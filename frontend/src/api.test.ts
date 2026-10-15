import { afterEach, expect, it, vi } from 'vitest';
import { API_BASE, checkHealth, decideToolInvocation, listPostings, reversePosting, getConfig, normalizeApiBase, sendFeedback, streamChat } from './api';

type Call = { url: string; init?: RequestInit };

function respondWith(body: unknown, status = 200): Call[] {
  const calls: Call[] = [];
  vi.stubGlobal('fetch', (url: string, init?: RequestInit) => {
    calls.push({ url, init });
    return Promise.resolve(new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } }));
  });
  return calls;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

it('reports the API unreachable when the request fails', async () => {
  vi.stubGlobal('fetch', () => Promise.reject(new TypeError('Failed to fetch')));
  expect(await checkHealth()).toBe(false);
});

it('reports the API connected on a 200', async () => {
  respondWith({ status: 'ok' });
  expect(await checkHealth()).toBe(true);
});

it('reverses with a key derived from the posting id so a retry replays', async () => {
  const calls = respondWith({ id: 'p2' }, 201);
  await reversePosting('p1');
  const reversal = calls.find((call) => call.url === `${API_BASE}/postings/p1/reversal`);
  expect(reversal).toBeDefined();
  expect(new Headers(reversal?.init?.headers).get('Idempotency-Key')).toBe('reverse:p1');
});

it('passes list filters as query parameters', async () => {
  const calls = respondWith({ items: [], next_cursor: null });
  await listPostings({ source: 'ai_tool', includeStress: true, limit: 20 });
  expect(calls[0].url).toBe(`${API_BASE}/postings?source=ai_tool&include_stress=true&limit=20`);
});

it('surfaces the problem detail as the error message', async () => {
  respondWith({ detail: 'Tool invocation i1 has already been decided.' }, 409);
  await expect(decideToolInvocation('i1', 'approved')).rejects.toThrow('already been decided');
});

it('fetches the deployment config once and retries after a failure', async () => {
  vi.stubGlobal('fetch', () => Promise.reject(new TypeError('Failed to fetch')));
  await expect(getConfig()).rejects.toThrow();
  const calls = respondWith({ chat_model: 'm' });
  await getConfig();
  await getConfig();
  expect(calls).toHaveLength(1);
});

it('defaults the API base to /api and strips trailing slashes', () => {
  expect(normalizeApiBase(undefined)).toBe('/api');
  expect(normalizeApiBase('https://api.example.com')).toBe('https://api.example.com');
  expect(normalizeApiBase('https://api.example.com/')).toBe('https://api.example.com');
  expect(normalizeApiBase('https://api.example.com//')).toBe('https://api.example.com');
});

it('posts a rating, and the comment only when there is one', async () => {
  const calls = respondWith({ id: 'f1' }, 201);
  await sendFeedback('t1', 'up');
  await sendFeedback('t1', 'down', 'Wrong tier.');
  const posts = calls.filter((call) => call.url === `${API_BASE}/chat/turns/t1/feedback`);
  expect(posts.map((call) => JSON.parse(String(call.init?.body)))).toEqual([{ rating: 'up' }, { rating: 'down', comment: 'Wrong tier.' }]);
  expect(posts[0].init?.method).toBe('POST');
});

it('rejects when the feedback is refused', async () => {
  respondWith({ detail: 'Chat turn t1 does not exist.' }, 404);
  await expect(sendFeedback('t1', 'up')).rejects.toThrow('does not exist');
});

function mockStream(chunks: string[], errorOnRead = false) {
  const calls: Call[] = [];
  vi.stubGlobal('fetch', (url: string, init?: RequestInit) => {
    calls.push({ url, init });
    if (url.includes('/timing')) {
      return Promise.resolve(new Response(JSON.stringify({ recorded: true }), { status: url.includes('error') ? 500 : 200 }));
    }
    const stream = new ReadableStream({
      start(controller) {
        if (errorOnRead) {
          controller.enqueue(new TextEncoder().encode(chunks[0]));
          controller.error(new Error('AbortError'));
        } else {
          chunks.forEach(c => controller.enqueue(new TextEncoder().encode(c)));
          controller.close();
        }
      }
    });
    return Promise.resolve(new Response(stream, { status: 200 }));
  });
  return calls;
}

it('posts TTFB after the first chunk and the final turn id', async () => {
  const calls = mockStream([
    'event: progress\ndata: {"step": "searching"}\n\n',
    'event: answer\ndata: {"text": "A", "citations": [], "turn_id": "t-1"}\n\n'
  ]);
  await streamChat('s', 'q', () => {});
  await new Promise(r => setTimeout(r, 10)); // wait for sendTiming to call fetch
  const timingCall = calls.find(c => c.url.includes('/timing'));
  expect(timingCall).toBeDefined();
  expect(timingCall?.url).toBe(`${API_BASE}/chat/turns/t-1/timing`);
  const body = JSON.parse(String(timingCall?.init?.body));
  expect(typeof body.ttfb_ms).toBe('number');
  expect(body.ttfb_ms).toBeGreaterThanOrEqual(0);
});

it('posts nothing when the stream ends in an error event (no turn id)', async () => {
  const calls = mockStream([
    'event: error\ndata: {"text": "something failed"}\n\n'
  ]);
  await streamChat('s', 'q', () => {});
  const timingCall = calls.find(c => c.url.includes('/timing'));
  expect(timingCall).toBeUndefined();
});

it('posts nothing and does not throw when the stream is aborted', async () => {
  const calls = mockStream(['event: progress\ndata: {"step": "start"}\n\n'], true);
  await expect(streamChat('s', 'q', () => {})).rejects.toThrow('AbortError');
  const timingCall = calls.find(c => c.url.includes('/timing'));
  expect(timingCall).toBeUndefined();
});

it('a failed timing post never reaches the caller', async () => {
  const calls = mockStream([
    'event: answer\ndata: {"text": "A", "citations": [], "turn_id": "error-1"}\n\n'
  ]);
  await expect(streamChat('s', 'q', () => {})).resolves.toBeUndefined();
  await new Promise(r => setTimeout(r, 10));
  const timingCall = calls.find(c => c.url.includes('/timing'));
  expect(timingCall).toBeDefined();
});

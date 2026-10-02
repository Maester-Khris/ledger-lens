import { afterEach, expect, it, vi } from 'vitest';
import { API_BASE, checkHealth, decideToolInvocation, listPostings, reversePosting, getConfig, normalizeApiBase } from './api';

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

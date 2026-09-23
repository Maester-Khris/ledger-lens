export const API_BASE: string = import.meta.env.VITE_API_BASE ?? '/api';

export type DocumentStatus = 'processing' | 'ready' | 'failed';

export interface DocumentEvent {
  stage: string;
  at: string;
  detail: Record<string, unknown>;
}

export interface DocumentSummary {
  id: string;
  document_key: string;
  title: string;
  source_url: string | null;
  version: number;
  version_id: string;
  page_count: number;
  byte_size: number;
  file_sha256: string;
  uploaded_at: string;
  element_count: number;
  status: DocumentStatus;
  status_note: string | null;
  events: DocumentEvent[];
}

export interface ElementPreview {
  ordinal: number;
  kind: string;
  section_path: string[];
  page_start: number;
  page_end: number;
  text: string;
}

export interface DocumentDetail extends DocumentSummary {
  preview: ElementPreview[];
}

export interface Citation {
  id: string;
  kind: 'element' | 'tool';
  document_title?: string;
  version?: number;
  page?: number;
  section?: string;
  quote?: string;
  file_url?: string;
  tool?: string;
}

export type ChatEvent =
  | { type: 'progress'; data: { step: string } }
  | { type: 'answer' | 'refused'; data: { text: string; citations: Citation[] } }
  | { type: 'error'; data: { text: string } };

async function json<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const problem = (await response.json().catch(() => ({}))) as { detail?: string };
    throw new Error(problem.detail ?? `Request failed (${response.status})`);
  }
  return (await response.json()) as T;
}

export function listDocuments(): Promise<DocumentSummary[]> {
  return fetch(`${API_BASE}/documents`).then((r) => json<DocumentSummary[]>(r));
}

export function getDocument(id: string): Promise<DocumentDetail> {
  return fetch(`${API_BASE}/documents/${id}`).then((r) => json<DocumentDetail>(r));
}

export function documentKeyFromName(name: string): string {
  const slug = name.toLowerCase().replace(/\.pdf$/, '').replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '');
  return (slug || 'document').slice(0, 64);
}

export function uploadDocument(file: File): Promise<{ document_id: string }> {
  const form = new FormData();
  form.append('file', file);
  form.append('document_key', documentKeyFromName(file.name));
  form.append('title', file.name);
  return fetch(`${API_BASE}/documents`, { method: 'POST', body: form }).then((r) => json<{ document_id: string }>(r));
}

export async function streamChat(sessionId: string, message: string, onEvent: (event: ChatEvent) => void): Promise<void> {
  const response = await fetch(`${API_BASE}/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ session_id: sessionId, message }),
  });
  if (!response.ok || !response.body) throw new Error(`Chat failed (${response.status})`);
  const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
  let buffer = '';
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += value;
    let boundary = buffer.indexOf('\n\n');
    while (boundary !== -1) {
      const block = buffer.slice(0, boundary);
      buffer = buffer.slice(boundary + 2);
      const fields = Object.fromEntries(block.split('\n').map((line) => [line.slice(0, line.indexOf(': ')), line.slice(line.indexOf(': ') + 2)]));
      if (fields.event && fields.data) onEvent({ type: fields.event, data: JSON.parse(fields.data) } as ChatEvent);
      boundary = buffer.indexOf('\n\n');
    }
  }
}

export function fileUrl(citation: Citation): string | undefined {
  return citation.file_url ? `${API_BASE}${citation.file_url}` : undefined;
}

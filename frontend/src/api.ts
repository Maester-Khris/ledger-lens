export const API_BASE: string = import.meta.env.VITE_API_BASE ?? '/api';
export const LANGFUSE_URL: string | undefined = import.meta.env.VITE_LANGFUSE_URL;

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
  kind: 'element' | 'tool' | 'system';
  document_title?: string;
  version?: number;
  page?: number;
  section?: string;
  quote?: string;
  file_url?: string;
  tool?: string;
  source?: string;
  detail?: string;
}

export interface UnvalidatedDto {
  document_id: string;
  title: string;
  fields: { path: string; label: string; reason: string | null }[];
}

export type ChatEvent =
  | { type: 'progress'; data: { step: string } }
  | { type: 'answer' | 'refused'; data: { text: string; citations: Citation[] } }
  | { type: 'error'; data: { text: string } }
  | { type: 'unvalidated'; data: UnvalidatedDto };

const GUEST_KEY = 'ledgerlens.guest';
let guestPromise: Promise<string> | null = null;

function storedGuest(): string | null {
  try { return localStorage.getItem(GUEST_KEY); } catch { return null; }
}

function storeGuest(id: string): void {
  try { localStorage.setItem(GUEST_KEY, id); } catch { /* storage blocked: the id lives for this tab only */ }
}

/** Registers once per page load; the server replaces an id it no longer knows (e.g. after a DB reset). */
export function guestId(): Promise<string> {
  guestPromise ??= (async () => {
    const known = storedGuest();
    const response = await fetch(`${API_BASE}/guests`, { method: 'POST', headers: known ? { 'X-Guest-Id': known } : {} });
    const { id } = await json<{ id: string }>(response);
    storeGuest(id);
    return id;
  })();
  return guestPromise;
}

export async function guestHeaders(): Promise<Record<string, string>> {
  try { return { 'X-Guest-Id': await guestId() }; } catch { return {}; }
}

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

export interface StreamChatOptions { documentId?: string }

export async function streamChat(
  sessionId: string, message: string, onEvent: (event: ChatEvent) => void, options: StreamChatOptions = {},
): Promise<void> {
  const response = await fetch(`${API_BASE}/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...(await guestHeaders()) },
    body: JSON.stringify({ session_id: sessionId, message, ...(options.documentId ? { document_id: options.documentId } : {}) }),
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

export type PostingSourceDto = 'api' | 'fee_run' | 'ai_tool' | 'stress_test';

export interface EntryDto {
  id: string;
  account_id: string;
  account_name: string;
  currency: string;
  direction: 'debit' | 'credit';
  amount: number;
}

export interface PostingDto {
  id: string;
  idempotency_key: string;
  description: string | null;
  effective_at: string;
  created_at: string;
  source: PostingSourceDto;
  reverses_posting_id: string | null;
  reversed_by_posting_id: string | null;
  entries: EntryDto[];
}

export interface PostingPage {
  items: PostingDto[];
  next_cursor: string | null;
}

export interface ProposedEntryDto {
  account_id: string;
  account_name: string;
  currency: string;
  direction: 'debit' | 'credit';
  amount: number;
}

export interface ToolDecisionDto {
  invocation_id: string;
  decision: 'approved' | 'rejected';
  decided_by: string;
  reason: string | null;
  decided_at: string;
  posting_id: string | null;
}

export interface ToolInvocationDto {
  id: string;
  session_id: string;
  trace_id: string | null;
  created_at: string;
  tool_name: string;
  tool_version: string;
  model_provider: string;
  model_id: string;
  prompt_version: string;
  temperature: string;
  input: Record<string, unknown>;
  result_amount_minor: number | null;
  result_currency: string | null;
  citation: Record<string, unknown> | null;
  proposed_entries: ProposedEntryDto[] | null;
  approval_required: boolean;
  decision: ToolDecisionDto | null;
}

export type ReviewDecision = 'confirmed' | 'corrected' | 'rejected';

export interface ReviewItemDto {
  run_id: string;
  field_path: string;
  value: unknown;
  quote: string;
  grounded: boolean;
  validator_errors: string[];
  page_grade: string;
  document_id: string;
  document_title: string;
  version: number;
  page: number | null;
}

export interface ReviewSubmission {
  run_id: string;
  field_path: string;
  decision: ReviewDecision;
  corrected_value: unknown;
  reason: string | null;
}

export interface ListPostingsOptions {
  source?: PostingSourceDto;
  includeStress?: boolean;
  limit?: number;
  cursor?: string;
}

export interface ListInvocationsOptions {
  pending?: boolean;
  postingId?: string;
  limit?: number;
  sessionId?: string;
}

function withQuery(path: string, params: Record<string, string | number | boolean | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) if (value !== undefined) search.set(key, String(value));
  const query = search.toString();
  return query ? `${path}?${query}` : path;
}

async function postJson(url: string, body: unknown, headers: Record<string, string> = {}): Promise<Response> {
  return fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...(await guestHeaders()), ...headers },
    body: JSON.stringify(body),
  });
}

export function listPostings(options: ListPostingsOptions = {}): Promise<PostingPage> {
  const url = withQuery(`${API_BASE}/postings`, {
    source: options.source,
    include_stress: options.includeStress,
    limit: options.limit,
    cursor: options.cursor,
  });
  return fetch(url).then((r) => json<PostingPage>(r));
}

// The key is derived from the posting, so a double click or a retry replays the same reversal.
export function reversePosting(postingId: string): Promise<PostingDto> {
  return postJson(`${API_BASE}/postings/${postingId}/reversal`, {}, { 'Idempotency-Key': `reverse:${postingId}` }).then((r) =>
    json<PostingDto>(r),
  );
}

export function listToolInvocations(options: ListInvocationsOptions = {}): Promise<ToolInvocationDto[]> {
  const url = withQuery(`${API_BASE}/tool-invocations`, {
    pending: options.pending,
    posting_id: options.postingId,
    limit: options.limit,
    session_id: options.sessionId,
  });
  return fetch(url).then((r) => json<ToolInvocationDto[]>(r));
}

export function decideToolInvocation(
  invocationId: string,
  decision: 'approved' | 'rejected',
  reason?: string,
): Promise<ToolDecisionDto> {
  return postJson(`${API_BASE}/tool-invocations/${invocationId}/decision`, { decision, reason: reason ?? null }).then((r) =>
    json<ToolDecisionDto>(r),
  );
}

export function listReviews(): Promise<ReviewItemDto[]> {
  return fetch(`${API_BASE}/reviews`).then((r) => json<ReviewItemDto[]>(r));
}

export function submitReview(input: ReviewSubmission): Promise<void> {
  return postJson(`${API_BASE}/reviews`, input).then((r) => json<unknown>(r)).then(() => undefined);
}

export function checkHealth(): Promise<boolean> {
  return fetch(`${API_BASE}/health`)
    .then((r) => r.ok)
    .catch(() => false);
}

export function documentPageUrl(documentId: string, version: number, page: number | null): string {
  const url = `${API_BASE}/documents/${documentId}/versions/${version}/file`;
  return page === null ? url : `${url}#page=${page}`;
}

export type EvalDto = {
  config_hash: string;
  chat_model: string;
  cases: number;
  numbers_ok: number;
  refusal_ok: number;
  citation_hit: number;
};
export type ConfigDto = {
  chat_model: string;
  extraction_model: string;
  embedding_model: string;
  embedding_dimensions: number;
  parser: string;
  pii: string;
  vector_store: string;
  retrieval: { search_candidates: number; min_dense_similarity: number };
  eval_config_hash: string;
};
export type StatsDto = {
  documents: { total: number; indexed: number; processing: number; failed: number; indexed_chunks: number };
  reviews_pending: number;
  approvals_pending: number;
  last_ingestion_at: string | null;
  chat: { turns_7d: number; latency_p50_ms: number | null; latency_p95_ms: number | null };
  eval: EvalDto | null;
  confidence_drop_rate: number | null;
  generated_at: string;
};

export async function getStats(): Promise<StatsDto> {
  return fetch(`${API_BASE}/stats`).then((r) => json<StatsDto>(r));
}

let cachedConfig: Promise<ConfigDto> | null = null;
export function getConfig(): Promise<ConfigDto> {
  if (cachedConfig === null) {
    cachedConfig = fetch(`${API_BASE}/config`).then((r) => json<ConfigDto>(r)).catch((err) => {
      cachedConfig = null;
      throw err;
    });
  }
  return cachedConfig;
}

export type FieldStatus = 'accepted' | 'confirmed' | 'corrected' | 'rejected' | 'needs_review';

export interface TermFieldDto {
  path: string; label: string; group: string; value: unknown;
  status: FieldStatus; reason: string | null; page: number | null; quote: string;
}

export interface TermsDto {
  document_id: string; title: string; version: number;
  extraction: { run_id: string; extracted_at: string; fields: TermFieldDto[] } | null;
  household: { id: string; name: string } | null;
  billing_schedule: { version: number; method: string; tiers: { up_to_minor: number | null; rate_bps: string }[]; valid_from: string | null } | null;
  coming_soon: string[];
}

export function getTerms(documentId: string): Promise<TermsDto> {
  return fetch(`${API_BASE}/documents/${documentId}/terms`).then((r) => json<TermsDto>(r));
}

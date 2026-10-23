import type { DocumentSummary, ReviewItemDto, ToolInvocationDto } from '../api';

const ACCEPTED_GRADES = ['GOOD', 'EXCELLENT'];

export function formatValue(value: unknown): string {
  return typeof value === 'string' ? value : JSON.stringify(value);
}

// A reviewer can type JSON (numbers, tier lists) or plain text; blank and null mean "nothing entered".
export function parseCorrection(text: string): unknown {
  const trimmed = text.trim();
  if (!trimmed) return undefined;
  try {
    const parsed: unknown = JSON.parse(trimmed);
    return parsed === null ? undefined : parsed;
  } catch {
    return trimmed;
  }
}

export function reviewReasons(item: ReviewItemDto): string[] {
  const reasons: string[] = [];
  if (!item.grounded) reasons.push('The quote was not found in the cited text.');
  for (const error of item.validator_errors) reasons.push(`Validator: ${error}`);
  if (!ACCEPTED_GRADES.includes(item.page_grade)) reasons.push(`Page quality is ${item.page_grade} (needs GOOD or better).`);
  return reasons;
}

export interface ViewerTarget {
  key: string;
  documentId: string;
  version: number;
  page: number | null;
  title: string;
}

export function fieldTarget(item: ReviewItemDto): ViewerTarget {
  return {
    key: `field:${item.run_id}:${item.field_path}`,
    documentId: item.document_id,
    version: item.version,
    page: item.page,
    title: item.document_title,
  };
}

export function approvalTarget(invocation: ToolInvocationDto, documents: DocumentSummary[]): ViewerTarget | null {
  const documentId = invocation.input.document_id;
  const doc = typeof documentId === 'string' ? documents.find((d) => d.id === documentId) : undefined;
  if (!doc) return null;
  const first = invocation.sources?.[0];  // a proposal opens at its first cited clause, in the version it cites
  return {
    key: `approval:${invocation.id}`, documentId: doc.id, version: first ? (invocation.document_version ?? doc.version) : doc.version,
    page: first ? first.page : null, title: doc.title,
  };
}

export interface DiffPart {
  text: string;
  changed: boolean;
}

export function diffParts(a: string, b: string): DiffPart[] {
  // ponytail: prefix/suffix diff; enough for one value against another
  if (a === '') return [];

  let prefixLen = 0;
  while (prefixLen < a.length && prefixLen < b.length && a[prefixLen] === b[prefixLen]) {
    prefixLen++;
  }

  let suffixLen = 0;
  const maxSuffix = Math.min(a.length - prefixLen, b.length - prefixLen);
  while (suffixLen < maxSuffix && a[a.length - 1 - suffixLen] === b[b.length - 1 - suffixLen]) {
    suffixLen++;
  }

  const parts: DiffPart[] = [];
  const prefix = a.slice(0, prefixLen);
  const middle = a.slice(prefixLen, a.length - suffixLen);
  const suffix = a.slice(a.length - suffixLen);

  if (prefix) parts.push({ text: prefix, changed: false });
  if (middle) parts.push({ text: middle, changed: true });
  if (suffix) parts.push({ text: suffix, changed: false });

  return parts;
}

export function flagReason(item: ReviewItemDto): string | null {
  if (!item.verification) return null;
  const v = item.verification;
  const label = v.layer === 'vision' ? 'Vision check' : v.layer === 'ocr_local' ? 'Local OCR check' : `${v.layer} check`;
  if (v.outcome === 'error') {
    return v.detail ? `${label} failed: ${v.detail}` : `${label} failed`;
  }
  if (v.outcome === 'unreadable') {
    return `${label} could not read it`;
  }
  if (v.detail) {
    return `${label}: ${v.detail}`;
  }
  if (v.read_value === null || v.read_value === undefined) {
    return `${label} found no value where extraction read one`;
  }
  return `${label} read ${formatValue(v.read_value)}, extraction read ${formatValue(item.value)}`;
}

export interface BandRow {
  index: number;
  extracted: { band_text: string; rate_text: string } | null;
  read: { band_text: string; rate_text: string } | null;
  changed: boolean;
}

interface BandItem {
  band_text?: unknown;
  rate_text?: unknown;
}

function parseBand(val: unknown): { band_text: string; rate_text: string } | null {
  if (val && typeof val === 'object' && 'band_text' in val && 'rate_text' in val) {
    const b = val as BandItem;
    return {
      band_text: typeof b.band_text === 'string' ? b.band_text : String(b.band_text ?? ''),
      rate_text: typeof b.rate_text === 'string' ? b.rate_text : String(b.rate_text ?? ''),
    };
  }
  return null;
}

export function bandRows(item: ReviewItemDto): BandRow[] {
  const extractedList = Array.isArray(item.value) ? item.value : [];
  const readList = Array.isArray(item.verification?.read_value) ? item.verification.read_value : [];
  const count = Math.max(extractedList.length, readList.length);
  const rows: BandRow[] = [];

  for (let i = 0; i < count; i++) {
    const extracted = i < extractedList.length ? parseBand(extractedList[i]) : null;
    const read = i < readList.length ? parseBand(readList[i]) : null;
    const changed =
      extracted === null ||
      read === null ||
      extracted.band_text !== read.band_text ||
      extracted.rate_text !== read.rate_text;
    rows.push({
      index: i + 1,
      extracted,
      read,
      changed,
    });
  }

  return rows;
}

export function canTakeVerifier(item: ReviewItemDto): boolean {
  if (!item.verification) return false;
  const readValue = item.verification.read_value;
  if (readValue === null || readValue === undefined) return false;
  if (item.field_path === 'fee_tiers') {
    if (!Array.isArray(readValue) || !Array.isArray(item.value)) return false;
    return readValue.length === item.value.length;
  }
  return true;
}

export function takeBlockedReason(item: ReviewItemDto): string | null {
  if (canTakeVerifier(item)) return null;
  const readValue = item.verification?.read_value;
  if (readValue === null || readValue === undefined) return 'The verifier read no value: keep, type or reject.';
  return 'The tables have a different number of bands: reject or type the value.';
}

export function verifierCorrection(item: ReviewItemDto): unknown {
  return item.verification?.read_value;
}

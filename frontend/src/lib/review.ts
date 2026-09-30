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
  return { key: `approval:${invocation.id}`, documentId: doc.id, version: doc.version, page: null, title: doc.title };
}

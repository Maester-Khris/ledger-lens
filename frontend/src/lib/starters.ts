import type { DocumentSummary } from '../api';
import starters from './starters.json';

// Every question here is an answerable case in backend/tests/eval/golden.json (backend test_starters_are_golden).
export const STARTERS: Record<string, string[]> = starters;
const MAX_UNSCOPED = 4;

/** The selected document's questions, or one per ready document when none is selected. */
export function startersFor(documents: DocumentSummary[], scopeId: string | null): string[] {
  const ready = documents.filter((d) => d.status === 'ready');
  if (scopeId !== null) return STARTERS[ready.find((d) => d.id === scopeId)?.document_key ?? ''] ?? [];
  return ready.flatMap((d) => (STARTERS[d.document_key] ?? []).slice(0, 1)).slice(0, MAX_UNSCOPED);
}

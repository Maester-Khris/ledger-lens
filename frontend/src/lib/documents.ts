import type { DocumentEvent, DocumentStatus } from '../api';

// Pipeline order (X1): values are verified before the document is indexed for search.
const STAGES = ['stored', 'parsed', 'extracted', 'verified', 'indexed'] as const;

const STAGE_LABELS: Record<(typeof STAGES)[number], string> = {
  stored: 'Stored (content-addressed)',
  parsed: 'Parsed + PII tokenised (Docling, Presidio)',
  extracted: 'Fee terms extracted',
  verified: 'Fee terms verified (local OCR re-read)',
  indexed: 'Indexed (Postgres full-text + Pinecone)',
};

export interface PipelineStep {
  stage: string;
  label: string;
  state: 'done' | 'active' | 'waiting' | 'failed';
  duration: string | null;
}

// The time between two events is the stage's own duration only when the stages ran back to back. A corpus ingested in
// stages over days made "Fee terms verified" read 253429.2s, so a long gap is shown as time waited ("+2.9 d").
export function formatGap(seconds: number): string {
  if (seconds < 600) return `${seconds.toFixed(1)}s`;
  if (seconds < 7200) return `+${Math.round(seconds / 60)} min`;
  if (seconds < 172800) return `+${(seconds / 3600).toFixed(1)} h`;
  return `+${(seconds / 86400).toFixed(1)} d`;
}

export function pipelineSteps(events: DocumentEvent[], status: DocumentStatus): PipelineStep[] {
  const reached = new Map<string, string | null>();
  events.forEach((e, i) => {
    if (!(STAGES as readonly string[]).includes(e.stage)) return;
    const seconds = i === 0 ? null : (Date.parse(e.at) - Date.parse(events[i - 1].at)) / 1000;
    reached.set(e.stage, seconds === null ? null : formatGap(seconds));
  });
  const failed = status === 'failed' || events.some((e) => e.stage === 'failed');
  let pendingMarked = false;
  const steps: PipelineStep[] = [];
  for (const stage of STAGES) {
    if (reached.has(stage)) {
      steps.push({ stage, label: STAGE_LABELS[stage], state: 'done', duration: reached.get(stage) ?? null });
    } else if (status !== 'ready') {
      const state = pendingMarked ? 'waiting' : failed ? 'failed' : 'active';
      pendingMarked = true;
      steps.push({ stage, label: STAGE_LABELS[stage], state, duration: null });
    }
  }
  return steps;
}

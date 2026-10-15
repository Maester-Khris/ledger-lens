import type { DocumentEvent, DocumentStatus } from '../api';

const STAGES = ['stored', 'parsed', 'indexed', 'extracted'] as const;

const STAGE_LABELS: Record<(typeof STAGES)[number], string> = {
  stored: 'Stored (content-addressed)',
  parsed: 'Parsed + PII tokenised (Docling, Presidio)',
  indexed: 'Indexed (Postgres full-text + Pinecone)',
  extracted: 'Fee terms extracted',
};

export interface PipelineStep {
  stage: string;
  label: string;
  state: 'done' | 'active' | 'waiting' | 'failed';
  duration: string | null;
}

export function pipelineSteps(events: DocumentEvent[], status: DocumentStatus): PipelineStep[] {
  const reached = new Map<string, string | null>();
  events.forEach((e, i) => {
    if (!(STAGES as readonly string[]).includes(e.stage)) return;
    const seconds = i === 0 ? null : (Date.parse(e.at) - Date.parse(events[i - 1].at)) / 1000;
    reached.set(e.stage, seconds === null ? null : `${seconds.toFixed(1)}s`);
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

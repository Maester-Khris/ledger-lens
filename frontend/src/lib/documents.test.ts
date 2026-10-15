import { describe, expect, it } from 'vitest';
import type { DocumentEvent } from '../api';
import { pipelineSteps } from './documents';

function event(stage: string, at: string): DocumentEvent {
  return { stage, at, detail: {} };
}

const STORED = event('stored', '2026-09-24T10:00:00Z');
const PARSED = event('parsed', '2026-09-24T10:00:12.5Z');
const INDEXED = event('indexed', '2026-09-24T10:00:15Z');
const EXTRACTED = event('extracted', '2026-09-24T10:00:30Z');

describe('pipelineSteps', () => {
  it('marks the next stage active while processing', () => {
    expect(pipelineSteps([STORED, PARSED], 'processing').map((s) => s.state)).toEqual(['done', 'done', 'active', 'waiting']);
  });

  it('marks the stage that did not complete as failed', () => {
    const steps = pipelineSteps([STORED, event('failed', '2026-09-24T10:00:05Z')], 'failed');
    expect(steps.map((s) => s.state)).toEqual(['done', 'failed', 'waiting', 'waiting']);
  });

  it('shows only completed stages with durations when ready', () => {
    const steps = pipelineSteps([STORED, PARSED, INDEXED, EXTRACTED], 'ready');
    expect(steps.map((s) => [s.stage, s.state, s.duration])).toEqual([
      ['stored', 'done', null],
      ['parsed', 'done', '12.5s'],
      ['indexed', 'done', '2.5s'],
      ['extracted', 'done', '15.0s'],
    ]);
  });

  it('labels stages in product language', () => {
    expect(pipelineSteps([STORED], 'processing')[1].label).toBe('Parsed + PII tokenised (Docling, Presidio)');
  });
});

import { describe, expect, it } from 'vitest';
import type { DocumentEvent } from '../api';
import { pipelineSteps } from './documents';

function event(stage: string, at: string): DocumentEvent {
  return { stage, at, detail: {} };
}

const STORED = event('stored', '2026-09-24T10:00:00Z');
const PARSED = event('parsed', '2026-09-24T10:00:12.5Z');
const EXTRACTED = event('extracted', '2026-09-24T10:00:27.5Z');
const VERIFIED = event('verified', '2026-09-24T10:00:30Z');
const INDEXED = event('indexed', '2026-09-24T10:00:45Z');

describe('pipelineSteps', () => {
  it('marks the next stage active while processing', () => {
    expect(pipelineSteps([STORED, PARSED], 'processing').map((s) => s.state)).toEqual(['done', 'done', 'active', 'waiting', 'waiting']);
  });

  it('marks the stage that did not complete as failed', () => {
    const steps = pipelineSteps([STORED, event('failed', '2026-09-24T10:00:05Z')], 'failed');
    expect(steps.map((s) => s.state)).toEqual(['done', 'failed', 'waiting', 'waiting', 'waiting']);
  });

  it('shows only completed stages with durations when ready', () => {
    const steps = pipelineSteps([STORED, PARSED, EXTRACTED, VERIFIED, INDEXED], 'ready');
    expect(steps.map((s) => [s.stage, s.state, s.duration])).toEqual([
      ['stored', 'done', null],
      ['parsed', 'done', '12.5s'],
      ['extracted', 'done', '15.0s'],
      ['verified', 'done', '2.5s'],
      ['indexed', 'done', '15.0s'],
    ]);
  });

  it('shows a long gap between steps as time waited, not as the stage taking that long', () => {
    // a corpus ingested in stages over days showed "Fee terms verified 253429.2s" for a 5-page document
    const steps = pipelineSteps(
      [
        event('stored', '2026-10-15T06:50:00Z'),
        event('parsed', '2026-10-15T07:16:46.9Z'), // 1606.9 s after the previous step
        event('extracted', '2026-10-15T07:25:00Z'), // 493.1 s
        event('verified', '2026-10-18T05:50:00Z'), // 253,500 s, about 2.9 days
        event('indexed', '2026-10-18T09:50:00Z'), // 4 hours
      ],
      'ready',
    );
    expect(steps.map((s) => s.duration)).toEqual([null, '+27 min', '493.1s', '+2.9 d', '+4.0 h']);
  });

  it('labels stages in product language', () => {
    expect(pipelineSteps([STORED], 'processing')[1].label).toBe('Parsed + PII tokenised (Docling, Presidio)');
  });
});

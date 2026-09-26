import { describe, expect, it } from 'vitest';
import type { EvalDto } from '../api';
import { evalScore, formatAgo, formatMs, formatPercent } from './stats';

const EVAL: EvalDto = { config_hash: 'abc', chat_model: 'm', cases: 8, numbers_ok: 1, refusal_ok: 0.875, citation_hit: 0.875 };

describe('stats formatting', () => {
  it('formats ratios as percentages with at most one decimal', () => {
    expect(formatPercent(0.875)).toBe('87.5%');
    expect(formatPercent(1)).toBe('100%');
  });

  it('scores the golden set as the mean of its three checks', () => {
    expect(evalScore(EVAL)).toBeCloseTo(0.9167, 3);
  });

  it('formats latency and shows a dash when there is none', () => {
    expect(formatMs(412)).toBe('412 ms');
    expect(formatMs(1830)).toBe('1.8 s');
    expect(formatMs(null)).toBe('—');
  });

  it('describes how long ago something happened', () => {
    const now = Date.parse('2026-09-26T12:00:00Z');
    expect(formatAgo('2026-09-26T11:59:30Z', now)).toBe('just now');
    expect(formatAgo('2026-09-26T11:43:00Z', now)).toBe('17 min ago');
    expect(formatAgo('2026-09-26T09:00:00Z', now)).toBe('3 h ago');
    expect(formatAgo('2026-09-24T12:00:00Z', now)).toBe('2 d ago');
  });
});

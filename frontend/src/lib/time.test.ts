import { expect, it } from 'vitest';
import { formatUtc, formatUtcFull } from './time';

it('formats an ISO timestamp as a short UTC label', () => {
  expect(formatUtc('2026-09-22T14:22:04Z')).toBe('22 Sep 2026 14:22 UTC');
});

it('formats an ISO timestamp with seconds', () => {
  expect(formatUtcFull('2026-09-22T14:22:04Z')).toBe('22 Sep 2026 14:22:04 UTC');
});

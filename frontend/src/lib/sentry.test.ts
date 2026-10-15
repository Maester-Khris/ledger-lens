import { describe, expect, it, vi } from 'vitest';

vi.mock('@sentry/react', () => ({ init: vi.fn() }));
import * as Sentry from '@sentry/react';
import { initSentry } from './sentry';

describe('initSentry', () => {
  it('does nothing without a DSN', () => {
    expect(initSentry(undefined)).toBe(false);
    expect(initSentry('')).toBe(false);
    expect(Sentry.init).not.toHaveBeenCalled();
  });

  it('initialises with the DSN, no PII and no traces', () => {
    const dsn = 'https://key@example.ingest.us.sentry.io/1';
    expect(initSentry(dsn)).toBe(true);
    expect(Sentry.init).toHaveBeenCalledWith(expect.objectContaining({
      dsn, sendDefaultPii: false, tracesSampleRate: 0,
    }));
  });
});

import { describe, expect, it } from 'vitest';
import { BUSY_HOLD_MS, MAX_AUTO_RETRIES, busyMessage, isWaiting, nextBusyStep } from './busy';

describe('nextBusyStep', () => {
  it('retries by itself after a short wait', () => {
    expect(nextBusyStep(3, 0)).toEqual({ kind: 'retry', waitMs: 3000 });
    expect(nextBusyStep(10, MAX_AUTO_RETRIES - 1)).toEqual({ kind: 'retry', waitMs: 10000 });
  });

  it('stops retrying after the allowed attempts and holds the busy state for a minute', () => {
    expect(nextBusyStep(3, MAX_AUTO_RETRIES)).toEqual({ kind: 'busy', waitMs: BUSY_HOLD_MS });
    expect(BUSY_HOLD_MS).toBe(60000);
  });

  it('does not retry by itself when the server asks for a long wait', () => {
    expect(nextBusyStep(30, 0)).toEqual({ kind: 'busy', waitMs: 30000 });
  });

  it('never waits less than a second', () => {
    expect(nextBusyStep(0, 0).waitMs).toBe(1000);
  });
});

describe('busyMessage', () => {
  const now = 1_000_000;

  it('says it is retrying when the wait is ten seconds or less', () => {
    expect(busyMessage(now + 3000, now)).toBe('High demand, retrying in 3 seconds.');
    expect(busyMessage(now + 1000, now)).toBe('High demand, retrying in 1 second.');
  });

  it('never says zero or a negative number of seconds', () => {
    expect(busyMessage(now - 5000, now)).toBe('High demand, retrying in 1 second.');
  });

  it('asks to try again in whole minutes for a long wait', () => {
    expect(busyMessage(now + 60000, now)).toBe('The assistant is busy right now. Try again in about 1 minute.');
    expect(busyMessage(now + 61000, now)).toBe('The assistant is busy right now. Try again in about 2 minutes.');
  });
});

describe('isWaiting', () => {
  it('is idle with no pending turn and no busy period', () => {
    expect(isWaiting(false, null, 0)).toBe(false);
  });

  it('waits while a turn is pending, retries included', () => {
    expect(isWaiting(true, null, 0)).toBe(true);
  });

  it('waits until the busy period has passed', () => {
    expect(isWaiting(false, 5000, 4000)).toBe(true);
    expect(isWaiting(false, 5000, 6000)).toBe(false);
  });
});

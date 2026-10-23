// Retries stay few and short, and the server adds jitter to Retry-After, so refused clients do not come back all at once.
export const SHORT_WAIT_SECONDS = 10;
export const MAX_AUTO_RETRIES = 3;
export const BUSY_HOLD_MS = 60_000;

export interface BusyStep {
  kind: 'retry' | 'busy';
  waitMs: number;
}

export function nextBusyStep(retryAfterSeconds: number, attempt: number): BusyStep {
  const seconds = Math.max(1, retryAfterSeconds);
  if (seconds > SHORT_WAIT_SECONDS) return { kind: 'busy', waitMs: seconds * 1000 };
  if (attempt < MAX_AUTO_RETRIES) return { kind: 'retry', waitMs: seconds * 1000 };
  return { kind: 'busy', waitMs: BUSY_HOLD_MS };
}

export function busyMessage(busyUntil: number, now: number): string {
  const remaining = Math.max(1, Math.ceil((busyUntil - now) / 1000));
  if (remaining <= SHORT_WAIT_SECONDS) {
    return `High demand, retrying in ${remaining} second${remaining === 1 ? '' : 's'}.`;
  }
  const minutes = Math.max(1, Math.ceil((busyUntil - now) / 60_000));
  return `The assistant is busy right now. Try again in about ${minutes} minute${minutes === 1 ? '' : 's'}.`;
}

export function isWaiting(turnPending: boolean, busyUntil: number | null, now: number): boolean {
  return turnPending || (busyUntil !== null && now < busyUntil);
}

import * as Sentry from '@sentry/react';

/** Drops chat request bodies and every fetch or XHR breadcrumb that calls /chat (spec P6, section 2). */
function scrubEvent<T extends Sentry.ErrorEvent>(event: T): T {
  if (event.request) delete event.request.data;
  event.breadcrumbs = event.breadcrumbs?.filter((b) => !((b.category === 'fetch' || b.category === 'xhr') && String(b.data?.url ?? '').includes('/chat')));
  return event;
}

/** Initialises Sentry only when a DSN is configured. Returns whether it did. */
export function initSentry(dsn: string | undefined): boolean {
  if (!dsn) return false;
  // @ts-expect-error sendDefaultPii is in the spec and test, but not in BrowserOptions types
  Sentry.init({ dsn, sendDefaultPii: false, tracesSampleRate: 0, beforeSend: scrubEvent });
  return true;
}

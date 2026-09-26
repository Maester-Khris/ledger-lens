import type { EvalDto } from '../api';

export function formatPercent(ratio: number): string {
  return `${(ratio * 100).toLocaleString(undefined, { maximumFractionDigits: 1 })}%`;
}

export function evalScore(summary: EvalDto): number {
  return (summary.numbers_ok + summary.refusal_ok + summary.citation_hit) / 3;
}

export function formatMs(ms: number | null): string {
  if (ms === null) return '—';
  if (ms < 1000) return `${ms} ms`;
  return `${(ms / 1000).toLocaleString(undefined, { maximumFractionDigits: 1 })} s`;
}

export function formatAgo(timestamp: string, now = Date.now()): string {
  const diffMs = Math.max(0, now - Date.parse(timestamp));
  if (diffMs < 60_000) return 'just now';
  const mins = diffMs / 60_000;
  if (mins < 60) return `${Math.floor(mins)} min ago`;
  const hours = mins / 60;
  if (hours < 24) return `${Math.floor(hours)} h ago`;
  return `${Math.floor(hours / 24)} d ago`;
}

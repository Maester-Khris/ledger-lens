import type { EvalDto } from '../api';

export function formatPercent(ratio: number): string {
  return `${Number((ratio * 100).toFixed(1))}%`;
}

export function evalScore(evaluation: EvalDto): number {
  return (evaluation.numbers_ok + evaluation.refusal_ok + evaluation.citation_hit) / 3;
}

export function formatMs(ms: number | null): string {
  if (ms === null) return '-';
  return ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`;
}

export function formatAgo(iso: string, now: number): string {
  const minutes = Math.floor((now - Date.parse(iso)) / 60000);
  if (minutes < 1) return 'just now';
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.floor(minutes / 60);
  return hours < 24 ? `${hours} h ago` : `${Math.floor(hours / 24)} d ago`;
}

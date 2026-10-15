// "Tue, 22 Sep 2026 14:22:04 GMT" → "22 Sep 2026 14:22"
export function formatUtc(iso: string): string {
  return `${new Date(iso).toUTCString().slice(5, 22)} UTC`;
}

export function formatUtcFull(iso: string): string {
  return `${new Date(iso).toUTCString().slice(5, 25)} UTC`;
}

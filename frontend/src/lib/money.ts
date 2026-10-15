export function formatMinor(amountMinor: number, currency: string): string {
  const major = (amountMinor / 100).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return `${major} ${currency}`;
}

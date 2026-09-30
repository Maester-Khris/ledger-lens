import { expect, it } from 'vitest';
import { formatMinor } from './money';

it('formats minor units with two decimals, grouping and the currency code', () => {
  expect(formatMinor(150000, 'CAD')).toBe('1,500.00 CAD');
  expect(formatMinor(5, 'USD')).toBe('0.05 USD');
  expect(formatMinor(0, 'CAD')).toBe('0.00 CAD');
});

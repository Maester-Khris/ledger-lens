import { expect, it } from 'vitest';
import { nextFlowPhase } from './flowPhase';

it('advances one phase at a time', () => {
  expect(nextFlowPhase(0, 7)).toBe(1);
  expect(nextFlowPhase(5, 7)).toBe(6);
});

it('holds on the last phase and never loops back to the first', () => {
  expect(nextFlowPhase(6, 7)).toBe(6);
  expect(nextFlowPhase(99, 7)).toBe(6);
});

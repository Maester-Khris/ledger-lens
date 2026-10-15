/** The hero diagram plays once and holds on its last phase; it never loops back to the first. */
export function nextFlowPhase(phase: number, phaseCount: number): number {
  return Math.min(phase + 1, phaseCount - 1);
}

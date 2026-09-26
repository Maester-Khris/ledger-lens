export const ZOOM_STEPS = [0.5, 0.75, 1, 1.25, 1.5, 2] as const;

export function clampPage(page: number | null | undefined, numPages: number): number {
  const wanted = Math.trunc(page ?? 1) || 1;
  return Math.min(Math.max(1, wanted), Math.max(1, numPages));
}

export function nextZoom(current: number, direction: 1 | -1): number {
  const index = ZOOM_STEPS.findIndex((step) => step === current);
  const from = index === -1 ? ZOOM_STEPS.indexOf(1) : index;
  return ZOOM_STEPS[Math.min(Math.max(from + direction, 0), ZOOM_STEPS.length - 1)];
}

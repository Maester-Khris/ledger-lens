import { useEffect, useRef, useState } from 'react';

/** Counts 0 → target over durationMs while active; resets to 0 when inactive; jumps straight to
 * target when reduced (no animation at all, per prefers-reduced-motion). */
export function useCountUp(target: number, active: boolean, durationMs: number, reduced: boolean): number {
  const [value, setValue] = useState(reduced ? target : 0);
  const frameRef = useRef<number | null>(null);

  useEffect(() => {
    if (reduced) {
      requestAnimationFrame(() => setValue(target));
      return;
    }
    if (!active) {
      requestAnimationFrame(() => setValue(0));
      return;
    }
    const start = performance.now();
    const tick = (now: number) => {
      const t = Math.min(1, (now - start) / durationMs);
      setValue(target * t);
      if (t < 1) frameRef.current = requestAnimationFrame(tick);
    };
    frameRef.current = requestAnimationFrame(tick);
    return () => {
      if (frameRef.current !== null) cancelAnimationFrame(frameRef.current);
    };
  }, [active, target, durationMs, reduced]);

  return value;
}

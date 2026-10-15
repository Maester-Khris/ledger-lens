import { useEffect, useState } from 'react';
import { getConfig } from '../api';

/** True when the API runs as the public demo (writes to shared state are off). False until /config answers. */
export function useDemoMode(): boolean {
  const [demoMode, setDemoMode] = useState(false);
  useEffect(() => {
    let cancelled = false;
    getConfig()
      .then((c) => !cancelled && setDemoMode(c.demo_mode))
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, []);
  return demoMode;
}

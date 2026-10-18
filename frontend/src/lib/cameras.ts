import { useCallback, useEffect, useState } from 'react';
import { api } from '../api';
import type { Camera } from '../types';

export function useCameras() {
  const [cams, setCams] = useState<Camera[]>([]);
  const [error, setError] = useState<string | null>(null);
  const refresh = useCallback(async () => {
    try { setCams((await api<{ cameras: Camera[] }>('/ui/api/cameras')).cameras); setError(null); }
    catch (e) { setError((e as Error).message); }
  }, []);
  useEffect(() => { refresh(); const id = setInterval(refresh, 10000); return () => clearInterval(id); }, [refresh]);
  return { cams, refresh, error };
}

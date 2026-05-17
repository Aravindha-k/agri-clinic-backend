import { useCallback, useEffect, useRef, useState } from 'react';
import { fetchCropsCatalog, fetchDistricts, MasterCrop, MasterDistrict } from '@/lib/api';

const TTL_MS = 15 * 60 * 1000;

type CacheEntry<T> = { at: number; data: T };

const districtsCache = { current: null as CacheEntry<MasterDistrict[]> | null };
const cropsCache = { current: null as CacheEntry<MasterCrop[]> | null };

export function useMasters(token: string | null) {
  const [districts, setDistricts] = useState<MasterDistrict[]>([]);
  const [crops, setCrops] = useState<MasterCrop[]>([]);
  const loading = useRef(false);

  const load = useCallback(async () => {
    if (!token || loading.current) return;
    loading.current = true;
    try {
      const now = Date.now();
      let d = districtsCache.current;
      if (!d || now - d.at > TTL_MS) {
        const list = await fetchDistricts(token);
        districtsCache.current = { at: now, data: list };
        d = districtsCache.current;
      }
      setDistricts(d!.data);

      let c = cropsCache.current;
      if (!c || now - c.at > TTL_MS) {
        const list = await fetchCropsCatalog(token);
        cropsCache.current = { at: now, data: list };
        c = cropsCache.current;
      }
      setCrops(c!.data);
    } finally {
      loading.current = false;
    }
  }, [token]);

  useEffect(() => {
    void load();
  }, [load]);

  return { districts, crops, reload: load };
}

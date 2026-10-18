import { useCallback, useEffect, useState } from 'react';
import { api } from '../api';
import { useI18n } from '../i18n';
import type { RuleType } from '../types';

export interface RulesData { types: RuleType[]; sources: Record<string, { url?: string; label?: string; short?: string }> }

let cache: RulesData | null = null;
let inflight: Promise<RulesData> | null = null;

export function useRules() {
  const [data, setData] = useState<RulesData | null>(cache);
  const [error, setError] = useState('');
  useEffect(() => {
    if (cache) return;
    inflight ??= api<RulesData>('/ui/api/rules').then(d => { cache = d; return d; }).finally(() => { inflight = null; });
    let alive = true;
    inflight.then(d => { if (alive) setData(d); }).catch(e => { if (alive) setError((e as Error).message); });
    return () => { alive = false; };
  }, []);
  return { data, types: data?.types || [], error };
}

export function useTypeNames() {
  const { typeName } = useI18n();
  const { types } = useRules();
  return useCallback((code: string) => typeName(code, types.find(x => x.code === code)?.type || code), [typeName, types]);
}

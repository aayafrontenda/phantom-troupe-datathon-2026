import { useCallback, useEffect, useState } from 'react';
import { api } from '../api';
import { useI18n } from '../i18n';
import type { RuleType } from '../types';

export interface RulesData { types: RuleType[]; sources: Record<string, { url?: string; label?: string; short?: string }> }

let cache: RulesData | null = null;
let inflight: Promise<RulesData> | null = null;

/** The violation catalogue (/ui/api/rules), fetched once per session and shared between pages. */
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

/** Type name for a bare code (live tiles): the Russian name comes from the catalogue, other languages from the kb. */
export function useTypeNames() {
  const { typeName } = useI18n();
  const { types } = useRules();
  return useCallback((code: string) => typeName(code, types.find(x => x.code === code)?.type || code), [typeName, types]);
}

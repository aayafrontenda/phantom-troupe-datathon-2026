import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';
import { LANGS, STRINGS, type Lang } from './strings';

export type { Lang };
export { LANGS };

export interface KbType { name: string; visual?: string; why?: string; caveat?: string }
export interface KbData {
  types: Record<string, Partial<Record<Lang, KbType>>>;
  sources: Record<string, { match: string } & Partial<Record<Lang, string>>>;
}

const LANG_KEY = 'cg_lang';

function initialLang(): Lang {
  try {
    const l = localStorage.getItem(LANG_KEY);
    if (l && l in STRINGS) return l as Lang;
  } catch {}
  const nav = (navigator.language || '').slice(0, 2);
  return nav === 'en' ? 'en' : nav === 'kk' ? 'kk' : 'ru';
}

type Vars = Record<string, string | number | undefined>;

interface I18n {
  lang: Lang;
  setLang: (l: Lang) => void;
  t: (key: string, vars?: Vars) => string;
  has: (key: string) => boolean;
  kb: KbData;
  typeName: (code: string | null | undefined, fallback?: string | null) => string;
  typeField: (code: string | null | undefined, field: keyof KbType, fallback?: string | null) => string;
  docName: (ref: { document?: string; url?: string }) => string;
  pointName: (p?: string | null) => string;
  docUrl: (url?: string | null) => string;
  locale: string;
}

const Ctx = createContext<I18n | null>(null);
const EMPTY_KB: KbData = { types: {}, sources: {} };

export function I18nProvider({ children }: { children: ReactNode }) {
  const [lang, setLangState] = useState<Lang>(initialLang);
  const [kb, setKb] = useState<KbData>(EMPTY_KB);

  useEffect(() => {
    fetch('/ui/api/i18n/kb').then(r => r.json()).then(d => setKb({ types: d.types || {}, sources: d.sources || {} })).catch(() => { });
  }, []);

  useEffect(() => { document.documentElement.lang = lang; }, [lang]);

  const setLang = useCallback((l: Lang) => {
    if (!(l in STRINGS)) return;
    setLangState(l);
    try { localStorage.setItem(LANG_KEY, l); } catch {}
  }, []);

  const value = useMemo<I18n>(() => {
    const rules = new Intl.PluralRules(LANGS[lang].locale);
    const pluralIndex = (n: number) => {
      const c = rules.select(n);
      if (lang === 'ru') return c === 'one' ? 0 : c === 'few' ? 1 : 2;
      return c === 'one' ? 0 : 1;
    };
    const t = (key: string, vars: Vars = {}) => {
      let s = STRINGS[lang][key] ?? STRINGS.en[key] ?? key;
      if (Array.isArray(s)) s = s[Math.min(s.length - 1, pluralIndex(Number(vars.n) || 0))];
      return s.replace(/\{(\w+)\}/g, (m, k) => (vars[k] === undefined ? m : String(vars[k])));
    };
    const kbType = (code: string | null | undefined) => (code && kb.types[code] && kb.types[code][lang]) || null;
    const typeName = (code: string | null | undefined, fallback?: string | null) =>
      (lang !== 'ru' && kbType(code)?.name) || fallback || code || '';
    const typeField = (code: string | null | undefined, field: keyof KbType, fallback?: string | null) =>
      (lang !== 'ru' && kbType(code)?.[field]) || fallback || '';
    const docName = (ref: { document?: string; url?: string }) => {
      if (lang === 'ru') return ref.document || '';
      const url = ref.url || '';
      const src = Object.values(kb.sources).find(s => (url ? s.match && url.includes(s.match) : s.match === ''));
      return (src && src[lang]) || ref.document || '';
    };
    const pointName = (p?: string | null) => {
      if (!p || lang === 'ru') return p || '';
      if (lang === 'en') return p.replace(/ст\.\s*/g, 'Art. ').replace(/пп\.\s*/g, 'subpara. ').replace(/п\.\s*/g, 'para. ');
      return p.replace(/ст\.\s*(\S+)/g, '$1-бап').replace(/пп\.\s*(\S+)/g, '$1-тармақша').replace(/п\.\s*(\S+)/g, '$1-тармақ');
    };
    const docUrl = (url?: string | null) => (lang === 'kk' && url ? url.replace('/rus/docs/', '/kaz/docs/') : url || '');
    return { lang, setLang, t, has: (k: string) => STRINGS[lang][k] !== undefined, kb, typeName, typeField, docName, pointName, docUrl, locale: LANGS[lang].locale };
  }, [lang, kb, setLang]);

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useI18n(): I18n {
  const v = useContext(Ctx);
  if (!v) throw new Error('useI18n outside provider');
  return v;
}

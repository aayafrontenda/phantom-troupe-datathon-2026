/* Small shared UI: icons, toasts, modals, lightbox, formatting helpers. */
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { useI18n } from './i18n';

/* ---------- icons ---------- */
const PATHS: Record<string, string> = {
  up: '<path d="M12 15V4M7 9l5-5 5 5M5 15v4.5h14V15"/>',
  play: '<path d="M8 5.5v13l10.5-6.5z" fill="currentColor" stroke="none"/>',
  pause: '<path d="M7 5h3.5v14H7zM13.5 5H17v14h-3.5z" fill="currentColor" stroke="none"/>',
  back: '<path d="M14.5 6l-6 6 6 6"/>',
  check: '<path d="M5 12.5l4.5 4.5L19 7.5"/>',
  x: '<path d="M6.5 6.5l11 11M17.5 6.5l-11 11"/>',
  alert: '<path d="M12 4l9 16H3z"/><path d="M12 10v4.2M12 17.2v.3"/>',
  shield: '<path d="M12 3l8 3v6c0 4.6-3.4 8.1-8 9-4.6-.9-8-4.4-8-9V6z"/><path d="M8.5 12l2.5 2.5 4.5-5"/>',
  film: '<rect x="4" y="3.5" width="16" height="17" rx="2.5"/><path d="M8 3.5v17M16 3.5v17M4 9h4M4 15h4M16 9h4M16 15h4"/>',
  cam: '<rect x="3" y="6.5" width="13" height="11" rx="2.5"/><path d="M16 10.5l5-3v9l-5-3"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  link: '<path d="M14 4h6v6M20 4l-8.5 8.5M18 14v5.5H4.5V6H10"/>',
  trash: '<path d="M4.5 7h15M9.5 7V4.5h5V7M6.5 7l1 13h9l1-13M10 11v5.5M14 11v5.5"/>',
  doc: '<path d="M6 3.5h8l4 4v13H6z"/><path d="M14 3.5v4h4M9 12h6M9 16h6"/>',
  clip: '<rect x="3.5" y="5.5" width="17" height="13" rx="2.5"/><path d="M10 9.5v5l4-2.5z" fill="currentColor" stroke="none"/>',
  search: '<circle cx="11" cy="11" r="6.5"/><path d="M16 16l4.5 4.5"/>',
  moon: '<path d="M19.5 14.5A8 8 0 0 1 9.5 4.5a8 8 0 1 0 10 10z"/>',
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2.5v2M12 19.5v2M2.5 12h2M19.5 12h2M5.3 5.3l1.4 1.4M17.3 17.3l1.4 1.4M5.3 18.7l1.4-1.4M17.3 6.7l1.4-1.4"/>',
  chev: '<path d="M9 6l6 6-6 6"/>',
  lock: '<rect x="5" y="10.5" width="14" height="10" rx="2"/><path d="M8.5 10.5V8a3.5 3.5 0 0 1 7 0v2.5"/>',
  user: '<circle cx="12" cy="8" r="4"/><path d="M4.5 20.5a7.5 7.5 0 0 1 15 0"/>',
  logout: '<path d="M10 4.5H5.5v15H10M15 8l4 4-4 4M19 12H9"/>',
  edit: '<path d="M4 20h4l10.5-10.5-4-4L4 16z"/><path d="M12.5 7.5l4 4"/>',
  eye: '<path d="M2.5 12s3.5-6.5 9.5-6.5 9.5 6.5 9.5 6.5-3.5 6.5-9.5 6.5S2.5 12 2.5 12z"/><circle cx="12" cy="12" r="2.8"/>',
  flag: '<path d="M5.5 21V4h11l-2 4 2 4h-11"/>',
  undo: '<path d="M8 7H4v4M4 11a8 8 0 1 1 2.3 7"/>',
  clock: '<circle cx="12" cy="12" r="8.5"/><path d="M12 7.5V12l3 2"/>',
  tg: '<path d="M21 4.5L2.8 11.4l5.7 2.1 2.2 6.6 3.3-4.2 4.7 3.6z"/><path d="M8.5 13.5l12.5-9"/>',
  download: '<path d="M12 4v11M7 10l5 5 5-5M5 19.5h14"/>',
  users: '<circle cx="9" cy="8" r="3.5"/><path d="M2.5 19.5a6.5 6.5 0 0 1 13 0M15.5 5a3.5 3.5 0 0 1 0 7M18 13.5a6 6 0 0 1 3.5 6"/>',
  settings: '<circle cx="12" cy="12" r="3"/><path d="M12 2.5v3M12 18.5v3M2.5 12h3M18.5 12h3M5.3 5.3l2.1 2.1M16.6 16.6l2.1 2.1M5.3 18.7l2.1-2.1M16.6 7.4l2.1-2.1"/>',
};
export function Icon({ id, className = '' }: { id: string; className?: string }) {
  return <svg className={`i ${className}`} viewBox="0 0 24 24" aria-hidden="true" dangerouslySetInnerHTML={{ __html: PATHS[id] || '' }} />;
}

/* ---------- formatting ---------- */
export const tc = (t: number | null | undefined) => {
  const v = Math.max(0, Number(t) || 0);
  const m = Math.floor(v / 60);
  return `${String(m).padStart(2, '0')}:${(v - m * 60).toFixed(1).padStart(4, '0')}`;
};
export const esc = (s: unknown) => String(s ?? '');
export const shortDesc = (d?: string | null) => String(d || '').split(/\s*Основание:/)[0].replace(/\s*Прямой публичной нормы не установлено\.?$/, '').trim();
export const observedPart = (d?: string | null) => {
  const p = shortDesc(d).split(/\s*Это может указывать на нарушение:\s*/);
  return p.length > 1 ? p[0].replace(/\.$/, '') : '';
};

export function useAgo() {
  const { t, locale } = useI18n();
  return useCallback((ts: number | null | undefined) => {
    if (!ts) return '';
    const s = Math.max(0, Date.now() / 1000 - ts);
    if (s < 60) return t('ago.now');
    if (s < 3600) return t('ago.min', { n: Math.floor(s / 60) });
    const d = new Date(ts * 1000), today = new Date();
    const hm = d.toTimeString().slice(0, 5);
    return d.toDateString() === today.toDateString() ? t('ago.today', { t: hm }) : `${d.toLocaleDateString(locale)} ${hm}`;
  }, [t, locale]);
}
export function fmtDate(ts: number | null | undefined, locale: string) {
  if (!ts) return '';
  const d = new Date(ts * 1000);
  return `${d.toLocaleDateString(locale)} ${d.toTimeString().slice(0, 5)}`;
}

/* ---------- toasts / modal / lightbox ---------- */
interface Toast { id: number; msg: string; kind: '' | 'err' }
interface ModalItem { id: number; wide: boolean; render: (close: (v: unknown) => void) => ReactNode; resolve: (v: unknown) => void }
interface UiCtx {
  toast: (msg: string, kind?: '' | 'err') => void;
  modal: <T,>(render: (close: (v: T | null) => void) => ReactNode, wide?: boolean) => Promise<T | null>;
  confirm: (title: string, text: ReactNode, okLabel: string, danger?: boolean) => Promise<boolean>;
  zoom: (src: string, cap: string) => void;
}
const Ui = createContext<UiCtx | null>(null);

export function UiProvider({ children }: { children: ReactNode }) {
  const { t } = useI18n();
  const [toasts, setToasts] = useState<Toast[]>([]);
  const [modals, setModals] = useState<ModalItem[]>([]);
  const [lb, setLb] = useState<{ src: string; cap: string } | null>(null);
  const seq = useRef(0);

  const toast = useCallback((msg: string, kind: '' | 'err' = '') => {
    const id = ++seq.current;
    setToasts(x => [...x, { id, msg, kind }]);
    setTimeout(() => setToasts(x => x.filter(y => y.id !== id)), 4200);
  }, []);

  const closeModal = useCallback((id: number, v: unknown) => {
    setModals(m => {
      const item = m.find(x => x.id === id);
      item?.resolve(v);
      return m.filter(x => x.id !== id);
    });
  }, []);

  const modal = useCallback(<T,>(render: (close: (v: T | null) => void) => ReactNode, wide = false) => new Promise<T | null>(resolve => {
    const id = ++seq.current;
    setModals(m => [...m, { id, wide, render: render as ModalItem['render'], resolve: resolve as (v: unknown) => void }]);
  }), []);

  const confirm = useCallback((title: string, text: ReactNode, okLabel: string, danger = true) =>
    modal<boolean>(close => (
      <>
        <h3>{title}</h3><p>{text}</p>
        <div className="acts">
          <button className="btn sm" onClick={() => close(null)}>{t('cancel')}</button>
          <button className={`btn sm ${danger ? 'danger-solid' : 'primary'}`} autoFocus onClick={() => close(true)}>{okLabel}</button>
        </div>
      </>
    )).then(v => !!v), [modal, t]);

  const zoom = useCallback((src: string, cap: string) => setLb({ src, cap }), []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return;
      if (lb) { setLb(null); return; }
      setModals(m => { const last = m[m.length - 1]; last?.resolve(null); return m.slice(0, -1); });
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [lb]);

  const value = useMemo(() => ({ toast, modal, confirm, zoom }), [toast, modal, confirm, zoom]);
  return (
    <Ui.Provider value={value}>
      {children}
      {modals.map(m => (
        <div className="modal" key={m.id} onClick={e => { if (e.target === e.currentTarget) closeModal(m.id, null); }}>
          <div className={`modal-card ${m.wide ? 'wide' : ''}`} role="dialog" aria-modal="true">{m.render(v => closeModal(m.id, v))}</div>
        </div>
      ))}
      {lb && <div className="lightbox" onClick={() => setLb(null)}><img src={lb.src} alt="" /><div className="lb-cap">{lb.cap}</div></div>}
      <div className="toasts" aria-live="polite">
        {toasts.map(x => <div key={x.id} className={`toast ${x.kind}`}><Icon id={x.kind === 'err' ? 'alert' : 'check'} /><span>{x.msg}</span></div>)}
      </div>
    </Ui.Provider>
  );
}
export function useUi(): UiCtx {
  const v = useContext(Ui);
  if (!v) throw new Error('useUi outside provider');
  return v;
}

/* ---------- theme ---------- */
export function useTheme() {
  const [dark, setDark] = useState(() => document.documentElement.dataset.theme === 'dark');
  const toggle = useCallback(() => {
    const next = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
    document.documentElement.dataset.theme = next;
    try { localStorage.setItem('cg_theme', next); } catch { /* ignore */ }
    setDark(next === 'dark');
  }, []);
  return { dark, toggle };
}

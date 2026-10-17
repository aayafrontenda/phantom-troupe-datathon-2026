/* Small shared UI: toasts, modals, lightbox, formatting helpers, theme. */
import { AlertTriangle, Check } from 'lucide-react';
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { Button } from './components/ui/button';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogTitle } from './components/ui/dialog';
import { useI18n } from './i18n';
import { cn } from './lib/utils';

/* ---------- formatting ---------- */
export const tc = (t: number | null | undefined) => {
  const v = Math.max(0, Number(t) || 0);
  const m = Math.floor(v / 60);
  return `${String(m).padStart(2, '0')}:${(v - m * 60).toFixed(1).padStart(4, '0')}`;
};
export const esc = (s: unknown) => String(s ?? '');
/** The evidence frame closest to the moment, as a data URL for the scrubber preview. */
export function keyFrame(frames: { timestamp_sec: number; image_base64: string }[] | undefined, t: number | null | undefined) {
  if (!frames?.length) return undefined;
  const f = frames.reduce((a, b) => (Math.abs(b.timestamp_sec - (t ?? 0)) < Math.abs(a.timestamp_sec - (t ?? 0)) ? b : a));
  return `data:image/jpeg;base64,${f.image_base64}`;
}
/** Banknote-style serial for finding numbers: 4 → "0004". */
export const serial = (id: number | string | null | undefined) => String(id ?? '').padStart(4, '0');
export const shortDesc = (d?: string | null) => String(d || '').split(/\s*Основание:/)[0].replace(/\s*Прямой публичной нормы не установлено\.?$/, '').replace(/\s*Норма косвенная[\s\S]*$/, '').trim();
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
  }, []);
  const dropToast = useCallback((id: number) => setToasts(x => x.filter(y => y.id !== id)), []);

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
        <DialogTitle>{title}</DialogTitle>
        <DialogDescription>{text}</DialogDescription>
        <DialogFooter>
          <Button variant="secondary" size="sm" onClick={() => close(null)}>{t('cancel')}</Button>
          <Button variant={danger ? 'danger' : 'default'} size="sm" autoFocus onClick={() => close(true)}>{okLabel}</Button>
        </DialogFooter>
      </>
    )).then(v => !!v), [modal, t]);

  const zoom = useCallback((src: string, cap: string) => setLb({ src, cap }), []);

  useEffect(() => {
    if (!lb) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setLb(null); };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [lb]);

  const value = useMemo(() => ({ toast, modal, confirm, zoom }), [toast, modal, confirm, zoom]);
  return (
    <Ui.Provider value={value}>
      {children}
      {modals.map(m => (
        <Dialog key={m.id} open onOpenChange={o => { if (!o) closeModal(m.id, null); }}>
          <DialogContent wide={m.wide} aria-describedby={undefined}>{m.render(v => closeModal(m.id, v))}</DialogContent>
        </Dialog>
      ))}
      {lb && (
        <div className="fixed inset-0 z-[60] flex cursor-zoom-out flex-col items-center justify-center gap-2.5 bg-black/90 [animation:fade-in_.2s_var(--ease-out)]" onClick={() => setLb(null)}>
          <img src={lb.src} alt="" className="max-h-[88vh] max-w-[94vw] rounded-lg" />
          <div className="text-xs text-white/75 tabular-nums">{lb.cap}</div>
        </div>
      )}
      <div aria-live="polite" className="fixed bottom-5 left-1/2 z-[70] flex w-[min(460px,calc(100vw-32px))] -translate-x-1/2 flex-col gap-2">
        {toasts.map(x => <ToastItem key={x.id} toast={x} onDone={dropToast} />)}
      </div>
    </Ui.Provider>
  );
}
/* A toast that reads like Sonner: the timer pauses while hovered or while the tab is hidden, a click dismisses it,
   and it leaves faster than it arrived. */
function ToastItem({ toast, onDone }: { toast: Toast; onDone: (id: number) => void }) {
  const [leaving, setLeaving] = useState(false);
  const left = useRef(toast.kind === 'err' ? 6500 : 4200);
  const started = useRef(0);
  const timer = useRef<number | null>(null);
  const pause = useCallback(() => {
    if (timer.current == null) return;
    clearTimeout(timer.current); timer.current = null;
    left.current -= Date.now() - started.current;
  }, []);
  const resume = useCallback(() => {
    if (timer.current != null || document.hidden) return;
    started.current = Date.now();
    timer.current = window.setTimeout(() => setLeaving(true), Math.max(600, left.current));
  }, []);
  useEffect(() => {
    resume();
    const vis = () => (document.hidden ? pause() : resume());
    document.addEventListener('visibilitychange', vis);
    return () => { pause(); document.removeEventListener('visibilitychange', vis); };
  }, [pause, resume]);
  useEffect(() => {
    if (!leaving) return;
    const id = window.setTimeout(() => onDone(toast.id), 220);
    return () => clearTimeout(id);
  }, [leaving, onDone, toast.id]);
  const err = toast.kind === 'err';
  return (
    <div role={err ? 'alert' : 'status'} onMouseEnter={pause} onMouseLeave={resume} onClick={() => setLeaving(true)}
      className={cn('flex items-center gap-2.5 rounded-[10px] px-4 py-3 text-sm shadow-lg transition-[transform,opacity] duration-300 [animation:pop-in_.3s_var(--ease-out)]',
        err ? 'bg-destructive text-white' : 'bg-foreground text-background',
        leaving && 'translate-y-1.5 scale-[.98] opacity-0 duration-200')}>
      {err ? <AlertTriangle className="size-[18px] shrink-0" /> : <Check className="size-[18px] shrink-0 opacity-75" />}
      <span>{toast.msg}</span>
    </div>
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
    const apply = () => {
      document.documentElement.dataset.theme = next;
      try { localStorage.setItem('cg_theme', next); } catch { /* ignore */ }
      setDark(next === 'dark');
    };
    // a rare action: a short crossfade instead of a hard flash, skipped for reduced motion
    const doc = document as Document & { startViewTransition?: (cb: () => void) => unknown };
    if (doc.startViewTransition && !matchMedia('(prefers-reduced-motion: reduce)').matches) doc.startViewTransition(apply);
    else apply();
  }, []);
  return { dark, toggle };
}

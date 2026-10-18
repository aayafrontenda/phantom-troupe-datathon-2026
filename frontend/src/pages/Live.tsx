import { Film, Plus, Video, X } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { api, wsUrl } from '../api';
import { useAuth } from '../auth';
import { CameraGallery } from '../components/CameraGallery';
import { ErrorBanner } from '../components/ErrorBanner';
import { refreshFeed, useFeed } from '../components/events';
import { Button } from '../components/ui/button';
import { DialogBody, DialogDescription, DialogFooter, DialogTitle } from '../components/ui/dialog';
import { Input, Label } from '../components/ui/input';
import { Segmented } from '../components/ui/segmented';
import { StateLine } from '../components/ui/state-line';
import { useI18n } from '../i18n';
import { useCameras } from '../lib/cameras';
import { useTypeNames } from '../lib/rules';
import { cn } from '../lib/utils';
import type { Camera, FindingBrief } from '../types';
import { serial, tc, useAgo, useUi } from '../ui';

export { useCameras } from '../lib/cameras';

interface Det { group?: string; label?: string; score?: number; box: number[] }
const WARN_GROUPS = ['phone', 'bag', 'drink', 'food'];
const STATE_CODES = ['MOTION', 'EMPTY'];

interface Ink { warn: string; person: string; object: string; text: string; font: string }
let inkCache: { theme: string; ink: Ink } | null = null;
function inks(): Ink {
  const theme = document.documentElement.dataset.theme || 'light';
  if (inkCache?.theme === theme) return inkCache.ink;
  const cs = getComputedStyle(document.documentElement);
  const v = (name: string, fallback: string) => cs.getPropertyValue(name).trim() || fallback;
  const ink = { warn: v('--salmon', '#E7798F'), person: v('--cv-person', '#93ABFF'), object: v('--cv-object', '#62D2C4'), text: v('--video', '#121216'), font: `600 12px ${v('--ui', 'system-ui, sans-serif')}` };
  inkCache = { theme, ink };
  return ink;
}

function drawBoxes(ctx: CanvasRenderingContext2D, dets: Det[], sx: number, sy: number) {
  const ink = inks();
  dets.forEach(d => {
    const [x1, y1, x2, y2] = d.box, warn = WARN_GROUPS.includes(d.group || '');
    ctx.strokeStyle = warn ? ink.warn : d.group === 'person' ? ink.person : ink.object; ctx.lineWidth = 2;
    ctx.strokeRect(x1 * sx, y1 * sy, (x2 - x1) * sx, (y2 - y1) * sy);
    ctx.font = ink.font;
    const label = `${d.label || d.group} ${(Number(d.score) || 0).toFixed(2)}`;
    ctx.fillStyle = ctx.strokeStyle; ctx.fillRect(x1 * sx - 1, y1 * sy - 18, ctx.measureText(label).width + 10, 17);
    ctx.fillStyle = ink.text; ctx.fillText(label, x1 * sx + 4, y1 * sy - 5);
  });
}

function CameraTile({ cam, onRemove }: { cam: Camera; onRemove?: () => void }) {
  const { t, has } = useI18n();
  const typeName = useTypeNames();
  const canvas = useRef<HTMLCanvasElement>(null);
  const [ms, setMs] = useState<number | null>(null);
  const [active, setActive] = useState<string[]>([]);
  useEffect(() => {
    let ws: WebSocket | null = null, closed = false, timer: number | null = null;
    const img = new Image();
    const open = () => {
      ws = new WebSocket(wsUrl(`/ui/api/cameras/${cam.id}/ws`));
      ws.onmessage = e => {
        const m = JSON.parse(e.data);
        if (m.type !== 'frame') return;
        img.onload = () => {
          const cv = canvas.current; if (!cv) return;
          if (cv.width !== img.width) { cv.width = img.width; cv.height = img.height; }
          const ctx = cv.getContext('2d')!; ctx.drawImage(img, 0, 0); drawBoxes(ctx, m.detections || [], 1, 1);
        };
        img.src = `data:image/jpeg;base64,${m.frame}`;
        setMs(m.ms); setActive(m.active || []);
      };
      ws.onclose = () => { if (!closed) timer = window.setTimeout(open, 3000); };
    };
    open();
    return () => { closed = true; if (timer) clearTimeout(timer); ws?.close(); };
  }, [cam.id]);
  const alarmed = active.some(c => !STATE_CODES.includes(c));
  const st = cam.state?.status || 'stopped';
  return (
    <div className={cn('relative h-full w-full overflow-hidden rounded-xl bg-video outline-2 outline-offset-2 transition-[outline-color] duration-300', alarmed ? 'outline-primary' : 'outline-transparent')}>
      <canvas ref={canvas} className="block h-full w-full object-contain" />

      <div className="absolute inset-x-0 top-0 flex items-center gap-2 bg-gradient-to-b from-black/80 to-transparent px-3.5 pt-3 pb-5 text-[13.5px] font-semibold text-white">
        <span aria-hidden="true" className={cn('size-[7px] rounded-full', st === 'online' ? 'animate-blink bg-salmon' : 'bg-white/40')} />
        <span className="truncate">{cam.name}</span><span className="flex-1" />
        <small className="text-[11.5px] font-medium text-white/70 tabular-nums">{ms != null ? `${ms} ms` : has(`cam.${st}`) ? t(`cam.${st}`) : st}</small>
        {onRemove && (
          <button type="button" onClick={onRemove} title={t('live.removeCam')} aria-label={t('live.removeCam')}
            className="grid size-[26px] place-items-center rounded-md text-white/70 transition-colors hover:bg-white/10 hover:text-white"><X className="size-4" /></button>
        )}
      </div>
      {active.length > 0 && (
        <div className="absolute inset-x-0 bottom-0 flex flex-wrap gap-1.5 bg-gradient-to-t from-black/80 to-transparent px-3.5 pt-5 pb-3">
          {active.map(c => {
            const neutral = STATE_CODES.includes(c);
            const name = neutral ? t(c === 'MOTION' ? 'live.motion' : 'live.empty') : typeName(c);
            return (
              <span key={c} className={cn('inline-flex items-center gap-1.5 rounded-md px-1.5 py-0.5 text-xs font-semibold text-white', neutral ? 'bg-white/15' : 'bg-primary')}>
                <span>{name}</span>
                {name !== c && <span className="rounded-sm bg-white/20 px-1 text-[10px] leading-4 tracking-wider tabular-nums">{c}</span>}
              </span>
            );
          })}
        </div>
      )}
    </div>
  );
}

export async function addCameraDialog(modal: ReturnType<typeof useUi>['modal'], t: (k: string, v?: Record<string, string | number>) => string) {
  return modal<{ name: string; url: string }>(close => {
    let name = '', url = '';
    return (
      <form onSubmit={e => { e.preventDefault(); if (url.trim()) close({ name: name.trim() || t('cam.default'), url: url.trim() }); }}>
        <DialogTitle>{t('live.addCam')}</DialogTitle><DialogDescription>{t('cam.addText')}</DialogDescription>
        <DialogBody>
          <div><Label htmlFor="cam-name">{t('cam.name')}</Label><Input id="cam-name" placeholder={t('cam.namePh')} onChange={e => { name = e.target.value; }} autoFocus /></div>
          <div><Label htmlFor="cam-url">{t('cam.address')}</Label><Input id="cam-url" placeholder="rtsp://10.20.4.17:554/stream1" spellCheck={false} onChange={e => { url = e.target.value; }} /><small className="mt-1 block text-xs text-muted-foreground">{t('adm.camUrlHint')}</small></div>
        </DialogBody>
        <DialogFooter><Button type="button" variant="secondary" size="sm" onClick={() => close(null)}>{t('cancel')}</Button><Button type="submit" size="sm">{t('cam.connect')}</Button></DialogFooter>
      </form>
    );
  });
}

export default function LivePage() {
  const { t, typeName } = useI18n();
  const { can } = useAuth();
  const { modal, confirm, toast } = useUi();
  const ago = useAgo();
  const { cams, refresh, error: camsError } = useCameras();
  const [tab, setTab] = useState<'open' | 'all'>('open');
  const feed = useFeed();

  const seen = useRef<Set<number> | null>(null);
  if (seen.current === null && feed.loaded) seen.current = new Set(feed.items.map(f => f.id));

  const addCam = async () => {
    const r = await addCameraDialog(modal, t);
    if (!r) return;
    try { await api('/ui/api/cameras', { method: 'POST', json: { ...r, fps: 4 } }); toast(t('cam.added', { n: r.name })); refresh(); }
    catch (e) { toast((e as Error).message, 'err'); }
  };
  const removeCam = async (cam: Camera) => {
    if (!await confirm(t('cam.removeTitle'), <><b>{cam.name}</b> {t('cam.removeText', { name: '' })}</>, t('cam.remove'))) return;
    try { await api(`/ui/api/cameras/${cam.id}`, { method: 'DELETE' }); toast(t('cam.removed')); refresh(); }
    catch (e) { toast((e as Error).message, 'err'); }
  };

  const items = (tab === 'open' ? feed.items.filter(f => !f.decision) : feed.items).slice(0, 80);
  const where = (f: FindingBrief) => f.source === 'camera' ? (f.camera_name || f.camera_id) : f.filename || f.job_id;

  const chat = [...items].reverse();
  const listRef = useRef<HTMLDivElement>(null);
  useEffect(() => { const el = listRef.current; if (el) el.scrollTop = el.scrollHeight; }, [chat.length, tab]);

  return (
    <div className="mx-auto flex max-w-[1680px] flex-col gap-4 lg:h-full">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="min-w-0">
          <h1 className="text-[22px] font-semibold tracking-tight text-heading">{t('live.title')}</h1>
          <p className="mt-1 max-w-[80ch] text-sm text-muted-foreground">{t('live.lead')}</p>
        </div>
        {can('admin') && <Button onClick={addCam}><Plus />{t('live.addCam')}</Button>}
      </div>
      {camsError && <ErrorBanner message={camsError} onRetry={refresh} />}
      <div className="flex min-h-0 flex-1 flex-col gap-4 lg:flex-row">

        <section aria-label={t('live.title')} className="relative flex min-h-[420px] min-w-0 flex-1 items-center justify-center overflow-hidden rounded-xl bg-video p-3 shadow-sm sm:p-4">
          {cams.length ? (
            <CameraGallery>
              {cams.map(c => <CameraTile key={c.id} cam={c} onRemove={can('admin') ? () => removeCam(c) : undefined} />)}
            </CameraGallery>
          ) : (
            <div className="flex max-w-sm flex-col items-center px-6 text-center text-pretty">
              <span className="grid size-14 place-items-center rounded-full bg-white/[.08] text-white/80"><Video className="size-6" strokeWidth={1.7} /></span>
              <h2 className="mt-4 text-lg font-semibold text-white">{t('live.noCams')}</h2>
              <p className="mt-1.5 text-sm text-white/60">{t(can('admin') ? 'live.noCamsAdmin' : 'live.noCamsHint')}</p>
              {can('admin') && <Button className="mt-5" onClick={addCam}><Plus />{t('live.addCam')}</Button>}
            </div>
          )}
        </section>

        <aside className="flex h-[70vh] w-full shrink-0 flex-col overflow-hidden rounded-xl border border-border/60 bg-card shadow-sm lg:h-auto lg:w-[380px]">
          <div className="flex h-14 shrink-0 items-center gap-2 border-b border-border/60 px-4">
            <h2 className="text-[15px] font-semibold text-heading">{t('live.events')}</h2>
            {feed.counts.pending ? <span className="min-w-5 rounded-md bg-primary px-1.5 text-center text-[11px] leading-5 font-semibold text-primary-foreground tabular-nums">{feed.counts.pending}</span> : null}
            <Segmented className="ml-auto" value={tab} onChange={setTab} aria-label={t('live.events')}
              options={[{ value: 'open', label: t('live.open') }, { value: 'all', label: t('live.allEv') }]} />
          </div>
          {feed.error && <ErrorBanner className="m-3 mb-0 rounded-lg" onRetry={refreshFeed} />}
          <div ref={listRef} className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto overscroll-contain px-4 py-4">
            {!chat.length ? (
              <div className="m-auto max-w-[30ch] text-center text-sm text-muted-foreground text-pretty">
                <p className="font-semibold text-foreground">{t(tab === 'open' ? 'ev.noneOpen' : 'ev.none')}</p>
                <p className="mt-1">{t(tab === 'open' ? 'ev.hintOpen' : 'ev.hint')}</p>
              </div>
            ) : chat.map(f => {
              const state = f.decision === 'confirm' ? 'confirm' : f.decision ? 'dismiss' : 'pending';
              const fresh = seen.current && !seen.current.has(f.id);
              return (
                <Link key={f.id} to={`/findings/${f.id}?from=live`}
                  className={cn('group flex gap-2.5 text-left no-underline', fresh && '[animation:pop-in_.32s_var(--ease-out)_both]')}>
                  <span className="grid size-8 shrink-0 place-items-center rounded-full bg-muted text-muted-foreground">
                    {f.source === 'camera' ? <Video className="size-4" /> : <Film className="size-4" />}
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-baseline gap-2 text-xs text-faint tabular-nums">
                      <span className="truncate font-semibold text-foreground">{where(f)}</span>
                      <span className="shrink-0">{ago(f.created_at)}</span>
                      <span className="ml-auto shrink-0">№ {serial(f.id)}</span>
                    </div>
                    <div className={cn('mt-1 rounded-2xl rounded-tl-md border px-3 py-2.5 transition-colors group-hover:border-border-strong', state === 'pending' ? 'border-primary/25 bg-primary-soft/50' : 'border-border/60 bg-subtle')}>
                      <StateLine state={state}>{t(f.decision === 'confirm' ? 'f.confirmed' : f.decision ? 'f.notViolation' : 'ev.pending')}</StateLine>
                      <p className={cn('mt-1 text-sm leading-snug', f.decision ? 'text-muted-foreground' : 'font-medium text-foreground')}>{typeName(f.type_code, f.type_name)}</p>
                      {(f.t_sec != null || f.verified) && (
                        <p className="mt-1 flex gap-2 text-xs text-muted-foreground tabular-nums">
                          {f.t_sec != null && <span>{t('ev.at', { t: tc(f.t_sec) })}</span>}{f.verified && <span>{t('fd.verified')}</span>}
                        </p>
                      )}
                    </div>
                  </div>
                </Link>
              );
            })}
          </div>
        </aside>
      </div>
    </div>
  );
}

import { useCallback, useEffect, useRef, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { api, wsUrl } from '../api';
import { useAuth } from '../auth';
import { Button } from '../components/ui/button';
import { Film, Plus, Video } from 'lucide-react';
import { CameraGallery } from '../components/CameraGallery';
import { useFeed } from '../components/events';
import { useI18n } from '../i18n';
import type { Camera, FindingBrief } from '../types';
import { Icon, serial, tc, useAgo, useUi } from '../ui';

interface Det { group?: string; label?: string; score?: number; box: number[] }

function drawBoxes(ctx: CanvasRenderingContext2D, dets: Det[], sx: number, sy: number) {
  dets.forEach(d => {
    const [x1, y1, x2, y2] = d.box, warn = ['phone', 'bag', 'drink', 'food'].includes(d.group || '');
    ctx.strokeStyle = warn ? '#FC9385' : d.group === 'person' ? '#93ABFF' : '#62D2C4'; ctx.lineWidth = 2;
    ctx.strokeRect(x1 * sx, y1 * sy, (x2 - x1) * sx, (y2 - y1) * sy);
    ctx.font = '600 12px "Open Sans", sans-serif';
    const label = `${d.label || d.group} ${(Number(d.score) || 0).toFixed(2)}`;
    ctx.fillStyle = ctx.strokeStyle; ctx.fillRect(x1 * sx - 1, y1 * sy - 18, ctx.measureText(label).width + 10, 17);
    ctx.fillStyle = '#120F14'; ctx.fillText(label, x1 * sx + 4, y1 * sy - 5);
  });
}

function CameraTile({ cam, onRemove }: { cam: Camera; onRemove?: () => void }) {
  const { t, typeName, has } = useI18n();
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
  const alarmed = active.some(c => !['MOTION', 'EMPTY'].includes(c));
  const st = cam.state?.status || 'stopped';
  return (
    <div className={`tile h-full w-full ${alarmed ? 'alarmed' : ''}`}>
      <canvas ref={canvas} />
      <div className="tile-bar"><span className={`rec ${st === 'online' ? '' : 'off'}`} /><span>{cam.name}</span><span className="sp" />
        <small>{ms != null ? `${ms} ms` : has(`cam.${st}`) ? t(`cam.${st}`) : st}</small>
        {onRemove && <button className="icon-btn" onClick={onRemove} title={t('live.removeCam')}><Icon id="x" /></button>}</div>
      <div className="tile-foot">{active.map(c => <span key={c} className={`pill xs ${['MOTION', 'EMPTY'].includes(c) ? 'neutral' : 'bad'}`} title={typeName(c, c)}>{c}</span>)}</div>
    </div>
  );
}

export function useCameras() {
  const [cams, setCams] = useState<Camera[]>([]);
  const refresh = useCallback(async () => { try { setCams((await api<{ cameras: Camera[] }>('/ui/api/cameras')).cameras); } catch { /* keep */ } }, []);
  useEffect(() => { refresh(); const id = setInterval(refresh, 10000); return () => clearInterval(id); }, [refresh]);
  return { cams, refresh };
}

export async function addCameraDialog(modal: ReturnType<typeof useUi>['modal'], t: (k: string, v?: Record<string, string | number>) => string) {
  return modal<{ name: string; url: string }>(close => {
    let name = '', url = '';
    return (
      <form onSubmit={e => { e.preventDefault(); if (url.trim()) close({ name: name.trim() || t('cam.default'), url: url.trim() }); }}>
        <h3>{t('live.addCam')}</h3><p>{t('cam.addText')}</p>
        <div className="form">
          <div><label className="lbl">{t('cam.name')}</label><input className="field" placeholder={t('cam.namePh')} onChange={e => { name = e.target.value; }} autoFocus /></div>
          <div><label className="lbl">{t('cam.address')}</label><input className="field" placeholder="rtsp://10.20.4.17:554/stream1" spellCheck={false} onChange={e => { url = e.target.value; }} /><small className="muted">{t('adm.camUrlHint')}</small></div>
        </div>
        <div className="acts"><button type="button" className="btn sm" onClick={() => close(null)}>{t('cancel')}</button><button type="submit" className="btn sm primary">{t('cam.connect')}</button></div>
      </form>
    );
  });
}

export default function LivePage() {
  const { t, typeName } = useI18n();
  const { can } = useAuth();
  const { modal, confirm, toast } = useUi();
  const ago = useAgo();
  const nav = useNavigate();
  const { cams, refresh } = useCameras();
  const [tab, setTab] = useState<'open' | 'all'>('open');
  const feed = useFeed();
  // ids present when the page opened; anything newer is "fresh" and gets the arrival animation
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

  // chat order: oldest at the top, newest at the bottom next to the reader's eye
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
      <div className="flex min-h-0 flex-1 flex-col gap-4 lg:flex-row">
        {/* the stage: like a shared screen in a call, it takes the main part of the window */}
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

        {/* events as a chat panel */}
        <aside className="flex h-[70vh] w-full shrink-0 flex-col overflow-hidden rounded-xl border border-border/60 bg-card shadow-sm lg:h-auto lg:w-[380px]">
          <div className="flex h-14 shrink-0 items-center gap-2 border-b border-border/60 px-4">
            <h2 className="text-[15px] font-semibold text-heading">{t('live.events')}</h2>
            {feed.counts.pending ? <span className="min-w-5 rounded-md bg-primary px-1.5 text-center text-[11px] leading-5 font-semibold text-primary-foreground tabular-nums">{feed.counts.pending}</span> : null}
            <div role="tablist" className="ml-auto flex gap-0.5 rounded-lg bg-muted p-0.5">
              {(['open', 'all'] as const).map(k => (
                <button key={k} role="tab" aria-selected={tab === k} onClick={() => setTab(k)}
                  className={`h-7 rounded-md px-2.5 text-[13px] font-medium transition-colors ${tab === k ? 'bg-card text-foreground shadow-sm' : 'text-muted-foreground hover:text-foreground'}`}>
                  {t(k === 'open' ? 'live.open' : 'live.allEv')}
                </button>
              ))}
            </div>
          </div>
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
                <Link key={f.id} to={`/findings/${f.id}?from=live`} onClick={e => { e.preventDefault(); nav(`/findings/${f.id}?from=live`); }}
                  className={`group flex gap-2.5 text-left no-underline ${fresh ? '[animation:pop-in_.32s_var(--ease-out)_both]' : ''}`}>
                  <span className="grid size-8 shrink-0 place-items-center rounded-full bg-muted text-muted-foreground">
                    {f.source === 'camera' ? <Video className="size-4" /> : <Film className="size-4" />}
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-baseline gap-2 text-xs text-faint tabular-nums">
                      <span className="truncate font-semibold text-foreground">{where(f)}</span>
                      <span className="shrink-0">{ago(f.created_at)}</span>
                      <span className="ml-auto shrink-0">№ {serial(f.id)}</span>
                    </div>
                    <div className={`mt-1 rounded-2xl rounded-tl-md border px-3 py-2.5 transition-colors group-hover:border-border-strong ${state === 'pending' ? 'border-primary/25 bg-primary-soft/50' : 'border-border/60 bg-subtle'}`}>
                      <span className={`state ${state}`}>{t(f.decision === 'confirm' ? 'f.confirmed' : f.decision ? 'f.notViolation' : 'ev.pending')}</span>
                      <p className={`mt-1 text-sm leading-snug ${f.decision ? 'text-muted-foreground' : 'font-medium text-foreground'}`}>{typeName(f.type_code, f.type_name)}</p>
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

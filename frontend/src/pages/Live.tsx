import { useCallback, useEffect, useRef, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { api, wsUrl } from '../api';
import { useAuth } from '../auth';
import { useFeed } from '../components/events';
import { useI18n } from '../i18n';
import type { Camera, FindingBrief } from '../types';
import { Icon, tc, useAgo, useUi } from '../ui';

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
    <div className={`tile ${alarmed ? 'alarmed' : ''}`}>
      <canvas ref={canvas} />
      <div className="tile-bar"><span className={`rec ${st === 'online' ? '' : 'off'}`} /><span>{cam.name}</span><span className="sp" />
        <small>{ms != null ? `${ms} ms` : has(`cam.${st}`) ? t(`cam.${st}`) : st}</small>
        {onRemove && <button className="icon-btn" onClick={onRemove} title={t('live.removeCam')}><Icon id="x" /></button>}</div>
      <div className="tile-foot">{active.map(c => <span key={c} className={`pill xs ${['MOTION', 'EMPTY'].includes(c) ? 'neutral' : 'bad'}`} title={typeName(c, c)}>{c}</span>)}</div>
    </div>
  );
}

function LaptopTile({ onStop }: { onStop: () => void }) {
  const { t, typeName } = useI18n();
  const { toast } = useUi();
  const canvas = useRef<HTMLCanvasElement>(null);
  const [status, setStatus] = useState('-');
  const [active, setActive] = useState<string[]>([]);
  useEffect(() => {
    let stream: MediaStream | null = null, ws: WebSocket | null = null, timer: number | null = null, raf = 0, busy = false, alive = true;
    let dets: Det[] = [], size: number[] | null = null;
    const video = document.createElement('video'); video.muted = true; video.playsInline = true;
    const off = document.createElement('canvas');
    (async () => {
      try { stream = await navigator.mediaDevices.getUserMedia({ video: { width: { ideal: 640 } }, audio: false }); }
      catch (e) { toast(t('cam.denied', { e: (e as Error).message }), 'err'); onStop(); return; }
      if (!alive) { stream.getTracks().forEach(x => x.stop()); return; }
      video.srcObject = stream; await video.play();
      ws = new WebSocket(wsUrl('/ui/api/live'));
      ws.onopen = () => { timer = window.setInterval(() => {
        if (busy || !ws || ws.readyState !== 1 || !video.videoWidth) return;
        const k = Math.min(1, 640 / Math.max(video.videoWidth, video.videoHeight));
        off.width = Math.round(video.videoWidth * k); off.height = Math.round(video.videoHeight * k);
        off.getContext('2d')!.drawImage(video, 0, 0, off.width, off.height);
        off.toBlob(b => { if (b && ws && ws.readyState === 1) { busy = true; ws.send(b); } }, 'image/jpeg', 0.75);
      }, 333); };
      ws.onmessage = e => {
        const m = JSON.parse(e.data); busy = false;
        if (m.error) { toast(m.error, 'err'); return; }
        if (m.skipped) return;
        dets = m.detections || []; size = m.size; setStatus(`${m.ms} ms${m.busy ? ` · ${t('busy')}` : ''}`); setActive(m.active || []);
      };
      const draw = () => {
        const cv = canvas.current;
        if (cv && video.videoWidth) {
          const w = video.videoWidth, h = video.videoHeight; if (cv.width !== w) { cv.width = w; cv.height = h; }
          const ctx = cv.getContext('2d')!; ctx.drawImage(video, 0, 0, w, h); if (size) drawBoxes(ctx, dets, w / size[0], h / size[1]);
        }
        raf = requestAnimationFrame(draw);
      };
      raf = requestAnimationFrame(draw);
    })();
    return () => { alive = false; if (timer) clearInterval(timer); cancelAnimationFrame(raf); ws?.close(); stream?.getTracks().forEach(x => x.stop()); };
  }, [onStop, t, toast]);
  const alarmed = active.some(c => !['MOTION', 'EMPTY'].includes(c));
  return (
    <div className={`tile ${alarmed ? 'alarmed' : ''}`}>
      <canvas ref={canvas} />
      <div className="tile-bar"><span className="rec" /><span>{t('live.thisComputer')}</span><span className="sp" /><small>{status}</small><button className="icon-btn" onClick={onStop} title={t('live.stop')}><Icon id="x" /></button></div>
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
  const [laptop, setLaptop] = useState(false);
  const [tab, setTab] = useState<'open' | 'all'>('open');
  const feed = useFeed();
  const stopLaptop = useCallback(() => setLaptop(false), []);

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

  return (
    <div className="page wide">
      <div className="page-head">
        <div><h1>{t('live.title')}</h1><p>{t('live.lead')}</p></div>
        <div className="acts">
          <button className="btn" onClick={() => setLaptop(l => !l)}><Icon id={laptop ? 'x' : 'cam'} />{t(laptop ? 'live.stopCam' : 'live.useCam')}</button>
          {can('admin') && <button className="btn primary" onClick={addCam}><Icon id="plus" />{t('live.addCam')}</button>}
        </div>
      </div>
      <div className="live-grid">
        <div className="wall">
          {laptop && <LaptopTile onStop={stopLaptop} />}
          {cams.map(c => <CameraTile key={c.id} cam={c} onRemove={can('admin') ? () => removeCam(c) : undefined} />)}
          {!cams.length && !laptop && (
            <div className="tile-add"><span className="ic"><Icon id="cam" /></span><b>{t('live.noCams')}</b><span>{t(can('admin') ? 'live.noCamsAdmin' : 'live.noCamsHint')}</span>
              {can('admin') && <button className="btn primary" onClick={addCam}><Icon id="plus" />{t('live.addCam')}</button>}</div>
          )}
        </div>
        <aside className="card feed">
          <div className="feed-h"><h2>{t('live.events')}</h2>{feed.counts.pending ? <span className="badge">{feed.counts.pending}</span> : null}<span className="sp" />
            <div className="seg"><button className={tab === 'open' ? 'on' : ''} onClick={() => setTab('open')}>{t('live.open')}</button><button className={tab === 'all' ? 'on' : ''} onClick={() => setTab('all')}>{t('live.allEv')}</button></div></div>
          <div className="feed-list">
            {!items.length ? <div className="empty"><b>{t(tab === 'open' ? 'ev.noneOpen' : 'ev.none')}</b>{t('ev.hint')}</div> : items.map(f => (
              <Link key={f.id} className={`al ${f.decision ? 'closed' : ''}`} to={`/findings/${f.id}?from=live`} onClick={e => { e.preventDefault(); nav(`/findings/${f.id}?from=live`); }}>
                <div className="t1"><span className={`pill xs ${f.decision === 'confirm' ? 'bad' : f.decision ? 'neutral' : 'warn'}`}>{t(f.decision === 'confirm' ? 'f.confirmed' : f.decision ? 'f.notViolation' : 'ev.pending')}</span>
                  <span className="sp" /><span>{ago(f.created_at)}</span></div>
                <b>{typeName(f.type_code, f.type_name)}</b>
                <div className="where"><Icon id={f.source === 'camera' ? 'cam' : 'film'} /> {where(f)}{f.t_sec != null ? ` · ${t('ev.at', { t: tc(f.t_sec) })}` : ''}{f.verified ? ` · ${t('fd.verified')}` : ''}</div>
              </Link>
            ))}
          </div>
        </aside>
      </div>
    </div>
  );
}

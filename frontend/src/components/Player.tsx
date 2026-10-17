/* Video player with violation markers on the scrub bar, plus a frame-sequence player for camera findings. */
import { forwardRef, useCallback, useEffect, useImperativeHandle, useRef, useState } from 'react';
import { useI18n } from '../i18n';
import { Icon, tc } from '../ui';
import { GuillocheBand } from './Guilloche';

export interface Marker { t: number; label: string; title: string; state?: 'confirm' | 'done' | ''; thumb?: string }
export interface PlayerHandle { seek: (t: number, play?: boolean) => void; toggle: () => void }

interface Props {
  src: string | null;
  poster?: string;
  duration: number;
  markers?: Marker[];
  selected?: number;
  onSelect?: (i: number) => void;
  onTime?: (t: number) => void;
  initialT?: number;
  wide?: boolean;
  removedTitle?: string;
  removedHint?: string;
  hint?: React.ReactNode;
}

function Scrub({ duration, t, markers, selected, onSeek, onSelect }: { duration: number; t: number; markers: Marker[]; selected?: number; onSeek: (t: number) => void; onSelect?: (i: number) => void }) {
  const ref = useRef<HTMLDivElement>(null);
  const D = Math.max(0.1, duration);
  const at = (e: React.PointerEvent) => {
    const r = ref.current!.getBoundingClientRect();
    onSeek(Math.min(1, Math.max(0, (e.clientX - r.left) / r.width)) * D);
  };
  return (
    <div className="scrub" ref={ref}
      onPointerDown={e => { if ((e.target as HTMLElement).closest('button')) return; at(e); (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId); }}
      onPointerMove={e => { if (e.buttons & 1 && !(e.target as HTMLElement).closest('button')) at(e); }}>
      <GuillocheBand progress={t / D} peaks={markers.map(m => ({ at: m.t / D, strength: m.state === 'done' ? 0.45 : 1, hot: !m.state }))} />
      {markers.map((m, i) => (
        <button key={i} className={`mk ${i === selected ? 'on' : ''} ${m.state || ''}`} style={{ left: `${m.t / D * 100}%` }} aria-label={m.title}
          title={m.thumb ? undefined : m.title} onClick={e => { e.stopPropagation(); onSelect?.(i); }}>{m.label}
          {m.thumb && <span className="mk-tip" aria-hidden="true"><img src={m.thumb} alt="" /><span>{m.title}</span></span>}</button>
      ))}
      <div className="head" style={{ left: `${t / D * 100}%` }} />
    </div>
  );
}

export const Player = forwardRef<PlayerHandle, Props>(function Player(p, ref) {
  const { t } = useI18n();
  const vid = useRef<HTMLVideoElement>(null);
  const [time, setTime] = useState(p.initialT || 0);
  const [playing, setPlaying] = useState(false);
  const [broken, setBroken] = useState(false);
  const pendingSeek = useRef<number | null>(p.initialT ?? null);

  const seek = useCallback((tt: number, play = false) => {
    const v = vid.current;
    const nt = Math.min(p.duration, Math.max(0, tt));
    setTime(nt); p.onTime?.(nt);
    if (v && v.readyState > 0) { v.currentTime = nt; if (play) v.play().catch(() => { }); }
    else pendingSeek.current = nt;
  }, [p]);
  const toggle = useCallback(() => {
    const v = vid.current; if (!v) return;
    if (v.paused) { if (v.ended) v.currentTime = 0; v.play().catch(() => { }); } else v.pause();
  }, []);
  useImperativeHandle(ref, () => ({ seek, toggle }), [seek, toggle]);

  useEffect(() => { setBroken(false); }, [p.src]);
  // timeupdate fires ~4x a second; follow the video every frame while it plays so the playhead glides
  useEffect(() => {
    if (!playing) return;
    let raf = 0;
    const tick = () => { const v = vid.current; if (v) setTime(v.currentTime); raf = requestAnimationFrame(tick); };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [playing]);

  if (!p.src) {
    return (
      <div className={`player ${p.wide ? 'wide' : ''}`}>
        {p.poster && <img src={p.poster} alt="" style={{ width: '100%', height: '100%', objectFit: 'contain' }} />}
        <div className="no-video"><Icon id="film" /><b>{p.removedTitle || t('p.removed')}</b><span>{p.removedHint || t('p.removedHint')}</span></div>
      </div>
    );
  }
  return (
    <>
      <div className={`player ${p.wide ? 'wide' : ''}`}>
        <video ref={vid} src={p.src} poster={p.poster} playsInline preload="auto" muted onClick={toggle}
          onLoadedMetadata={() => { const v = vid.current!; if (pendingSeek.current != null) { v.currentTime = Math.max(0.01, pendingSeek.current); pendingSeek.current = null; } }}
          onTimeUpdate={() => { const v = vid.current!; setTime(v.currentTime); p.onTime?.(v.currentTime); }}
          onPlay={() => setPlaying(true)} onPause={() => setPlaying(false)} onError={() => setBroken(true)} />
        {broken && <div className="no-video"><Icon id="film" /><b>{t('p.cantPlay')}</b><span>{t('p.cantPlayHint')}</span></div>}
      </div>
      <Scrub duration={p.duration} t={time} markers={p.markers || []} selected={p.selected} onSeek={tt => seek(tt, true)} onSelect={p.onSelect} />
      <div className="pctrl">
        <button className="icon-btn" onClick={toggle} aria-label={t(playing ? 'p.pause' : 'p.play')}><Icon id={playing ? 'pause' : 'play'} /></button>
        <span className="time num"><b>{tc(time)}</b> / {tc(p.duration)}</span>
      </div>
      {p.hint && <div className="keys-hint">{p.hint}</div>}
    </>
  );
});

/* Frames captured around a camera alert, played back at their original pace. */
export const SequencePlayer = forwardRef<PlayerHandle, { frames: { t: number; url: string }[]; markers?: Marker[]; onTime?: (t: number) => void; initialT?: number; wide?: boolean }>(
  function SequencePlayer(p, ref) {
    const { t } = useI18n();
    const [idx, setIdx] = useState(() => nearest(p.frames, p.initialT || 0));
    const [playing, setPlaying] = useState(false);
    const timer = useRef<number | null>(null);
    const duration = p.frames.length ? p.frames[p.frames.length - 1].t : 0;

    const stop = useCallback(() => { if (timer.current) clearTimeout(timer.current); timer.current = null; setPlaying(false); }, []);
    const step = useCallback((i: number) => {
      setIdx(i); p.onTime?.(p.frames[i]?.t || 0);
      if (i + 1 >= p.frames.length) { stop(); return; }
      const dt = Math.min(1.5, Math.max(0.05, p.frames[i + 1].t - p.frames[i].t));
      timer.current = window.setTimeout(() => step(i + 1), dt * 1000);
    }, [p, stop]);
    const play = useCallback((from?: number) => { stop(); setPlaying(true); step(from ?? (idx + 1 >= p.frames.length ? 0 : idx)); }, [idx, p.frames.length, step, stop]);
    const seek = useCallback((tt: number, pl = false) => { const i = nearest(p.frames, tt); stop(); setIdx(i); p.onTime?.(p.frames[i]?.t || 0); if (pl) play(i); }, [p, play, stop]);
    const toggle = useCallback(() => (playing ? stop() : play()), [playing, play, stop]);
    useImperativeHandle(ref, () => ({ seek, toggle }), [seek, toggle]);
    useEffect(() => () => { if (timer.current) clearTimeout(timer.current); }, []);

    const cur = p.frames[idx];
    return (
      <>
        <div className={`player ${p.wide ? 'wide' : ''}`} onClick={toggle}>
          {cur ? <img className="seq" src={cur.url} alt="" /> : <div className="no-video"><Icon id="film" /><b>{t('p.noClip')}</b></div>}
        </div>
        <Scrub duration={duration} t={cur?.t || 0} markers={p.markers || []} onSeek={tt => seek(tt, false)} />
        <div className="pctrl">
          <button className="icon-btn" onClick={toggle} aria-label={t(playing ? 'p.pause' : 'p.play')}><Icon id={playing ? 'pause' : 'play'} /></button>
          <span className="time num"><b>{tc(cur?.t || 0)}</b> / {tc(duration)}</span>
          <span className="sp" /><span className="muted small">{t('p.frames')} <span className="num">({p.frames.length})</span></span>
        </div>
      </>
    );
  });

function nearest(frames: { t: number }[], tt: number): number {
  let best = 0, bd = Infinity;
  frames.forEach((f, i) => { const d = Math.abs(f.t - tt); if (d < bd) { bd = d; best = i; } });
  return best;
}

/* Video player with violation markers on the scrub bar, plus a frame-sequence player for camera findings. */
import { Film, Pause, Play } from 'lucide-react';
import { forwardRef, useCallback, useEffect, useImperativeHandle, useRef, useState, type ReactNode } from 'react';
import { useI18n } from '../i18n';
import { cn } from '../lib/utils';
import { tc } from '../ui';
import { GuillocheBand } from './Guilloche';
import { Button } from './ui/button';

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
  hint?: ReactNode;
}

/* the stage: portrait like the cash-desk camera, or 4:3 for clips */
const stageClass = (wide?: boolean) => cn('relative mx-auto overflow-hidden rounded-lg bg-video',
  wide ? 'aspect-[4/3] max-h-[60vh]' : 'aspect-[464/848] max-h-[60vh] xl:max-h-[calc(100dvh-240px)]');

function NoVideo({ title, hint }: { title: ReactNode; hint?: ReactNode }) {
  return (
    <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 bg-video/80 p-[18px] text-center text-[13px] text-white/75 text-balance">
      <Film className="size-[18px]" strokeWidth={1.7} /><b className="text-white">{title}</b>{hint && <span>{hint}</span>}
    </div>
  );
}

/* the signature: an engraved security line that swells where the AI looked closer */
function Scrub({ duration, t, markers, selected, onSeek, onSelect }: { duration: number; t: number; markers: Marker[]; selected?: number; onSeek: (t: number) => void; onSelect?: (i: number) => void }) {
  const ref = useRef<HTMLDivElement>(null);
  const D = Math.max(0.1, duration);
  const at = (e: React.PointerEvent) => {
    const r = ref.current!.getBoundingClientRect();
    onSeek(Math.min(1, Math.max(0, (e.clientX - r.left) / r.width)) * D);
  };
  return (
    <div ref={ref} className="relative mt-1.5 h-[70px] cursor-pointer touch-none select-none"
      onPointerDown={e => { if ((e.target as HTMLElement).closest('button')) return; at(e); (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId); }}
      onPointerMove={e => { if (e.buttons & 1 && !(e.target as HTMLElement).closest('button')) at(e); }}>
      <GuillocheBand progress={t / D} peaks={markers.map(m => ({ at: m.t / D, strength: m.state === 'done' ? 0.45 : 1, hot: !m.state }))} />
      {markers.map((m, i) => {
        const on = i === selected;
        return (
          <span key={i} className="absolute top-0 -translate-x-1/2" style={{ left: `${m.t / D * 100}%` }}>
            <button type="button" aria-label={m.title} title={m.thumb ? undefined : m.title} onClick={e => { e.stopPropagation(); onSelect?.(i); }}
              className={cn('group relative block h-5 min-w-5 rounded-[5px] px-[5px] text-[11px] leading-5 font-semibold tabular-nums transition-[transform,box-shadow] duration-150 hover:-translate-y-px active:scale-[.94]',
                m.state === 'done' ? 'bg-muted text-muted-foreground' : m.state === 'confirm' ? 'bg-destructive text-white' : 'bg-primary text-white',
                on && 'ring-[1.5px] ring-foreground ring-offset-2 ring-offset-card')}>
              {m.label}
              {/* the flag pole: dashed while waiting, solid once decided */}
              <span aria-hidden="true" className={cn('absolute top-5 left-1/2 h-[18px] border-l',
                m.state === 'done' ? 'border-solid border-faint' : m.state === 'confirm' ? 'border-solid border-destructive' : 'border-dashed border-primary opacity-70')} />
              {/* hover a flag to preview its key frame: grows from the marker, short delay in, instant out */}
              {m.thumb && (
                <span aria-hidden="true" className="pointer-events-none absolute bottom-7 left-1/2 z-[2] hidden w-[92px] origin-bottom -translate-x-1/2 scale-[.94] rounded-lg border border-border bg-card p-1 opacity-0 shadow-lg transition-[opacity,transform] duration-150 group-hover:scale-100 group-hover:opacity-100 group-hover:delay-150 group-focus-visible:scale-100 group-focus-visible:opacity-100 pointer-fine:block">
                  <img src={m.thumb} alt="" className="block aspect-[464/848] w-full rounded-[5px] bg-video object-cover" />
                  <span className="mt-1 block text-left text-[11px] leading-tight font-medium whitespace-normal text-foreground">{m.title}</span>
                </span>
              )}
            </button>
          </span>
        );
      })}
      <div className="pointer-events-none absolute bottom-0.5 -ml-px h-12 w-0.5 rounded-[1px] bg-foreground" style={{ left: `${t / D * 100}%` }} />
    </div>
  );
}

function Controls({ playing, onToggle, time, duration, children }: { playing: boolean; onToggle: () => void; time: number; duration: number; children?: ReactNode }) {
  const { t } = useI18n();
  return (
    <div className="mt-1 flex items-center gap-1.5">
      <Button variant="ghost" size="icon-sm" onClick={onToggle} aria-label={t(playing ? 'p.pause' : 'p.play')}>
        {playing ? <Pause className="fill-current" /> : <Play className="fill-current" />}
      </Button>
      <span className="ml-0.5 text-[13.5px] font-medium tracking-wide text-muted-foreground tabular-nums"><b className="font-semibold text-foreground">{tc(time)}</b> / {tc(duration)}</span>
      {children}
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
      <div className={stageClass(p.wide)}>
        {p.poster && <img src={p.poster} alt="" className="h-full w-full object-contain" />}
        <NoVideo title={p.removedTitle || t('p.removed')} hint={p.removedHint || t('p.removedHint')} />
      </div>
    );
  }
  return (
    <>
      <div className={stageClass(p.wide)}>
        <video ref={vid} src={p.src} poster={p.poster} playsInline preload="auto" muted onClick={toggle} className="block h-full w-full bg-video object-contain"
          onLoadedMetadata={() => { const v = vid.current!; if (pendingSeek.current != null) { v.currentTime = Math.max(0.01, pendingSeek.current); pendingSeek.current = null; } }}
          onTimeUpdate={() => { const v = vid.current!; setTime(v.currentTime); p.onTime?.(v.currentTime); }}
          onPlay={() => setPlaying(true)} onPause={() => setPlaying(false)} onError={() => setBroken(true)} />
        {broken && <NoVideo title={t('p.cantPlay')} hint={t('p.cantPlayHint')} />}
      </div>
      <Scrub duration={p.duration} t={time} markers={p.markers || []} selected={p.selected} onSeek={tt => seek(tt, true)} onSelect={p.onSelect} />
      <Controls playing={playing} onToggle={toggle} time={time} duration={p.duration} />
      {p.hint && (
        <div className="mt-2 hidden text-center text-xs leading-[1.9] text-faint sm:pointer-fine:block [&>span>span]:whitespace-nowrap [&>span>span+span]:ml-5">{p.hint}</div>
      )}
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
        <div className={stageClass(p.wide)} onClick={toggle}>
          {cur ? <img src={cur.url} alt="" className="block h-full w-full bg-video object-contain" /> : <NoVideo title={t('p.noClip')} />}
        </div>
        <Scrub duration={duration} t={cur?.t || 0} markers={p.markers || []} onSeek={tt => seek(tt, false)} />
        <Controls playing={playing} onToggle={toggle} time={cur?.t || 0} duration={duration}>
          <span className="ml-auto text-[13px] text-muted-foreground">{t('p.frames')} <span className="tabular-nums">({p.frames.length})</span></span>
        </Controls>
      </>
    );
  });

function nearest(frames: { t: number }[], tt: number): number {
  let best = 0, bd = Infinity;
  frames.forEach((f, i) => { const d = Math.abs(f.t - tt); if (d < bd) { bd = d; best = i; } });
  return best;
}

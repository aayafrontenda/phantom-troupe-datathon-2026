import { useId, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { cn } from '../lib/utils';

const STRAND = 'fill-none [stroke-width:1] [vector-effect:non-scaling-stroke] [stroke-linecap:round]';

export interface Peak { x: number; strength?: number }

function bandPaths(w: number, h: number, peaks: Peak[], strands: number) {
  const mid = h / 2, base = h * 0.12, swell = h * 0.5, sigma = Math.max(14, w * 0.035);
  const period = 34;
  const out: string[] = [];
  for (let k = 0; k < strands; k++) {
    const phase = (k / strands) * Math.PI * 2;
    let d = '';
    for (let x = 0; x <= w; x += 1.5) {
      let env = base;
      for (const p of peaks) { const z = (x - p.x) / sigma; env += swell * (p.strength ?? 1) * Math.exp(-z * z); }
      env = Math.min(env, mid - 1.5);
      const mod = 0.72 + 0.28 * Math.cos(x / (period * 3.1) + phase * 0.5);
      const y = mid + env * mod * Math.sin((x / period) * Math.PI * 2 + phase);
      d += `${x === 0 ? 'M' : 'L'}${x.toFixed(1)} ${y.toFixed(2)}`;
    }
    out.push(d);
  }
  return out;
}

export function GuillocheBand({ peaks, progress, height = 48, strands = 4 }: { peaks: { at: number; strength?: number; hot?: boolean }[]; progress: number; height?: number; strands?: number }) {
  const ref = useRef<SVGSVGElement>(null);
  const [w, setW] = useState(0);
  const clip = useId(), hotClip = useId();
  const hotHalf = Math.max(14, w * 0.035) * 1.6;
  useLayoutEffect(() => {
    const el = ref.current; if (!el) return;
    const ro = new ResizeObserver(([e]) => setW(Math.round(e.contentRect.width)));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  const key = peaks.map(p => `${p.at.toFixed(4)}:${p.strength ?? 1}`).join(',');
  const paths = useMemo(() => (w ? bandPaths(w, height, peaks.map(p => ({ x: p.at * w, strength: p.strength })), strands) : []), [w, height, strands, key]);
  return (
    <svg ref={ref} className="absolute inset-x-0 bottom-0.5 block w-full overflow-visible" viewBox={`0 0 ${w || 1} ${height}`} height={height} preserveAspectRatio="none" aria-hidden="true">
      <defs>
        <clipPath id={clip}><rect x="0" y="0" width={Math.max(0, Math.min(1, progress)) * w} height={height} /></clipPath>
        <clipPath id={hotClip}>{peaks.filter(p => p.hot).map((p, i) => <rect key={i} x={p.at * w - hotHalf} y="0" width={hotHalf * 2} height={height} />)}</clipPath>
      </defs>
      <g className={cn(STRAND, 'stroke-foreground/30')}>{paths.map((d, i) => <path key={i} d={d} />)}</g>
      <g className={cn(STRAND, 'stroke-foreground opacity-85')} clipPath={`url(#${clip})`}>{paths.map((d, i) => <path key={i} d={d} />)}</g>
      {peaks.some(p => p.hot) && <g className={cn(STRAND, 'stroke-primary [stroke-width:1.15]')} clipPath={`url(#${hotClip})`}>{paths.map((d, i) => <path key={i} d={d} />)}</g>}
    </svg>
  );
}

export function Rosette({ size = 640, rings = 30, className }: { size?: number; rings?: number; className?: string }) {
  const paths = useMemo(() => {
    const c = size / 2, out: string[] = [];
    for (let r = 0; r < rings; r++) {
      const R = size * (0.09 + r * 0.0128), lobes = 36, a = size * (0.009 + 0.004 * Math.sin(r * 0.6)), ph = r * 0.42;
      let d = '';
      for (let i = 0; i <= 1080; i++) {
        const th = (i / 1080) * Math.PI * 2;
        const rr = R + a * Math.sin(lobes * th + ph) + a * 0.35 * Math.sin(6 * th - ph);
        d += `${i ? 'L' : 'M'}${(c + rr * Math.cos(th)).toFixed(1)} ${(c + rr * Math.sin(th)).toFixed(1)}`;
      }
      out.push(d + 'Z');
    }
    return out;
  }, [size, rings]);
  return (
    <svg className={cn('fill-none [vector-effect:non-scaling-stroke]', className)} viewBox={`0 0 ${size} ${size}`} aria-hidden="true">
      {paths.map((d, i) => <path key={i} d={d} className={i === 9 || i === 21 ? 'stroke-salmon opacity-85 [stroke-width:1]' : 'stroke-current opacity-[.22] [stroke-width:.75]'} />)}
    </svg>
  );
}

function lobedRing(c: number, r: number, amp: number, lobes: number, phase = 0) {
  let d = '';
  for (let i = 0; i <= 180; i++) {
    const th = (i / 180) * Math.PI * 2, rr = r + amp * Math.sin(lobes * th + phase);
    d += `${i ? 'L' : 'M'}${(c + rr * Math.cos(th)).toFixed(2)} ${(c + rr * Math.sin(th)).toFixed(2)}`;
  }
  return d + 'Z';
}
const MARK_RINGS = [lobedRing(16, 12.2, 1.9, 9), lobedRing(16, 12.2, 1.9, 9, Math.PI), lobedRing(16, 7.4, 1.2, 9, Math.PI / 2)];

export function Mark({ size = 26, className, dotClassName }: { size?: number; className?: string; dotClassName?: string }) {
  return (
    <svg className={cn('block shrink-0 text-foreground', className)} width={size} height={size} viewBox="0 0 32 32" aria-hidden="true">
      <g className="fill-none stroke-current" strokeWidth="1.1">{MARK_RINGS.map((d, i) => <path key={i} d={d} />)}</g>
      <circle cx="16" cy="16" r="3.2" className={cn('fill-primary', dotClassName)} />
    </svg>
  );
}

/* Gallery view like a video call (Zoom / Meet): every tile gets the same size, as large as the stage allows.
   For each column count we fit the tiles into the stage and keep the layout with the biggest tile;
   an incomplete last row is centred. */
import { Children, isValidElement, useLayoutEffect, useRef, useState, type ReactNode } from 'react';

const GAP = 12; // keep in step with the gap-3 utilities below

export function bestGrid(n: number, W: number, H: number, ratio: number, gap = GAP) {
  let best = { cols: 1, w: 0, h: 0 };
  for (let cols = 1; cols <= n; cols++) {
    const rows = Math.ceil(n / cols);
    const w = Math.min((W - gap * (cols - 1)) / cols, ((H - gap * (rows - 1)) / rows) * ratio);
    if (w > best.w) best = { cols, w, h: w / ratio };
  }
  return { cols: best.cols, w: Math.max(0, Math.floor(best.w)), h: Math.max(0, Math.floor(best.h)) };
}

/** ratio: tile width / height (cash-desk cameras are portrait, 3:4). */
export function CameraGallery({ children, ratio = 3 / 4 }: { children: ReactNode; ratio?: number }) {
  const ref = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ W: 0, H: 0 });
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver(([e]) => setSize({ W: e.contentRect.width, H: e.contentRect.height }));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  const items = Children.toArray(children);
  const { cols, w, h } = bestGrid(items.length, size.W, size.H, ratio);

  return (
    <div ref={ref} className="absolute inset-3 sm:inset-4">
      <div className="flex h-full w-full max-w-full flex-wrap content-center items-center justify-center gap-3">
        {/* the row width caps how many tiles wrap per line, so rows hold exactly `cols` tiles */}
        <div className="flex flex-wrap content-center justify-center gap-3" style={{ width: cols * w + (cols - 1) * GAP }}>
          {items.map((c, i) => <div key={isValidElement(c) && c.key != null ? c.key : i} style={{ width: w, height: h }} className="relative">{c}</div>)}
        </div>
      </div>
    </div>
  );
}

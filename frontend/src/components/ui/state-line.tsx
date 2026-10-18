import type { ReactNode } from 'react';
import { cn } from '@/lib/utils';

export type LineState = 'pending' | 'confirm' | 'dismiss';

export function StateLine({ state, children, className }: { state: LineState; children: ReactNode; className?: string }) {
  return (
    <span className={cn('inline-flex items-center gap-2 text-xs font-semibold whitespace-nowrap',
      state === 'pending' ? 'text-primary-ink' : state === 'confirm' ? 'text-destructive' : 'text-muted-foreground', className)}>
      <span aria-hidden="true" className={cn('w-[18px] border-t-2 border-current', state === 'pending' ? 'border-dashed' : 'border-solid', state === 'dismiss' && 'opacity-60')} />
      {children}
    </span>
  );
}

export function Ticks({ states, className }: { states: ('' | 'd' | 'c')[]; className?: string }) {
  return (
    <span aria-hidden="true" className={cn('flex max-w-[260px] flex-wrap justify-end gap-[5px]', className)}>
      {states.map((s, i) => (
        <i key={i} className={cn('block w-[22px] border-t-2 transition-colors duration-300',
          s === 'c' ? 'border-solid border-destructive' : s === 'd' ? 'border-solid border-foreground' : 'border-dashed border-primary-ink')} />
      ))}
    </span>
  );
}

import type { ReactNode } from 'react';
import { cn } from '@/lib/utils';

export interface SegmentedOption<V extends string | number> { value: V; label: ReactNode; count?: ReactNode; lang?: string }

/** Segmented control: a row of tabs in a muted trough, the selected one lifted onto the card tone. */
export function Segmented<V extends string | number>({ value, onChange, options, className, size = 'default', ...rest }: {
  value: V; onChange: (v: V) => void; options: SegmentedOption<V>[]; className?: string; size?: 'default' | 'sm';
} & Omit<React.HTMLAttributes<HTMLDivElement>, 'onChange'>) {
  return (
    <div role="tablist" className={cn('inline-flex gap-0.5 rounded-lg bg-muted p-0.5', className)} {...rest}>
      {options.map(o => {
        const on = o.value === value;
        return (
          <button key={String(o.value)} type="button" role="tab" aria-selected={on} lang={o.lang} onClick={() => onChange(o.value)}
            className={cn('flex items-center gap-1.5 rounded-md font-medium whitespace-nowrap transition-colors',
              size === 'sm' ? 'h-6 px-2 text-xs' : 'h-7 px-2.5 text-[13px]',
              on ? 'bg-card text-foreground shadow-sm' : 'text-muted-foreground hover:text-foreground')}>
            {o.label}
            {o.count !== undefined && <span className="text-faint tabular-nums">{o.count}</span>}
          </button>
        );
      })}
    </div>
  );
}

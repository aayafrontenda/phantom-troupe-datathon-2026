import { cva, type VariantProps } from 'class-variance-authority';
import * as React from 'react';
import { cn } from '@/lib/utils';

/** Filter chip: a hairline pill that inverts to ink when selected. */
const chipVariants = cva(
  'inline-flex h-8 cursor-pointer items-center gap-1.5 rounded-md border px-3 text-[13px] font-semibold whitespace-nowrap transition-[background-color,border-color,transform] duration-150 active:scale-[.97]',
  {
    variants: {
      on: {
        true: 'border-foreground bg-foreground text-background',
        false: 'border-border bg-card text-foreground hover:border-border-strong',
      },
    },
    defaultVariants: { on: false },
  },
);

export interface ChipProps extends React.ButtonHTMLAttributes<HTMLButtonElement>, VariantProps<typeof chipVariants> { count?: React.ReactNode }

function Chip({ className, on, count, children, ...props }: ChipProps) {
  return (
    <button type="button" aria-pressed={!!on} className={cn(chipVariants({ on: !!on }), className)} {...props}>
      {children}
      {count !== undefined && count !== null && <span className="font-medium opacity-65 tabular-nums">{count}</span>}
    </button>
  );
}

export { Chip, chipVariants };

import * as ProgressPrimitive from '@radix-ui/react-progress';
import * as React from 'react';
import { cn } from '@/lib/utils';

const Progress = React.forwardRef<
  React.ElementRef<typeof ProgressPrimitive.Root>,
  React.ComponentPropsWithoutRef<typeof ProgressPrimitive.Root> & { indicatorClassName?: string; indeterminate?: boolean }
>(({ className, value, indicatorClassName, indeterminate, ...props }, ref) => (
  <ProgressPrimitive.Root ref={ref} value={value} data-slot="progress"
    className={cn('relative h-2 w-full overflow-hidden rounded-full bg-muted', className)} {...props}>
    <ProgressPrimitive.Indicator
      className={cn('h-full w-full flex-1 rounded-full bg-primary transition-transform duration-500 ease-out', indicatorClassName)}
      style={{ transform: `translateX(-${100 - (value || 0)}%)` }} />
    {indeterminate && (
      <span aria-hidden="true" className="pointer-events-none absolute inset-y-0 left-0 w-1/3 animate-scan bg-gradient-to-r from-transparent via-white/45 to-transparent dark:via-white/25" />
    )}
  </ProgressPrimitive.Root>
));
Progress.displayName = ProgressPrimitive.Root.displayName;

export { Progress };

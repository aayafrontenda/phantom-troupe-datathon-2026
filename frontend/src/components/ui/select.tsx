import { ChevronDown } from 'lucide-react';
import * as React from 'react';
import { cn } from '@/lib/utils';
import { fieldClass } from './input';

/** Native select with the field look and a lucide chevron. */
const Select = React.forwardRef<HTMLSelectElement, Omit<React.SelectHTMLAttributes<HTMLSelectElement>, 'size'> & { size?: 'default' | 'sm'; wrapperClassName?: string }>(
  ({ className, wrapperClassName, size = 'default', children, ...props }, ref) => (
    <span className={cn('relative inline-block w-full', wrapperClassName)}>
      <select ref={ref} data-slot="select"
        className={cn(fieldClass, 'appearance-none pr-8', size === 'sm' ? 'h-8 pl-2.5 text-[13px]' : 'h-9 pl-3', className)} {...props}>
        {children}
      </select>
      <ChevronDown aria-hidden="true" className="pointer-events-none absolute top-1/2 right-2.5 size-4 -translate-y-1/2 text-faint" />
    </span>
  ),
);
Select.displayName = 'Select';

export { Select };

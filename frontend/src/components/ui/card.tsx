import * as React from 'react';
import { cn } from '@/lib/utils';

export const cardClass = 'overflow-hidden rounded-xl border border-border/60 bg-card text-card-foreground shadow-sm';
const Card = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(({ className, ...props }, ref) => (
  <div ref={ref} data-slot="card" className={cn(cardClass, className)} {...props} />
));
Card.displayName = 'Card';

const CardHeader = ({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) => (
  <div data-slot="card-header" className={cn('flex flex-col gap-1 px-5 pt-5 pb-2', className)} {...props} />
);
const CardTitle = ({ className, ...props }: React.HTMLAttributes<HTMLHeadingElement>) => (
  <h2 data-slot="card-title" className={cn('text-lg font-semibold tracking-tight text-heading', className)} {...props} />
);
const CardDescription = ({ className, ...props }: React.HTMLAttributes<HTMLParagraphElement>) => (
  <p data-slot="card-description" className={cn('text-[13px] text-muted-foreground', className)} {...props} />
);
const CardContent = ({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) => (
  <div data-slot="card-content" className={cn('px-5 pb-5', className)} {...props} />
);

export { Card, CardContent, CardDescription, CardHeader, CardTitle };

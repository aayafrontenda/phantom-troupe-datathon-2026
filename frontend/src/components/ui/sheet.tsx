import * as SheetPrimitive from '@radix-ui/react-dialog';
import { XIcon } from 'lucide-react';
import * as React from 'react';
import { cn } from '@/lib/utils';

const Sheet = SheetPrimitive.Root;
const SheetTrigger = SheetPrimitive.Trigger;
const SheetClose = SheetPrimitive.Close;

const SIDES = {
  right: 'inset-y-0 right-0 h-full w-full border-l sm:max-w-md data-[state=open]:[animation:sheet-in-right_.24s_var(--ease-out)]',
  left: 'inset-y-0 left-0 h-full w-72 border-r data-[state=open]:[animation:sheet-in-left_.24s_var(--ease-out)]',
};

function SheetContent({ className, children, side = 'right', closeLabel = 'Close', ...props }:
  React.ComponentProps<typeof SheetPrimitive.Content> & { side?: keyof typeof SIDES; closeLabel?: string }) {
  return (
    <SheetPrimitive.Portal>
      <SheetPrimitive.Overlay className="fixed inset-0 z-50 bg-black/30 data-[state=open]:[animation:fade-in_.2s_ease]" />
      <SheetPrimitive.Content className={cn('fixed z-50 flex flex-col bg-card shadow-sm', SIDES[side], className)} {...props}>
        {children}
        <SheetPrimitive.Close className="absolute top-3 right-3 grid size-8 place-items-center rounded-md text-muted-foreground transition-colors hover:bg-accent hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring/40 outline-none">
          <XIcon className="size-4" /><span className="sr-only">{closeLabel}</span>
        </SheetPrimitive.Close>
      </SheetPrimitive.Content>
    </SheetPrimitive.Portal>
  );
}

const SheetHeader = ({ className, ...props }: React.ComponentProps<'div'>) => <div className={cn('flex flex-col gap-1 border-b border-border px-5 py-4 pr-12', className)} {...props} />;
const SheetTitle = ({ className, ...props }: React.ComponentProps<typeof SheetPrimitive.Title>) => <SheetPrimitive.Title className={cn('text-base font-semibold text-heading', className)} {...props} />;
const SheetDescription = ({ className, ...props }: React.ComponentProps<typeof SheetPrimitive.Description>) => <SheetPrimitive.Description className={cn('text-sm text-muted-foreground', className)} {...props} />;

export { Sheet, SheetClose, SheetContent, SheetDescription, SheetHeader, SheetTitle, SheetTrigger };

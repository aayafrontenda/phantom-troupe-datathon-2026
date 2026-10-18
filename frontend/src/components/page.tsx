import { AlertTriangle, ChevronLeft } from 'lucide-react';
import type { ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { useI18n } from '../i18n';
import { cn } from '../lib/utils';

export function Page({ wide, className, children }: { wide?: boolean; className?: string; children: ReactNode }) {
  return <div className={cn('mx-auto flex w-full flex-col gap-5 pb-8', wide ? 'max-w-[1480px]' : 'max-w-[1280px]', className)}>{children}</div>;
}

export function PageHeader({ title, lead, actions, className }: { title: ReactNode; lead?: ReactNode; actions?: ReactNode; className?: string }) {
  return (
    <div className={cn('flex flex-wrap items-end justify-between gap-x-5 gap-y-3', className)}>
      <div className="min-w-0">
        <h1 className="text-[22px] font-semibold tracking-tight text-heading sm:text-2xl">{title}</h1>
        {lead && <p className="mt-1.5 max-w-[62ch] text-[14.5px] text-muted-foreground text-pretty">{lead}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

export function Crumb({ to, children, className }: { to: string; children: ReactNode; className?: string }) {
  return (
    <Link to={to} className={cn('-mb-2 inline-flex w-fit items-center gap-1 text-sm font-medium text-muted-foreground no-underline transition-colors hover:text-foreground', className)}>
      <ChevronLeft className="size-4" />{children}
    </Link>
  );
}

export function EmptyState({ title, children, className }: { title?: ReactNode; children?: ReactNode; className?: string }) {
  return (
    <div className={cn('px-6 py-12 text-center text-sm text-muted-foreground text-balance', className)}>
      {title && <p className="mb-1 text-base font-semibold text-foreground">{title}</p>}
      {children}
    </div>
  );
}

export function Loading({ className }: { className?: string }) {
  const { t } = useI18n();
  return (
    <div role="status" className={cn('py-10 text-center text-sm text-muted-foreground', className)}>
      <span aria-hidden="true" className="mx-auto mb-3.5 block h-0.5 w-[120px] origin-left animate-sweep bg-primary" />
      {t('loading')}
    </div>
  );
}

export function Note({ children, icon, className }: { children: ReactNode; icon?: ReactNode; className?: string }) {
  return (
    <div className={cn('flex items-start gap-2.5 rounded-[10px] bg-warning-soft px-4 py-3 text-sm text-foreground [&>svg]:mt-px [&>svg]:size-[18px] [&>svg]:shrink-0 [&>svg]:text-warning', className)}>
      {icon ?? <AlertTriangle strokeWidth={1.7} />}
      <span>{children}</span>
    </div>
  );
}

export function StatStrip({ cols = 4, className, children }: { cols?: 4 | 5; className?: string; children: ReactNode }) {
  return (
    <div className={cn('grid grid-cols-2 border-t border-border', cols === 5 ? 'md:grid-cols-3 xl:grid-cols-5' : 'md:grid-cols-4', className)}>
      {children}
    </div>
  );
}

const TONES = { default: 'text-foreground', warn: 'text-warning', ok: 'text-success', attn: 'text-primary-ink', bad: 'text-destructive' };
export function Stat({ value, label, tone = 'default', small, children, className }:
  { value: ReactNode; label: ReactNode; tone?: keyof typeof TONES; small?: boolean; children?: ReactNode; className?: string }) {
  return (
    <div className={cn('border-b border-border px-[18px] pt-4 pb-3.5 text-left md:border-b-0 md:not-first:border-l', className)}>
      <div className={cn('font-semibold leading-tight tracking-tight tabular-nums', small ? 'text-[22px]' : 'text-[26px] md:text-[30px]', TONES[tone])}>{value}</div>
      <div className="mt-1 text-[13.5px] text-muted-foreground">{label}</div>
      {children !== undefined && <div className="mt-2.5 min-h-[22px] text-[13px]">{children}</div>}
    </div>
  );
}

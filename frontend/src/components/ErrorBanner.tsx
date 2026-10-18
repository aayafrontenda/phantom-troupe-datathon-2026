import { RefreshCw, WifiOff } from 'lucide-react';
import { useI18n } from '../i18n';
import { cn } from '../lib/utils';
import { Button } from './ui/button';

export function ErrorBanner({ message, onRetry, className }: { message?: string; onRetry?: () => void; className?: string }) {
  const { t } = useI18n();
  return (
    <div role="alert" className={cn('flex flex-wrap items-center gap-3 rounded-lg border border-destructive-line bg-destructive-soft px-4 py-3 text-sm text-foreground', className)}>
      <WifiOff className="size-[18px] shrink-0 text-destructive" strokeWidth={1.8} />
      <div className="min-w-0 flex-1">
        <span className="font-medium">{t('err.unavailable')}</span>
        {message && <span className="ml-1.5 text-muted-foreground">{message}</span>}
      </div>
      {onRetry && <Button size="sm" variant="outline" onClick={onRetry}><RefreshCw />{t('retry')}</Button>}
    </div>
  );
}

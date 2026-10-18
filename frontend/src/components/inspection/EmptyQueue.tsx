import { Lock, Upload } from 'lucide-react';
import { useState } from 'react';
import { useI18n } from '../../i18n';
import { cn } from '../../lib/utils';
import { useUploads } from '../uploads';
import { Button } from '../ui/button';
import { DeskIllustration } from './Illustration';

export function EmptyQueue() {
  const { t } = useI18n();
  const { pick, uploadFiles } = useUploads();
  const [over, setOver] = useState(false);
  return (
    <section
      onClick={e => { if (!(e.target as HTMLElement).closest('button')) pick(); }}
      onDragOver={e => { e.preventDefault(); setOver(true); }} onDragLeave={() => setOver(false)}
      onDrop={e => { e.preventDefault(); e.stopPropagation(); setOver(false); uploadFiles([...e.dataTransfer.files]); }}
      className={cn('flex cursor-pointer flex-col items-center rounded-xl border border-dashed bg-card px-6 py-12 text-center shadow-sm transition-colors',
        over ? 'border-primary bg-primary-soft/40' : 'border-border-strong')}>
      <DeskIllustration className="w-[300px] max-w-full" />
      <h2 className="mt-4 text-lg font-semibold text-heading">{t('drop.bigTitle')}</h2>
      <p className="mt-1.5 max-w-[46ch] text-sm text-muted-foreground text-pretty">{t('drop.bigHint')}</p>
      <Button className="mt-5" onClick={pick}><Upload />{t('drop.choose')}</Button>
      <p className="mt-4 flex items-center gap-1.5 text-xs text-faint"><Lock className="size-3.5" />{t('drop.privacy')}</p>
    </section>
  );
}

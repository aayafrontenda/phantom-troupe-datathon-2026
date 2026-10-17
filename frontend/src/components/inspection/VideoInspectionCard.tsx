/* The check being analyzed: title and hint, then the full-width pipeline runner with the cancel action. */
import { X } from 'lucide-react';
import type { ReactNode } from 'react';
import { useI18n } from '../../i18n';
import { cn } from '../../lib/utils';
import type { Job } from '../../types';
import { Button } from '../ui/button';
import { normStage, PipelineProgressBar } from './PipelineProgressBar';

export function VideoInspectionCard({ job, onCancel, className, children }: {
  job: Job; onCancel?: () => void; className?: string; children?: ReactNode;
}) {
  const { t } = useI18n();
  const queued = normStage(job.stage) === 'queued';
  const title = queued ? (job.queue_position ? t('proc.queue', { n: job.queue_position }) : t('proc.starting')) : t('proc.title');

  return (
    <article className={cn('overflow-hidden rounded-xl border border-border/60 bg-card shadow-sm', className)}>
      <div className="px-4 pt-4 pb-3 sm:px-5">
        <h2 className="text-[17px] font-semibold text-heading">{title}</h2>
        <p className="mt-0.5 text-sm text-muted-foreground">{job.stage === 'retry' ? t('proc.retry') : t('proc.sub')}</p>
      </div>
      <div className="border-t border-border/60 bg-subtle/60 px-4 py-3.5 sm:px-5">
        <PipelineProgressBar stage={job.stage} progress={job.progress} etaSec={job.eta_sec}
          actions={onCancel && <Button variant="destructive" size="sm" onClick={onCancel}><X />{t('del.cancelBtn')}</Button>} />
      </div>
      {children}
    </article>
  );
}

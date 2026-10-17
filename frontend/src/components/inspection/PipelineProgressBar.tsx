/* Full-width progress runner: one bar with a scan shimmer, then a single line with the pipeline steps
   (current one with its percent), the ETA and the action. Same data as the former step tiles. */
import { Fragment, type ReactNode } from 'react';
import { useI18n } from '../../i18n';
import { cn } from '../../lib/utils';
import { Progress } from '../ui/progress';

export const STEPS = ['queued', 'frames', 'detection', 'vlm', 'report', 'done'];
export const normStage = (s?: string) => (s === 'started' || s === 'retry' ? 'queued' : (s || 'queued'));

export function PipelineProgressBar({ stage: rawStage, progress, etaSec, actions, className }:
  { stage?: string; progress?: number; etaSec?: number | null; actions?: ReactNode; className?: string }) {
  const { t } = useI18n();
  const stage = normStage(rawStage);
  const ci = Math.max(0, STEPS.indexOf(stage));
  const pct = Math.round((progress || 0) * 100);

  return (
    <div className={cn('flex flex-col gap-3', className)}>
      <Progress value={Math.max(3, pct)} indeterminate aria-label={t(`step.${stage}`)} className="h-2.5" />
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <ol className="flex min-w-0 flex-1 flex-wrap items-center gap-x-1.5 gap-y-1 text-[13px] tabular-nums" aria-live="polite">
          {STEPS.map((k, i) => (
            <Fragment key={k}>
              {i > 0 && <li aria-hidden="true" className="text-faint">›</li>}
              <li aria-current={i === ci ? 'step' : undefined}
                className={cn(i < ci ? 'text-muted-foreground' : i === ci ? 'font-medium text-foreground' : 'text-faint')}>
                {t(`step.${k}`)}{i === ci && i > 0 ? <span className="ml-1 text-primary-ink">{pct}%</span> : null}
              </li>
            </Fragment>
          ))}
          {etaSec != null && <><li aria-hidden="true" className="px-1 text-faint">•</li><li className="text-muted-foreground">{t('proc.eta', { s: etaSec })}</li></>}
        </ol>
        {actions && <div className="flex shrink-0 items-center gap-1.5">{actions}</div>}
      </div>
    </div>
  );
}

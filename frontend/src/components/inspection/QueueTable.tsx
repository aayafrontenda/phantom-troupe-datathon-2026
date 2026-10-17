/* Queue and history of checks: one card with filter tabs, search and the table (stacked rows on phones). */
import { AlertTriangle, CheckCircle2, FileText, FileVideo, Search, ShieldCheck, Trash2, Upload, XCircle } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { Link } from 'react-router-dom';
import { useI18n } from '../../i18n';
import { cn } from '../../lib/utils';
import type { JobRow } from '../../types';
import { tc, useAgo } from '../../ui';
import type { UploadItem } from '../uploads';
import { Badge } from '../ui/badge';
import { Button } from '../ui/button';
import { Progress } from '../ui/progress';
import { Tip } from '../ui/tooltip';

export type QueueFilter = 'all' | 'review' | 'violation' | 'clear';
export const isActive = (j: JobRow) => j.public_status === 'processing';
export const needsReview = (j: JobRow) => j.verdict === 'violation' && j.public_status === 'done' && (j.reviewed || 0) < (j.n_violations || 0);
export const QUEUE_FILTERS: Record<QueueFilter, (j: JobRow) => boolean> = {
  all: () => true,
  review: needsReview,
  violation: j => j.verdict === 'violation' && j.public_status === 'done',
  clear: j => j.verdict === 'no_violation' && j.public_status === 'done',
};

export function QueueTable({ rows, uploads, counts, filter, onFilter, q, onQuery, onDelete, canDelete, reportHref }: {
  rows: JobRow[]; uploads: UploadItem[]; counts: Record<QueueFilter, number>; filter: QueueFilter; onFilter: (f: QueueFilter) => void;
  q: string; onQuery: (q: string) => void; onDelete: (j: JobRow) => void; canDelete: boolean; reportHref: (id: string) => string;
}) {
  const { t } = useI18n();
  const ago = useAgo();
  const nav = useNavigate();

  const status = (j: JobRow) => {
    if (isActive(j)) {
      const queued = j.status === 'queued';
      const pct = Math.round((j.progress || 0) * 100);
      return (
        <div className="flex w-36 flex-col gap-1.5">
          <Badge variant={queued ? 'secondary' : 'accent'}>{queued ? `${t('pill.queued')}${j.queue_position ? `, ${t('pill.ahead', { n: j.queue_position })}` : ''}` : t('pill.analyzing', { p: pct })}</Badge>
          <Progress value={queued ? 3 : Math.max(4, pct)} className="h-1" indeterminate={!queued} />
        </div>
      );
    }
    const part = j.partial ? <Badge variant="outline">{t('pill.partial')}</Badge> : null;
    if (j.public_status === 'failed') return <Badge variant="destructive"><XCircle />{t('pill.failed')}</Badge>;
    if (j.verdict === 'violation') return <span className="flex flex-wrap gap-1"><Badge variant="warning"><AlertTriangle />{t('pill.violations', { n: j.n_violations || 0 })}</Badge>{part}</span>;
    return <span className="flex flex-wrap gap-1"><Badge variant="success"><ShieldCheck />{t('pill.clear')}</Badge>{part}</span>;
  };
  const review = (j: JobRow) => {
    if (j.public_status !== 'done' || j.verdict !== 'violation') return <span className="text-faint">—</span>;
    if ((j.reviewed || 0) >= (j.n_violations || 0)) return <Badge variant="success"><CheckCircle2 />{t('pill.reviewed')}</Badge>;
    return <span className="text-muted-foreground tabular-nums">{t('rev.progress', { a: j.reviewed || 0, b: j.n_violations || 0 })}</span>;
  };

  const tabs: QueueFilter[] = ['all', 'review', 'violation', 'clear'];
  const empty = !rows.length && !uploads.length;

  return (
    <section className="overflow-hidden rounded-xl border border-border/60 bg-card shadow-sm">
      <div className="flex flex-wrap items-center gap-3 border-b border-border/60 px-4 py-3">
        <div role="tablist" aria-label={t('nav.checks')} className="flex gap-0.5 rounded-lg bg-muted p-0.5">
          {tabs.map(k => (
            <button key={k} role="tab" aria-selected={filter === k} onClick={() => onFilter(k)}
              className={cn('flex h-7 items-center gap-1.5 rounded-md px-2.5 text-[13px] font-medium transition-colors',
                filter === k ? 'bg-card text-foreground shadow-sm' : 'text-muted-foreground hover:text-foreground')}>
              {t(`f.${k}`)}
              <span className={cn('tabular-nums', k === 'review' && counts.review ? 'text-primary-ink' : 'text-faint')}>{counts[k]}</span>
            </button>
          ))}
        </div>
        <label className="ml-auto flex h-8 w-full items-center gap-2 rounded-lg border border-border bg-card px-2.5 text-sm focus-within:border-primary focus-within:ring-3 focus-within:ring-primary-soft sm:w-60">
          <Search className="size-4 text-faint" />
          <input value={q} onChange={e => onQuery(e.target.value)} placeholder={t('search')} className="min-w-0 flex-1 bg-transparent outline-none placeholder:text-faint" />
        </label>
      </div>

      {empty ? (
        <div className="px-6 py-14 text-center">
          <p className="font-semibold text-heading">{t(filter === 'review' ? 'empty.review' : 'empty.none')}</p>
          <p className="mt-1 text-sm text-muted-foreground">{t(filter === 'all' && !q ? 'empty.start' : 'empty.other')}</p>
        </div>
      ) : (
        <table className="w-full text-sm">
          <thead className="hidden border-b border-border/60 text-left text-xs text-muted-foreground md:table-header-group">
            <tr>
              <th className="px-4 py-2 font-medium">{t('th.recording')}</th>
              <th className="px-4 py-2 font-medium">{t('th.uploaded')}</th>
              <th className="px-4 py-2 font-medium">{t('th.result')}</th>
              <th className="px-4 py-2 font-medium">{t('th.review')}</th>
              <th className="px-4 py-2"><span className="sr-only">{t('act.open')}</span></th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border/60">
            {uploads.map(u => {
              const f = u.sent / Math.max(1, u.total);
              return (
                <tr key={u.key} className="grid grid-cols-[minmax(0,1fr)_auto] gap-2 px-4 py-3 md:table-row md:p-0">
                  <td className="md:px-4 md:py-3"><FileCell icon={<Upload className="size-4" />} name={u.name} sub={t('row.uploading', { a: (u.sent / 1e6).toFixed(1), b: (u.total / 1e6).toFixed(1) })} /></td>
                  <td className="hidden text-muted-foreground md:table-cell md:px-4">{t('now')}</td>
                  <td className="md:px-4"><div className="flex w-36 flex-col gap-1.5"><Badge variant="secondary">{t('pill.uploading', { p: Math.round(f * 100) })}</Badge><Progress value={f * 100} className="h-1" /></div></td>
                  <td className="hidden md:table-cell" /><td className="hidden md:table-cell" />
                </tr>
              );
            })}
            {rows.map(j => (
              <tr key={j.job_id} className="grid cursor-pointer grid-cols-[minmax(0,1fr)_auto] items-center gap-2 px-4 py-3 transition-colors hover:bg-subtle md:table-row md:p-0"
                onClick={e => { if (!(e.target as HTMLElement).closest('a,button')) nav(`/checks/${j.job_id}`); }}>
                <td className="md:px-4 md:py-3">
                  <FileCell icon={<FileVideo className="size-4" />} name={j.filename}
                    sub={[j.duration_sec ? tc(j.duration_sec) : '', j.processing_sec ? t('row.analysedIn', { s: j.processing_sec }) : '', j.created_by || ''].filter(Boolean).join(' · ')} />
                </td>
                <td className="hidden whitespace-nowrap text-muted-foreground md:table-cell md:px-4">{ago(j.created_at)}</td>
                <td className="col-start-1 md:px-4">{status(j)}</td>
                <td className="col-start-1 md:px-4">{review(j)}</td>
                <td className="col-start-2 row-span-2 row-start-1 md:px-4">
                  <div className="flex items-center justify-end gap-1">
                    {needsReview(j) ? <Button asChild size="sm"><Link to={`/checks/${j.job_id}`}>{t('act.review')}</Link></Button>
                      : <Button asChild size="sm" variant="outline"><Link to={`/checks/${j.job_id}`}>{t('act.open')}</Link></Button>}
                    {j.public_status === 'done' && (
                      <Tip label={t('act.report')}>
                        <Button asChild size="icon-sm" variant="ghost"><a href={reportHref(j.job_id)} target="_blank" rel="noopener" aria-label={t('act.openReport')}><FileText /></a></Button>
                      </Tip>
                    )}
                    {canDelete && (
                      <Tip label={t(isActive(j) ? 'act.cancelDelete' : 'act.delete')}>
                        <Button size="icon-sm" variant="ghost" className="hover:bg-destructive-soft hover:text-destructive" onClick={() => onDelete(j)} aria-label={t('act.delete')}><Trash2 /></Button>
                      </Tip>
                    )}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}

function FileCell({ icon, name, sub }: { icon: React.ReactNode; name: string; sub?: string }) {
  return (
    <div className="flex min-w-0 items-center gap-3">
      <span className="grid size-8 shrink-0 place-items-center rounded-lg border border-border/60 text-muted-foreground">{icon}</span>
      <div className="min-w-0">
        <div className="truncate font-medium text-foreground" title={name}>{name}</div>
        {sub && <div className="truncate text-xs text-muted-foreground tabular-nums">{sub}</div>}
      </div>
    </div>
  );
}

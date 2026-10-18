import { useCallback, useEffect, useMemo, useState } from 'react';
import { api } from '../api';
import { useAuth } from '../auth';
import { ErrorBanner } from '../components/ErrorBanner';
import { EmptyQueue } from '../components/inspection/EmptyQueue';
import { PageBanner } from '../components/inspection/PageBanner';
import { isActive, QUEUE_FILTERS, QueueTable, type QueueFilter } from '../components/inspection/QueueTable';
import { DropZone, useUploads } from '../components/uploads';
import { useI18n } from '../i18n';
import type { JobRow } from '../types';
import { useUi } from '../ui';

export function reportUrl(id: string, lang: string) { return `/ui/api/jobs/${id}/report.html?lang=${lang}`; }

export default function ChecksPage() {
  const { t, lang } = useI18n();
  const { confirm, toast } = useUi();
  const { can } = useAuth();
  const { uploads, pick, version } = useUploads();
  const [jobs, setJobs] = useState<JobRow[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [failed, setFailed] = useState<string | null>(null);
  const [filter, setFilter] = useState<QueueFilter>('all');
  const [q, setQ] = useState('');

  const refresh = useCallback(async () => {
    try { setJobs((await api<{ jobs: JobRow[] }>('/ui/api/jobs?limit=200')).jobs); setLoaded(true); setFailed(null); }
    catch (e) { setFailed((e as Error).message); }
  }, []);
  useEffect(() => { refresh(); }, [refresh, version]);
  useEffect(() => {
    const fast = jobs.some(isActive) || uploads.length > 0;
    const id = setInterval(refresh, fast ? 2000 : 15000);
    return () => clearInterval(id);
  }, [jobs, uploads.length, refresh]);

  const cnt = useMemo(() => Object.fromEntries((Object.keys(QUEUE_FILTERS) as QueueFilter[]).map(k => [k, jobs.filter(QUEUE_FILTERS[k]).length])) as Record<QueueFilter, number>, [jobs]);
  const rows = jobs.filter(QUEUE_FILTERS[filter]).filter(j => !q.trim() || (j.filename || '').toLowerCase().includes(q.trim().toLowerCase()));

  const del = async (j: JobRow) => {
    const active = isActive(j);
    const ok = await confirm(t(active ? 'del.cancelTitle' : 'del.deleteTitle'), <><b>{j.filename}</b><br />{t(active ? 'del.cancelText' : 'del.deleteText')}</>, t(active ? 'del.cancelBtn' : 'act.delete'));
    if (!ok) return;
    try {
      await api(`/ui/api/jobs/${j.job_id}`, { method: 'DELETE' });
      setJobs(x => x.filter(y => y.job_id !== j.job_id));
      toast(t(active ? 'del.cancelled' : 'del.deleted'));
    } catch (e) { toast((e as Error).message, 'err'); }
  };

  return (
    <div className="mx-auto flex max-w-[1280px] flex-col gap-5 pb-8">
      <PageBanner onUpload={pick} />
      {failed && <ErrorBanner message={failed} onRetry={refresh} />}
      {loaded && !jobs.length && !uploads.length ? <EmptyQueue /> : (
        <>
          <DropZone onPick={pick} />
          <QueueTable rows={rows} uploads={uploads} counts={cnt} filter={filter} onFilter={setFilter} q={q} onQuery={setQ}
            onDelete={del} canDelete={can('operator')} reportHref={id => reportUrl(id, lang)} />
        </>
      )}
    </div>
  );
}

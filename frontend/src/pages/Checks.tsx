import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { api } from '../api';
import { useAuth } from '../auth';
import { DropZone, useUploads } from '../components/uploads';
import { useI18n } from '../i18n';
import type { JobRow } from '../types';
import { Icon, tc, useAgo, useUi } from '../ui';

type Filter = 'all' | 'review' | 'violation' | 'clear';
const isActive = (j: JobRow) => j.public_status === 'processing';
const needsReview = (j: JobRow) => j.verdict === 'violation' && j.public_status === 'done' && (j.reviewed || 0) < (j.n_violations || 0);
const FILTERS: Record<Filter, (j: JobRow) => boolean> = {
  all: () => true,
  review: needsReview,
  violation: j => j.verdict === 'violation' && j.public_status === 'done',
  clear: j => j.verdict === 'no_violation' && j.public_status === 'done',
};

export function reportUrl(id: string, lang: string) { return `/ui/api/jobs/${id}/report.html?lang=${lang}`; }

export default function ChecksPage() {
  const { t, lang } = useI18n();
  const { confirm, toast } = useUi();
  const { can } = useAuth();
  const ago = useAgo();
  const nav = useNavigate();
  const { uploads, pick, version } = useUploads();
  const [jobs, setJobs] = useState<JobRow[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [filter, setFilter] = useState<Filter>('all');
  const [q, setQ] = useState('');

  const refresh = useCallback(async () => {
    try { setJobs((await api<{ jobs: JobRow[] }>('/ui/api/jobs?limit=200')).jobs); setLoaded(true); } catch { /* keep */ }
  }, []);
  useEffect(() => { refresh(); }, [refresh, version]);
  useEffect(() => {
    const fast = jobs.some(isActive) || uploads.length > 0;
    const id = setInterval(refresh, fast ? 2000 : 15000);
    return () => clearInterval(id);
  }, [jobs, uploads.length, refresh]);

  const cnt = useMemo(() => Object.fromEntries((Object.keys(FILTERS) as Filter[]).map(k => [k, jobs.filter(FILTERS[k]).length])) as Record<Filter, number>, [jobs]);
  const rows = jobs.filter(FILTERS[filter]).filter(j => !q.trim() || (j.filename || '').toLowerCase().includes(q.trim().toLowerCase()));

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

  const statusCell = (j: JobRow) => {
    if (j.public_status === 'processing') {
      const queued = j.status === 'queued';
      const pct = Math.round((j.progress || 0) * 100);
      return <><span className="pill info">{queued ? `${t('pill.queued')}${j.queue_position ? ` · ${t('pill.ahead', { n: j.queue_position })}` : ''}` : t('pill.analyzing', { p: pct })}</span>
        <div className="minibar"><i style={{ width: `${queued ? 3 : Math.max(4, pct)}%` }} /></div></>;
    }
    const part = j.partial ? <> <span className="pill neutral">{t('pill.partial')}</span></> : null;
    if (j.public_status === 'failed') return <span className="pill bad"><Icon id="x" />{t('pill.failed')}</span>;
    if (j.verdict === 'violation') return <><span className="pill warn"><Icon id="alert" />{t('pill.violations', { n: j.n_violations || 0 })}</span>{part}</>;
    return <><span className="pill ok"><Icon id="shield" />{t('pill.clear')}</span>{part}</>;
  };
  const reviewCell = (j: JobRow) => {
    if (j.public_status !== 'done' || j.verdict !== 'violation') return <span className="muted">—</span>;
    if ((j.reviewed || 0) >= (j.n_violations || 0)) return <span className="pill ok"><Icon id="check" />{t('pill.reviewed')}</span>;
    return <span className="muted">{t('rev.progress', { a: j.reviewed || 0, b: j.n_violations || 0 })}</span>;
  };

  return (
    <div className="page">
      <div className="page-head">
        <div><h1>{t('checks.title')}</h1><p>{t('checks.lead')}</p></div>
        <button className="btn primary lg" onClick={pick}><Icon id="up" />{t('checks.upload')}</button>
      </div>
      {loaded && !jobs.length && !uploads.length ? (
        <>
          <DropZone big onPick={pick} />
          <p className="muted row" style={{ justifyContent: 'center' }}><Icon id="lock" />{t('drop.privacy')}</p>
        </>
      ) : (
        <>
          <DropZone onPick={pick} />
          <div className="stats">
            {([['all', ''], ['review', 'attn'], ['violation', 'warn'], ['clear', 'ok']] as [Filter, string][]).map(([k, c]) => (
              <button key={k} className={`stat ${c} ${filter === k ? 'on' : ''}`} onClick={() => setFilter(k)}>
                <div className="n">{cnt[k]}</div><div className="l">{t(`f.${k}`)}</div>
              </button>
            ))}
          </div>
          <div className="toolbar">
            <label className="search"><Icon id="search" /><input className="field" placeholder={t('search')} value={q} onChange={e => setQ(e.target.value)} /></label>
          </div>
          <div className="card">
            {!rows.length && !uploads.length ? (
              <div className="empty"><b>{t(filter === 'review' ? 'empty.review' : 'empty.none')}</b>{t(filter === 'all' && !q ? 'empty.start' : 'empty.other')}</div>
            ) : (
              <table className="table">
                <thead><tr><th>{t('th.recording')}</th><th>{t('th.uploaded')}</th><th>{t('th.result')}</th><th>{t('th.review')}</th><th /></tr></thead>
                <tbody>
                  {uploads.map(u => (
                    <tr key={u.key}>
                      <td><div className="fname"><span className="ic"><Icon id="up" /></span><div><b>{u.name}</b><small>{t('row.uploading', { a: (u.sent / 1e6).toFixed(1), b: (u.total / 1e6).toFixed(1) })}</small></div></div></td>
                      <td className="c-hide muted">{t('now')}</td>
                      <td><span className="pill info">{t('pill.uploading', { p: Math.round(u.sent / Math.max(1, u.total) * 100) })}</span><div className="minibar"><i style={{ width: `${u.sent / Math.max(1, u.total) * 100}%` }} /></div></td>
                      <td /><td />
                    </tr>
                  ))}
                  {rows.map(j => (
                    <tr key={j.job_id} className="click" onClick={e => { if (!(e.target as HTMLElement).closest('a,button')) nav(`/checks/${j.job_id}`); }}>
                      <td><div className="fname"><span className="ic"><Icon id="film" /></span><div><b title={j.filename}>{j.filename}</b>
                        <small className="num">{j.duration_sec ? tc(j.duration_sec) : ''}{j.processing_sec ? ` · ${t('row.analysedIn', { s: j.processing_sec })}` : ''}{j.created_by ? ` · ${j.created_by}` : ''}</small></div></div></td>
                      <td className="c-hide muted">{ago(j.created_at)}</td>
                      <td>{statusCell(j)}</td>
                      <td>{reviewCell(j)}</td>
                      <td className="c-acts"><div className="row-acts">
                        {needsReview(j) ? <Link className="btn sm primary" to={`/checks/${j.job_id}`}>{t('act.review')}</Link> : <Link className="btn sm" to={`/checks/${j.job_id}`}>{t('act.open')}</Link>}
                        {j.public_status === 'done' && <a className="icon-btn" href={reportUrl(j.job_id, lang)} target="_blank" rel="noopener" title={t('act.report')} aria-label={t('act.openReport')}><Icon id="doc" /></a>}
                        {can('operator') && <button className="icon-btn danger" onClick={() => del(j)} title={t(isActive(j) ? 'act.cancelDelete' : 'act.delete')} aria-label={t('act.delete')}><Icon id="trash" /></button>}
                      </div></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </>
      )}
    </div>
  );
}

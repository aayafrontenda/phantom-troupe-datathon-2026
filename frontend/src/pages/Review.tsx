import { Check, Download, Film, Flag, Pencil, Search, Video } from 'lucide-react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { api } from '../api';
import { ErrorBanner } from '../components/ErrorBanner';
import { useFeed } from '../components/events';
import { EmptyState, Page, PageHeader } from '../components/page';
import { Badge } from '../components/ui/badge';
import { Button } from '../components/ui/button';
import { Card } from '../components/ui/card';
import { Chip } from '../components/ui/chip';
import { Input } from '../components/ui/input';
import { Select } from '../components/ui/select';
import { useI18n } from '../i18n';
import { useRules } from '../lib/rules';
import { cn } from '../lib/utils';
import type { FindingBrief } from '../types';
import { tc, useAgo } from '../ui';

type Quick = 'all' | 'pending' | 'rejected' | 'confirmed' | 'toVerify' | 'verified' | 'disagreed' | 'edited';
const QUICK: Record<Quick, Record<string, string>> = {
  all: {}, pending: { decision: 'pending' }, rejected: { decision: 'reject' }, confirmed: { decision: 'confirm' },
  toVerify: { decision: 'decided', verified: 'false' }, verified: { verified: 'true' }, disagreed: { verified: 'true', verify_result: 'disagree' }, edited: { edited: 'true' },
};
const PAGE = 50;
const PERIOD_SEC: Record<string, number> = { today: 86400, week: 7 * 86400, month: 30 * 86400 };

interface ListResponse { findings: FindingBrief[]; total: number; counts: Record<string, number>; operators: string[] }

const th = 'px-5 py-3 text-left text-xs font-semibold text-muted-foreground';
const td = 'md:px-5 md:py-3.5 md:align-middle';

export default function ReviewPage() {
  const { t, typeName } = useI18n();
  const ago = useAgo();
  const nav = useNavigate();
  const [sp, setSp] = useSearchParams();
  const quick = (sp.get('q') as Quick) || 'rejected';
  const source = sp.get('source') || '';
  const type = sp.get('type') || '';
  const op = sp.get('op') || '';
  const period = sp.get('period') || '';
  const text = sp.get('text') || '';
  const [rows, setRows] = useState<FindingBrief[]>([]);
  const [total, setTotal] = useState(0);
  const [ops, setOps] = useState<string[]>([]);
  const [failed, setFailed] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const { types } = useRules();
  const feed = useFeed();
  const counts = feed.counts;
  const rowsRef = useRef(rows);
  useEffect(() => { rowsRef.current = rows; }, [rows]);

  const set = (k: string, v: string) => { const n = new URLSearchParams(sp); if (v) n.set(k, v); else n.delete(k); setSp(n, { replace: true }); };

  const params = useCallback((limit: number, offset: number) => {
    const p = new URLSearchParams({ limit: String(limit), offset: String(offset) });
    const q = QUICK[quick] || {};
    Object.entries(q).forEach(([k, v]) => p.set(k, v));
    if (source) p.set('source', source);
    if (type) p.set('type_code', type);
    if (op) p.set('decided_by', op);
    if (text) p.set('q', text);
    if (period && PERIOD_SEC[period]) p.set('since', String(Date.now() / 1000 - PERIOD_SEC[period]));
    return p;
  }, [quick, source, type, op, text, period]);

  // a refresh re-reads everything already on screen (offset 0, limit = rows loaded); "more" appends the next page
  const load = useCallback(async (append = false) => {
    const have = rowsRef.current.length;
    const p = append ? params(PAGE, have) : params(Math.max(PAGE, have), 0);
    setBusy(true);
    try {
      const d = await api<ListResponse>(`/ui/api/findings?${p}`);
      setRows(r => append ? [...r, ...d.findings] : d.findings);
      setTotal(d.total);
      setOps(d.operators || []);
      setFailed(null);
    } catch (e) { setFailed((e as Error).message); }
    finally { setBusy(false); }
  }, [params]);

  // filters changed: start from the first page; live updates re-read what is on screen
  useEffect(() => { rowsRef.current = []; }, [params]);
  useEffect(() => { load(); }, [load, feed.items]);

  const tiles: [Quick, number | undefined][] = useMemo(() => [
    ['rejected', counts.rejected], ['toVerify', counts.to_verify], ['confirmed', counts.confirmed],
    ['pending', counts.pending], ['verified', counts.verified], ['disagreed', counts.disagreed], ['edited', counts.edited], ['all', counts.total],
  ], [counts]);

  const where = (f: FindingBrief) => f.source === 'camera' ? f.camera_name || f.camera_id : f.filename || f.job_id;

  return (
    <Page wide>
      <PageHeader title={t('rv.title')} lead={t('rv.lead')}
        actions={<Button asChild variant="secondary"><a href="/ui/api/findings.csv"><Download />{t('rv.export')}</a></Button>} />
      <div className="flex flex-wrap gap-1.5">
        {tiles.map(([k, n]) => <Chip key={k} on={quick === k} count={n} onClick={() => set('q', k)}>{t(`rv.${k}`)}</Chip>)}
      </div>
      <div className="flex flex-wrap items-center gap-2" role="group" aria-label={t('rv.filters')}>
        <Select size="sm" wrapperClassName="w-auto min-w-[150px]" aria-label={t('rv.source')} value={source} onChange={e => set('source', e.target.value)}>
          <option value="">{t('rv.src.all')}</option><option value="upload">{t('rv.src.upload')}</option><option value="camera">{t('rv.src.camera')}</option>
        </Select>
        <Select size="sm" wrapperClassName="w-auto min-w-[150px] max-w-[340px]" aria-label={t('rv.type')} value={type} onChange={e => set('type', e.target.value)}>
          <option value="">{t('rv.anyType')}</option>{types.map(x => <option key={x.code} value={x.code}>{x.code} · {typeName(x.code, x.type)}</option>)}
        </Select>
        <Select size="sm" wrapperClassName="w-auto min-w-[150px]" aria-label={t('rv.operator')} value={op} onChange={e => set('op', e.target.value)}>
          <option value="">{t('rv.anyOp')}</option>{ops.map(o => <option key={o} value={o}>{o}</option>)}
        </Select>
        <Select size="sm" wrapperClassName="w-auto min-w-[150px]" aria-label={t('rv.period')} value={period} onChange={e => set('period', e.target.value)}>
          <option value="">{t('rv.any')}</option><option value="today">{t('rv.today')}</option><option value="week">{t('rv.week')}</option><option value="month">{t('rv.month')}</option>
        </Select>
        <label className="relative w-full max-w-[280px] min-w-[220px] flex-1">
          <Search className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-faint" aria-hidden="true" />
          <Input size="sm" className="pl-8" placeholder={t('search.any')} aria-label={t('search.any')} defaultValue={text}
            onKeyDown={e => { if (e.key === 'Enter') set('text', (e.target as HTMLInputElement).value); }} />
        </label>
      </div>
      {failed && <ErrorBanner message={failed} onRetry={() => load()} />}
      <Card>
        {!rows.length ? <EmptyState title={t('rv.empty')}>{t('rv.emptyHint')}</EmptyState> : (
          <>
            <table className="w-full text-sm">
              <thead className="hidden border-b border-border md:table-header-group">
                <tr><th className={th}>{t('rv.th.when')}</th><th className={th}>{t('rv.th.where')}</th><th className={th}>{t('rv.th.type')}</th><th className={th}>{t('rv.th.ai')}</th><th className={th}>{t('rv.th.decision')}</th><th className={th}>{t('rv.th.verify')}</th><th className={th}><span className="sr-only">{t('act.open')}</span></th></tr>
              </thead>
              <tbody className="divide-y divide-border">
                {rows.map(f => {
                  const primary = f.decision && !f.verified;
                  return (
                    <tr key={f.id} className="grid cursor-pointer grid-cols-[minmax(0,1fr)_auto] gap-x-3 gap-y-1.5 px-4 py-3 transition-colors hover:bg-subtle md:table-row md:p-0"
                      onClick={e => { if (!(e.target as HTMLElement).closest('a,button')) nav(`/findings/${f.id}?from=review`); }}>
                      <td className={cn(td, 'text-xs whitespace-nowrap text-muted-foreground md:text-sm')}>{ago(f.created_at)}</td>
                      <td className={cn(td, 'col-start-1')}>
                        <div className="flex min-w-0 items-center gap-3">
                          <span className="hidden size-9 shrink-0 place-items-center rounded-lg bg-muted text-muted-foreground md:grid">{f.source === 'camera' ? <Video className="size-4" /> : <Film className="size-4" />}</span>
                          <div className="min-w-0"><b className="block max-w-[34ch] truncate font-semibold">{where(f)}</b>{f.t_sec != null && <small className="text-xs text-muted-foreground tabular-nums">{tc(f.t_sec)}</small>}</div>
                        </div>
                      </td>
                      <td className={cn(td, 'col-start-1')}>{typeName(f.type_code, f.type_name)}{f.edited && <> <Badge variant="info" title={t('rv.edited')}><Pencil /></Badge></>}</td>
                      <td className={cn(td, 'col-start-1 flex flex-wrap gap-1 md:table-cell')}>
                        <Badge variant="warning">{f.confidence != null ? t('rv.aiViolation', { p: Math.round(f.confidence * 100) }) : t('v.badTitle')}</Badge>
                        {f.below_threshold && <> <Badge variant="muted" title={t('f.belowThresholdTip')}>{t('f.belowThreshold')}</Badge></>}
                      </td>
                      <td className={cn(td, 'col-start-1')}>
                        {f.decision ? <><Badge variant={f.decision === 'confirm' ? 'destructive' : 'muted'}>{t(f.decision === 'confirm' ? 'f.confirmed' : 'f.notViolation')}</Badge><div className="text-[13px] text-muted-foreground">{f.decided_by_name || f.decided_by}</div></>
                          : <Badge variant="warning">{t('fd.notDecided')}</Badge>}
                      </td>
                      <td className={cn(td, 'col-start-1')}>
                        {f.verified ? <><Badge variant={f.verify_result === 'agree' ? 'success' : 'destructive'}>{f.verify_result === 'agree' ? <Check /> : <Flag />}{t(f.verify_result === 'agree' ? 'fd.agree' : 'fd.disagree')}</Badge><div className="text-[13px] text-muted-foreground">{f.verified_by_name || f.verified_by}</div></>
                          : <span className="text-muted-foreground">{f.decision ? t('fd.notVerified') : '-'}</span>}
                      </td>
                      <td className={cn(td, 'col-start-2 row-span-6 row-start-1 self-center md:text-right')}>
                        <Button asChild size="xs" variant={primary ? 'default' : 'secondary'}>
                          <Link to={`/findings/${f.id}?from=review`}>{t(primary ? 'rv.verifyBtn' : 'act.open')}</Link>
                        </Button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            <div className="flex items-center justify-end gap-2.5 border-t border-border px-5 py-3 text-[13.5px] text-muted-foreground">
              <span>{t('rv.total', { n: rows.length, t: total })}</span>
              {rows.length < total && <Button size="xs" variant="secondary" disabled={busy} onClick={() => load(true)}>{t('rv.more')}</Button>}
            </div>
          </>
        )}
      </Card>
    </Page>
  );
}

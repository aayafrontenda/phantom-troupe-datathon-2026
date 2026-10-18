import { Download, ShieldCheck, User } from 'lucide-react';
import { useCallback, useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { api } from '../api';
import { ErrorBanner } from '../components/ErrorBanner';
import { useFeed } from '../components/events';
import { EmptyState, Loading, Note, Page, PageHeader, Stat, StatStrip } from '../components/page';
import { Badge } from '../components/ui/badge';
import { Button } from '../components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../components/ui/card';
import { Segmented } from '../components/ui/segmented';
import { Select } from '../components/ui/select';
import { useI18n } from '../i18n';
import { cn } from '../lib/utils';
import type { Quality } from '../types';

const PERIODS: [number, string][] = [[7, 'q.p7'], [30, 'q.p30'], [0, 'q.pAll']];

function pct(v: number | null | undefined, digits = 0): string {
  return v == null ? '-' : `${(v * 100).toFixed(digits)}%`;
}

const th = 'px-5 py-3 text-left text-xs font-semibold text-muted-foreground';
const td = 'md:px-5 md:py-3.5 md:align-middle';
const link = 'font-semibold no-underline hover:underline';

export default function QualityPage() {
  const { t, typeName, locale } = useI18n();
  const nav = useNavigate();
  const [days, setDays] = useState(30);
  const [cam, setCam] = useState('');
  const [data, setData] = useState<Quality | null>(null);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState<string | null>(null);
  const [cams, setCams] = useState<{ id: string; name: string }[]>([]);
  const feed = useFeed();

  const load = useCallback(async () => {
    const p = new URLSearchParams({ days: String(days) });
    if (cam) p.set('camera_id', cam);
    try { setData(await api<Quality>(`/ui/api/quality?${p}`)); setFailed(null); }
    catch (e) { setFailed((e as Error).message); }
    finally { setLoading(false); }
  }, [days, cam]);
  useEffect(() => { load(); }, [load, feed.items]);
  useEffect(() => { api<{ cameras: { id: string; name: string }[] }>('/ui/api/cameras').then(d => setCams(d.cameras)).catch(() => { }); }, []);

  const nf = new Intl.NumberFormat(locale);
  const s = data?.summary;
  const verifiedBasis = s?.basis === 'verified';
  const accuracy = s?.accuracy ?? null;
  const delta = s?.accuracy_delta_pp ?? null;
  const raised = data?.by_type.filter(x => x.threshold.status === 'raised') || [];
  const retrain = data?.by_type.filter(x => x.threshold.status === 'retrain') || [];
  const fmtTh = (v: number) => v.toLocaleString(locale, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const steps = [1, 2, 3, 4, 5] as const;

  return (
    <Page wide>
      <PageHeader title={t('q.title')} lead={t('q.lead')} actions={<>
        {cams.length > 0 && (
          <Select size="sm" wrapperClassName="w-auto max-w-[220px]" aria-label={t('adm.cams')} value={cam} onChange={e => setCam(e.target.value)}>
            <option value="">{t('q.camAll')}</option>{cams.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
          </Select>
        )}
        <Segmented value={days} onChange={setDays} aria-label={t('rv.period')} options={PERIODS.map(([d, k]) => ({ value: d, label: t(k) }))} />
        <Button asChild><a href={`/ui/api/quality/dataset.zip?days=${days}`} title={t('q.exportHint')}><Download />{t('q.export')}</a></Button>
      </>} />

      {failed && <ErrorBanner message={failed} onRetry={() => { setLoading(true); load(); }} />}
      {!data ? (loading ? <Loading /> : null) : !s?.decided ? (
        <Card><EmptyState title={t('q.empty')}>{t('q.emptyHint')}</EmptyState></Card>
      ) : (
        <>
          <StatStrip>
            <Stat tone="ok" value={pct(accuracy)} label={t(verifiedBasis ? 'q.accuracy' : 'q.accuracyOp')}>
              {delta != null && days > 0 ? <Badge variant={delta >= 0 ? 'success' : 'destructive'}>{t('q.delta', { d: (delta > 0 ? '+' : '') + delta.toLocaleString(locale), n: days })}</Badge>
                : <span className="text-muted-foreground">{days > 0 ? t('q.noPrev') : ''}</span>}
            </Stat>
            <Stat tone="warn" value={pct(accuracy == null ? null : 1 - accuracy)} label={t(verifiedBasis ? 'q.false' : 'q.falseOp')}>
              <span className="text-muted-foreground tabular-nums">{verifiedBasis ? `${nf.format(s.false_verified)} / ${nf.format(s.verified)}` : `${nf.format(s.rejected)} / ${nf.format(s.decided)}`}</span>
            </Stat>
            <Stat value={nf.format(s.decided)} label={t('q.decided', { n: nf.format(s.verified) })}>
              <span className="text-muted-foreground">{s.coverage != null && t('q.coverage', { p: Math.round(s.coverage * 100) })}</span>
            </Stat>
            <Stat tone="attn" value={nf.format(s.flagged)} label={t('q.flagged')}>
              <Link to="/review?q=disagreed" className={link}>{t('q.openReview')}</Link>
            </Stat>
          </StatStrip>

          <div className="grid gap-5 xl:grid-cols-[minmax(0,1.25fr)_minmax(0,1fr)]">
            <Card>
              <CardHeader><CardTitle>{t('q.byType')}</CardTitle><CardDescription>{t('q.byTypeLead')}</CardDescription></CardHeader>
              <CardContent className="pt-3">
                <div className="grid gap-3">
                  {data.by_type.filter(x => x.decided > 0).map(x => {
                    const tip = x.threshold.status === 'raised' ? t('q.thRaised', { v: fmtTh(x.threshold.applied), b: fmtTh(x.threshold.base) }) : t('q.thBase', { v: fmtTh(x.threshold.applied) });
                    return (
                      <Link key={x.type_code} to={`/review?q=all&type=${x.type_code}`}
                        className="group grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-3 gap-y-1.5 rounded-md text-sm no-underline sm:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)_170px] sm:gap-3.5">
                        <div className="flex min-w-0 items-center gap-2.5">
                          <Badge variant="secondary" className="font-semibold">{x.type_code}</Badge>
                          <span className="truncate transition-colors group-hover:text-primary-ink">{typeName(x.type_code, x.type_name)}</span>
                        </div>
                        <div className="relative h-2.5 overflow-hidden rounded-sm bg-muted max-sm:col-span-2" title={tip}>
                          <i className="absolute inset-y-0 left-0 block rounded-sm bg-foreground" style={{ width: `${(x.confirm_rate || 0) * 100}%` }} />
                        </div>
                        <div className="flex flex-col items-start gap-1 text-[13.5px] leading-tight whitespace-nowrap text-muted-foreground tabular-nums max-sm:col-start-2 max-sm:row-start-1">
                          <span>{pct(x.confirm_rate)} · {nf.format(x.decided)}</span>
                          {x.threshold.status === 'raised' && <Badge variant="accent">{tip}</Badge>}
                        </div>
                      </Link>
                    );
                  })}
                </div>
                <Note className="mt-[18px]" icon={<ShieldCheck strokeWidth={1.7} />}>
                  {raised.length ? t('q.raised', { list: raised.map(x => `${x.type_code} → ${fmtTh(x.threshold.applied)}`).join(', '), n: nf.format(data.dataset.verified) })
                    : t('q.noRaised', { base: fmtTh(data.thresholds.base), p: Math.round(data.thresholds.target * 100), n: data.thresholds.min_samples })}
                  {retrain.length > 0 && <> {t('q.retrain', { list: retrain.map(x => x.type_code).join(', '), p: Math.round(data.thresholds.target * 100) })}</>}
                </Note>
              </CardContent>
            </Card>

            <Card>
              <CardHeader><CardTitle>{t('q.weekly')}</CardTitle><CardDescription>{t('q.weeklyLead')}</CardDescription></CardHeader>
              <CardContent className="pt-3">
                <div className="flex h-[150px] items-stretch gap-1.5 pt-1 sm:h-[190px] sm:gap-2.5">
                  {data.weekly.map(w => {
                    const h = w.rate == null ? 0 : Math.max(4, w.rate * 100);
                    const recent = data.period.since == null || w.start + 7 * 86400 > data.period.since;
                    return (
                      <div key={w.start} className="flex min-w-0 flex-1 flex-col items-center gap-1.5" title={`${nf.format(w.false)} / ${nf.format(w.decided)}`}>
                        <span className="h-[18px] text-xs text-muted-foreground tabular-nums">{w.rate == null ? '' : pct(w.rate)}</span>
                        <div className="flex w-full flex-1 items-end rounded bg-subtle px-1.5"><i className={cn('block w-full rounded-t-[3px]', recent ? 'bg-primary' : 'bg-border-strong')} style={{ height: `${h}%` }} /></div>
                        <span className="text-[11.5px] text-faint tabular-nums">{w.week}</span>
                      </div>
                    );
                  })}
                </div>
                <div className="mt-1 text-[13px] text-muted-foreground">{t('q.week')}</div>
                <div className="mt-[18px] grid gap-px overflow-hidden rounded-[10px] border border-border bg-border sm:grid-cols-3">
                  {([[nf.format(data.dataset.examples), 'q.dsExamples'], [nf.format(data.dataset.negatives), 'q.dsNeg'], [`${raised.length} ⁄ ${data.by_type.length}`, 'q.dsRaised']] as const).map(([v, k]) => (
                    <div key={k} className="flex flex-col gap-0.5 bg-card px-3.5 py-3"><b className="text-[22px] leading-tight font-semibold tabular-nums">{v}</b><span className="text-xs text-muted-foreground">{t(k)}</span></div>
                  ))}
                </div>
              </CardContent>
            </Card>
          </div>

          <Card>
            <CardHeader className="pb-3"><CardTitle>{t('q.ops')}</CardTitle><CardDescription>{t('q.opsLead')}</CardDescription></CardHeader>
            <table className="w-full text-sm">
              <thead className="hidden border-y border-border md:table-header-group">
                <tr><th className={th}>{t('q.th.op')}</th><th className={th}>{t('q.th.decided')}</th><th className={th}>{t('q.th.rejected')}</th><th className={th}>{t('q.th.edited')}</th><th className={th}>{t('q.th.verified')}</th><th className={th}>{t('q.th.disagreed')}</th><th className={th}><span className="sr-only">{t('act.open')}</span></th></tr>
              </thead>
              <tbody className="divide-y divide-border border-t border-border md:border-t-0">
                {data.operators.map(o => {
                  const href = `/review?q=all&op=${encodeURIComponent(o.login)}`;
                  const cell = (label: string, body: React.ReactNode, cls = '') => (
                    <td className={cn(td, 'col-start-1 text-[13px] tabular-nums md:text-sm', cls)}><span className="text-xs text-muted-foreground md:hidden">{label}: </span>{body}</td>
                  );
                  return (
                    <tr key={o.login} className={cn('grid cursor-pointer grid-cols-[minmax(0,1fr)_auto] gap-x-3 gap-y-1 px-4 py-3 transition-colors md:table-row md:p-0',
                      o.flagged ? 'md:bg-primary-soft md:hover:brightness-[.97]' : 'hover:bg-subtle')}
                      onClick={e => { if (!(e.target as HTMLElement).closest('a,button')) nav(href); }}>
                      <td className={cn(td, 'col-start-1')}>
                        <div className="flex min-w-0 items-center gap-3">
                          <span className="hidden size-9 shrink-0 place-items-center rounded-lg bg-muted text-muted-foreground md:grid"><User className="size-4" /></span>
                          <div className="min-w-0"><b className="block truncate font-semibold">{o.name}</b>
                            <small className="text-xs text-muted-foreground">{o.flagged ? <span className="font-semibold text-primary-ink">{t(o.flag_reason === 'disagree' ? 'q.flagDisagree' : 'q.flagRejects', { n: o.disagreed })}</span> : t(`role.${o.role || 'operator'}`)}</small></div>
                        </div>
                      </td>
                      {cell(t('q.th.decided'), nf.format(o.decided))}
                      {cell(t('q.th.rejected'), <><span className={cn(o.flagged && o.flag_reason === 'rejects' && 'font-semibold text-primary-ink')}>{pct(o.reject_rate)}</span> <span className="text-muted-foreground">· {nf.format(o.rejected)}</span></>)}
                      {cell(t('q.th.edited'), nf.format(o.edited), 'hidden md:table-cell')}
                      {cell(t('q.th.verified'), pct(o.coverage), 'hidden md:table-cell')}
                      {cell(t('q.th.disagreed'), o.disagreed ? <span className={cn(o.flagged && o.flag_reason === 'disagree' && 'font-semibold text-primary-ink')}>{nf.format(o.disagreed)} · {pct(o.disagree_rate, 1)}</span> : <span className="text-muted-foreground">0</span>)}
                      <td className={cn(td, 'col-start-2 row-span-4 row-start-1 self-center md:text-right')}>
                        <Button asChild size="xs" variant={o.flagged ? 'default' : 'secondary'}><Link to={href}>{t(o.flagged ? 'q.review' : 'act.open')}</Link></Button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </Card>

          <Card>
            <CardHeader><CardTitle>{t('q.loop')}</CardTitle><CardDescription>{t('q.loopLead')}</CardDescription></CardHeader>
            <CardContent className="pt-3">
              <ol className="grid gap-3.5 sm:grid-cols-3 xl:grid-cols-5">
                {steps.map(i => (
                  <li key={i} className="flex min-w-0 flex-col gap-1.5 border-t-2 border-foreground pt-3 last:border-primary">
                    <span className="text-xs font-semibold text-muted-foreground tabular-nums">{i}</span>
                    <b className="text-[15px] leading-tight font-semibold">{t(`q.s${i}`)}</b>
                    <span className="text-[13px] text-muted-foreground">{t(`q.s${i}d`)}</span>
                  </li>
                ))}
              </ol>
            </CardContent>
          </Card>
        </>
      )}
    </Page>
  );
}

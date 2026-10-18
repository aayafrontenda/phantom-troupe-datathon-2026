import { AlertTriangle, Check, ChevronRight, FileText, Play, ShieldCheck, Trash2, X } from 'lucide-react';
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { ApiError, api } from '../api';
import { useAuth } from '../auth';
import { refreshFeed } from '../components/events';
import { DecisionBar, DescriptionBlock, FrameStrip, labelClass, RuleBlock } from '../components/finding';
import { VideoInspectionCard } from '../components/inspection/VideoInspectionCard';
import { Crumb, EmptyState, Loading, Note, Page } from '../components/page';
import { Player, type Marker, type PlayerHandle } from '../components/Player';
import { Button } from '../components/ui/button';
import { Card, cardClass } from '../components/ui/card';
import { Ticks } from '../components/ui/state-line';
import { useUploads } from '../components/uploads';
import { useI18n } from '../i18n';
import { cn } from '../lib/utils';
import type { Finding, FindingBrief, Job } from '../types';
import { keyFrame, tc, useAgo, useUi } from '../ui';
import { reportUrl } from './Checks';

const VERDICT = {
  bad: { box: 'border-transparent bg-primary-soft', icon: 'bg-card text-primary-ink' },
  ok: { box: 'border-transparent bg-success-soft', icon: 'bg-card text-success' },
  fail: { box: 'border-transparent bg-destructive-soft', icon: 'bg-card text-destructive' },
  done: { box: 'border-border bg-card', icon: 'bg-success-soft text-success' },
  info: { box: 'border-transparent bg-info-soft', icon: 'bg-card text-info' },
};
export function Verdict({ tone, icon, title, text, aside }: { tone: keyof typeof VERDICT; icon: ReactNode; title: ReactNode; text: ReactNode; aside?: ReactNode }) {
  return (
    <div className={cn('flex flex-wrap items-center gap-[18px] rounded-xl border p-[18px] sm:flex-nowrap sm:px-6 sm:py-5', VERDICT[tone].box)}>
      <div className="flex min-w-0 flex-1 items-center gap-[18px]">
        <span className={cn('grid size-11 shrink-0 place-items-center rounded-[10px] [&_svg]:size-[22px]', VERDICT[tone].icon)}>{icon}</span>
        <div className="min-w-0">
          <h2 className="text-[21px] font-semibold tracking-tight">{title}</h2>
          <p className="mt-0.5 max-w-[70ch] text-[14.5px] text-muted-foreground">{text}</p>
        </div>
      </div>
      {aside && <div className="flex w-full flex-col items-start gap-2 text-left sm:ml-auto sm:w-auto sm:min-w-[180px] sm:items-end sm:text-right">{aside}</div>}
    </div>
  );
}

const sceneBtn = 'grid w-full grid-cols-[64px_minmax(0,1fr)_auto] gap-3 rounded-md px-2.5 py-2 text-left transition-colors hover:bg-subtle';
const sceneT = 'text-xs font-semibold tracking-wide text-primary-ink tabular-nums';

export default function CheckPage() {
  const { id = '' } = useParams();
  const { t, lang, typeName } = useI18n();
  const { toast, confirm } = useUi();
  const { can } = useAuth();
  const ago = useAgo();
  const nav = useNavigate();
  const { local } = useUploads();
  const [job, setJob] = useState<Job | null>(null);
  const [err, setErr] = useState<ApiError | null>(null);
  const [sel, setSel] = useState(0);
  const [time, setTime] = useState(0);
  const player = useRef<PlayerHandle>(null);
  const prevStatus = useRef<string | null>(null);

  const load = useCallback(async () => {
    try {
      const j = await api<Job>(`/ui/api/jobs/${id}`);
      setJob(j); setErr(null);
      return j;
    } catch (e) { setErr(e as ApiError); return null; }
  }, [id]);

  useEffect(() => { prevStatus.current = null; setSel(0); load(); }, [load]);

  // follow progress while processing (SSE + poll)
  useEffect(() => {
    if (!job || job.status !== 'processing') return;
    const poll = setInterval(load, 2000);
    let es: EventSource | null = null;
    try {
      es = new EventSource(`/ui/api/jobs/${id}/events`);
      es.addEventListener('progress', e => { const d = JSON.parse((e as MessageEvent).data); setJob(j => j ? { ...j, stage: d.stage, progress: d.progress } : j); });
      ['done', 'failed'].forEach(ev => es!.addEventListener(ev, () => load()));
    } catch { /* poll only */ }
    return () => { clearInterval(poll); es?.close(); };
  }, [job?.status, id, load, job]);

  useEffect(() => {
    if (!job) return;
    if (prevStatus.current === 'processing' && job.status === 'done') {
      toast(job.verdict === 'violation' ? t('toast.found', { n: job.violations?.length || 0 }) : t('toast.clear'));
      refreshFeed();
    }
    prevStatus.current = job.status;
  }, [job, t, toast]);

  // finding updates from other pages / users
  useEffect(() => {
    if (!job || job.status !== 'done') return;
    const es = new EventSource(`/ui/api/jobs/${id}/events`);
    es.addEventListener('finding_update', () => load());
    return () => es.close();
  }, [job?.status, id, load, job]);

  const viols = job?.violations || [];
  const findings = job?.findings || [];
  const dur = Math.max(0.1, job?.duration_sec || Number((job?.meta as { duration_sec?: number } | undefined)?.duration_sec) || 0.1);
  const fById = useMemo(() => Object.fromEntries(findings.map(f => [f.violation_index ?? -1, f])), [findings]);

  const onFindingChange = (nf: Finding) => {
    setJob(j => j ? { ...j, findings: (j.findings || []).map(f => f.id === nf.id ? { ...f, ...nf } : f) } : j);
    refreshFeed();
    const all = findings.map(f => f.id === nf.id ? nf : f);
    if (nf.decision && all.every(f => f.decision)) toast(t('toast.allReviewed'));
    else if (nf.decision) { const next = all.findIndex((f, k) => k > (nf.violation_index ?? -1) && !f.decision); if (next >= 0) select(next, true); }
  };

  // keyboard-driven selection jumps instantly; only pointer selection scrolls smoothly
  const select = useCallback((i: number, jump: boolean, smooth = true) => {
    setSel(i);
    document.querySelector(`[data-finding="${i}"]`)?.scrollIntoView({ behavior: smooth ? 'smooth' : 'auto', block: 'nearest' });
    if (jump && viols[i]) player.current?.seek(Math.max(0, viols[i].timecode_sec - 1), true);
  }, [viols]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement).closest('input,textarea,select') || document.querySelector('[role="dialog"]')) return;
      if (!job || job.status !== 'done') return;
      const n = viols.length;
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      // e.code, not e.key: shortcuts must work on the Russian and Kazakh layouts too
      if (e.code === 'Space') { e.preventDefault(); player.current?.toggle(); }
      else if (e.code === 'ArrowLeft') { e.preventDefault(); player.current?.seek(time - 1); }
      else if (e.code === 'ArrowRight') { e.preventDefault(); player.current?.seek(time + 1); }
      else if (!n) return;
      else if (e.code === 'KeyN') select((sel + 1) % n, true, false);
      else if (e.code === 'KeyP') select((sel - 1 + n) % n, true, false);
      else if ((e.code === 'KeyC' || e.code === 'KeyR') && can('operator')) {
        const f = fById[sel];
        if (f && !f.decision) decideByKey(f, e.code === 'KeyC' ? 'confirm' : 'reject');
      }
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [job, viols, sel, time, select, fById, can]);

  async function decideByKey(f: FindingBrief, decision: 'confirm' | 'reject') {
    try { onFindingChange(await api<Finding>(`/ui/api/findings/${f.id}/decision`, { method: 'POST', json: { decision, comment: null } })); }
    catch (e) { toast(t('toast.saveErr', { e: (e as Error).message }), 'err'); }
  }

  const onTime = (tt: number) => {
    setTime(tt);
    const near = viols.findIndex(v => tt >= v.timecode_sec - 1 && tt <= v.timecode_sec + 2);
    if (near >= 0 && near !== sel) setSel(near);
  };

  const del = async () => {
    if (!job) return;
    const active = job.status === 'processing';
    const ok = await confirm(t(active ? 'del.cancelTitle' : 'del.deleteTitle'), <><b>{job.filename}</b><br />{t(active ? 'del.cancelText' : 'del.deleteText')}</>, t(active ? 'del.cancelBtn' : 'act.delete'));
    if (!ok) return;
    try { await api(`/ui/api/jobs/${id}`, { method: 'DELETE' }); toast(t(active ? 'del.cancelled' : 'del.deleted')); nav('/checks'); }
    catch (e) { toast((e as Error).message, 'err'); }
  };

  if (err) {
    return (
      <Page><Crumb to="/checks">{t('crumb')}</Crumb>
        <Card><EmptyState title={t(err.status === 404 ? 'chk.gone' : 'chk.loadErr')}>{err.status === 404 ? t('chk.goneHint') : err.message}</EmptyState></Card></Page>
    );
  }
  if (!job) return <Page><Loading /></Page>;

  const meta = [job.duration_sec ? t('meta.long', { t: tc(job.duration_sec) }) : '', job.created_at ? t('meta.uploaded', { ago: ago(job.created_at) }) : '',
    job.created_by ? t('meta.by', { n: job.created_by }) : '', job.processing_sec ? t('meta.analysed', { s: job.processing_sec }) : ''].filter(Boolean);
  const head = (extra?: ReactNode) => (
    <>
      <Crumb to="/checks">{t('crumb')}</Crumb>
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <h1 className="text-[26px] font-semibold tracking-tight break-words">{job.filename}</h1>
          <div className="mt-1.5 flex flex-wrap items-center gap-x-[18px] gap-y-1 text-[13.5px] text-muted-foreground">{meta.map(m => <span key={m}>{m}</span>)}</div>
        </div>
        <div className="flex flex-wrap gap-2">{extra}{can('operator') && job.status !== 'processing' && <Button variant="destructive" onClick={del}><Trash2 />{t('act.delete')}</Button>}</div>
      </div>
    </>
  );

  if (job.status === 'processing') {
    return (
      <Page>{head()}
        <VideoInspectionCard job={job} onCancel={can('operator') ? del : undefined}>
          {local[id] && (
            <div className="border-t border-border/60 p-4 sm:px-5">
              <p className="mb-2 text-xs text-muted-foreground">{t('proc.preview')}</p>
              <video src={local[id]} controls muted playsInline className="max-h-[360px] w-full rounded-lg bg-video" />
            </div>
          )}
        </VideoInspectionCard>
      </Page>
    );
  }

  const n = viols.length, failed = job.status === 'failed';
  const decided = findings.filter(f => f.decision).length;
  const confirmed = findings.filter(f => f.decision === 'confirm').length;
  let verdict: ReactNode;
  if (failed) verdict = <Verdict tone="fail" icon={<X />} title={t('v.failTitle')} text={t('v.failText', { err: job.error || t('v.unknownErr') })} />;
  else if (n) verdict = (
    <Verdict tone={decided === n ? 'done' : 'bad'} icon={decided === n ? <Check /> : <AlertTriangle />}
      title={t(decided === n ? 'v.doneTitle' : 'v.badTitle')} text={decided === n ? t('v.doneText', { c: confirmed, d: decided - confirmed }) : t('v.badText', { n })}
      aside={<>
        <b className="text-[13.5px] font-semibold text-foreground">{t('rev.progress', { a: decided, b: n })}</b>
        <Ticks className="justify-start sm:justify-end" states={viols.map((_, i) => fById[i]?.decision === 'confirm' ? 'c' : fById[i]?.decision ? 'd' : '')} />
      </>} />
  );
  else verdict = <Verdict tone="ok" icon={<ShieldCheck />} title={t('v.okTitle')} text={t('v.okText')} />;

  const markers: Marker[] = viols.map((v, i) => ({ t: v.timecode_sec, label: String(i + 1), title: `${typeName(v.type_code, v.type)} · ${tc(v.timecode_sec)}`,
    state: fById[i]?.decision === 'confirm' ? 'confirm' : fById[i]?.decision ? 'done' : '', thumb: keyFrame(v.evidence_frames, v.timecode_sec) }));
  const poster = viols[sel]?.evidence_frames?.[0] ? `data:image/jpeg;base64,${viols[sel].evidence_frames[0].image_base64}` : undefined;
  const src = local[id] || (job.video_available !== false ? `/ui/api/jobs/${id}/video` : null);
  const scenes = ((job.meta as { scenes?: { t: number; scene: string }[] } | undefined)?.scenes) || [];

  return (
    <Page>
      {head(job.status === 'done' ? (
        <Button asChild variant={n && decided === n ? 'default' : 'secondary'}><a href={reportUrl(id, lang)} target="_blank" rel="noopener"><FileText />{t('act.report')}</a></Button>
      ) : null)}
      {verdict}
      {job.partial && <Note className="-mt-2">{t('v.partial')}</Note>}
      <div className="grid items-start gap-5 xl:grid-cols-[minmax(280px,380px)_minmax(0,1fr)]">
        <Card className="overflow-visible p-3 xl:sticky xl:top-0">
          <Player ref={player} src={src} poster={poster} duration={dur} markers={markers} selected={sel} onSelect={i => select(i, true)} onTime={onTime}
            initialT={n ? Math.max(0, viols[0].timecode_sec - 1) : 0}
            hint={n ? <span dangerouslySetInnerHTML={{ __html: t('keys') }} /> : null} />
        </Card>
        <div className="min-w-0">
          <div className="flex flex-col gap-3.5">
            {!n ? (
              <Card className="p-7">
                <h3 className="mb-1.5 text-lg font-semibold">{t(failed ? 'c.noResult' : 'c.whatChecked')}</h3>
                <p className="text-muted-foreground">{failed ? '' : scenes.length ? t('c.scenes', { n: scenes.length }) : t('c.scanned')}</p>
                {scenes.length > 0 && (
                  <ul className="mt-3.5 flex flex-col gap-px">
                    {scenes.map((s, i) => <li key={i}><button type="button" className={sceneBtn} onClick={() => player.current?.seek(s.t, true)}><span className={sceneT}>{tc(s.t)}</span><span lang="ru">{s.scene}</span></button></li>)}
                  </ul>
                )}
              </Card>
            ) : viols.map((v, i) => {
              const f: FindingBrief | undefined = fById[i];
              const on = i === sel;
              return (
                <article key={i} data-finding={i}
                  className={cn(cardClass, 'transition-[border-color,box-shadow] duration-200', on && 'border-foreground ring-1 ring-foreground')}
                  onClick={e => { if (!(e.target as HTMLElement).closest('button,a,summary,textarea,input')) select(i, true); }}>
                    <div className="flex flex-wrap items-center gap-3 border-b border-border px-4 py-3.5 sm:px-5 sm:py-4">
                      <span className={cn('grid h-7 min-w-7 shrink-0 place-items-center rounded-md px-1.5 text-[13px] font-semibold tabular-nums',
                        f?.decision === 'confirm' ? 'bg-destructive text-white' : f?.decision ? 'bg-muted text-faint' : 'bg-primary text-white')}>{i + 1}</span>
                      <h3 className="flex-[1_1_60%] text-[17px] font-semibold leading-tight sm:text-lg">{typeName(v.type_code, v.type)}</h3>
                      <div className="ml-auto flex shrink-0 items-center gap-1.5">
                        {f && <Button asChild size="xs" variant="ghost"><Link to={`/findings/${f.id}`} onClick={e => e.stopPropagation()}>{t('ev.open')}</Link></Button>}
                        <Button size="sm" variant="secondary" onClick={e => { e.stopPropagation(); select(i, false); player.current?.seek(Math.max(0, v.timecode_sec - 1), true); }}>
                          <Play className="fill-current" /><span className="tracking-wide tabular-nums">{tc(v.timecode_sec)}</span>
                        </Button>
                      </div>
                    </div>
                    <div className="grid gap-5 px-4 py-[18px] sm:grid-cols-[auto_minmax(0,1fr)] sm:px-5">
                      <FrameStrip frames={v.evidence_frames || []} keyT={v.timecode_sec} caption={job.filename || ''} />
                      <div className="min-w-0">
                        {f ? <DescriptionBlock f={f} editable={can('operator')} onChange={onFindingChange} />
                          : <><p className={labelClass}>{t('f.seen')}</p><p className="max-w-[68ch] text-[15px] leading-relaxed" lang="ru">{v.description}</p></>}
                        <RuleBlock rule={v.rule || {}} typeCode={v.type_code} open={i === sel} clipUrl={(job.clips || []).includes(i) ? `/ui/api/jobs/${id}/violations/${i}/clip.mp4` : null} />
                      </div>
                    </div>
                    {f && <DecisionBar f={f} editable={can('operator')} onChange={onFindingChange} />}
                </article>
              );
            })}
          </div>
          <TechDetails job={job} dur={dur} onSeek={tt => player.current?.seek(tt, true)} />
        </div>
      </div>
    </Page>
  );
}

function TechDetails({ job, dur, onSeek }: { job: Job; dur: number; onSeek: (t: number) => void }) {
  const { t } = useI18n();
  const m = (job.meta || {}) as Record<string, unknown>;
  const tl = job.timeline && Array.isArray(job.timeline.t) ? job.timeline : null;
  const lanes = ['people', 'screen_on', 'phone', 'drink', 'bag'].filter(k => tl && Array.isArray(tl[k]));
  const lane = (k: string) => {
    const vals = tl![k];
    if (k === 'people') {
      let d = 'M0 16';
      tl!.t.forEach((tt, i) => { d += ` L${(tt / dur * 1000).toFixed(1)} ${(16 - Math.min(3, vals[i] || 0) / 3 * 13).toFixed(1)}`; });
      return <path d={`${d} L1000 16 Z`} className="fill-info/25 stroke-info" vectorEffect="non-scaling-stroke" />;
    }
    const rects: ReactNode[] = []; let start: number | null = null;
    const push = (a: number, b: number) => rects.push(<rect key={rects.length} x={(a / dur * 1000).toFixed(1)} y="3" width={Math.max(2, (b - a) / dur * 1000).toFixed(1)} height="10" rx="2" className="fill-warning" />);
    tl!.t.forEach((tt, i) => { if (vals[i] && start === null) start = tt; if (!vals[i] && start !== null) { push(start, tt); start = null; } });
    if (start !== null) push(start, dur);
    return <>{rects}</>;
  };
  const scenes = (m.scenes as { t: number; scene: string }[] | undefined) || [];
  const kv: [string, ReactNode][] = [
    [t('kv.analyzer'), job.analyzer || '-'], [t('kv.frames'), String(m.frames ?? '-')],
    [t('kv.moments'), ((m.candidates as unknown[]) || []).length || '-'], [t('kv.calls'), String(m.vlm_calls ?? '-')],
    [t('kv.time'), `${job.processing_sec ?? '-'} ${t('sec')}`], [t('kv.id'), job.job_id],
  ];
  return (
    <details className="group mt-5 border-t border-border">
      <summary className="flex cursor-pointer list-none items-center gap-1.5 py-3.5 text-sm font-medium text-muted-foreground transition-colors hover:text-foreground [&::-webkit-details-marker]:hidden">
        <ChevronRight className="size-[15px] transition-transform duration-200 group-open:rotate-90" />{t('tech.title')}
      </summary>
      <div className="flex flex-col gap-4 pb-4">
        <div className="grid grid-cols-[repeat(auto-fill,minmax(160px,1fr))] gap-px overflow-hidden rounded-[10px] border border-border bg-border">
          {kv.map(([k, v]) => <div key={k} className="bg-card px-3 py-2.5 text-xs text-muted-foreground">{k}<b className="block truncate text-[15px] font-semibold text-foreground tabular-nums">{v}</b></div>)}
        </div>
        {lanes.length > 0 && (
          <div><p className={labelClass}>{t('tech.signals')}</p>
            <div className="flex flex-col gap-1">
              {lanes.map(k => (
                <div key={k} className="grid grid-cols-[110px_minmax(0,1fr)] items-center gap-2">
                  <span className="text-xs text-muted-foreground">{t(`lane.${k}`)}</span>
                  <div className="relative h-4 rounded-[3px] bg-subtle"><svg viewBox="0 0 1000 16" preserveAspectRatio="none" className="absolute inset-0 h-full w-full">{lane(k)}</svg></div>
                </div>
              ))}
            </div>
          </div>
        )}
        {scenes.length > 0 && (
          <div><p className={labelClass}>{t('tech.saw')}</p>
            <ul className="flex flex-col gap-px">{scenes.map((s, i) => <li key={i}><button type="button" className={sceneBtn} onClick={() => onSeek(s.t)}><span className={sceneT}>{tc(s.t)}</span><span lang="ru">{s.scene}</span></button></li>)}</ul>
          </div>
        )}
        {job.warning && <div className="text-[13px] text-muted-foreground">{job.warning}</div>}
      </div>
    </details>
  );
}

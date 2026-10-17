import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { ApiError, api } from '../api';
import { useAuth } from '../auth';
import { refreshFeed } from '../components/events';
import { DecisionBar, DescriptionBlock, FrameStrip, RuleBlock } from '../components/finding';
import { Player, type Marker, type PlayerHandle } from '../components/Player';
import { useUploads } from '../components/uploads';
import { useI18n } from '../i18n';
import type { Finding, FindingBrief, Job } from '../types';
import { Icon, tc, useAgo, useUi } from '../ui';
import { reportUrl } from './Checks';

const STEPS = ['queued', 'frames', 'detection', 'vlm', 'report', 'done'];

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

  const select = useCallback((i: number, jump: boolean) => {
    setSel(i);
    document.querySelector(`.find[data-i="${i}"]`)?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    if (jump && viols[i]) player.current?.seek(Math.max(0, viols[i].timecode_sec - 1), true);
  }, [viols]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement).closest('input,textarea,select') || document.querySelector('.modal')) return;
      if (!job || job.status !== 'done') return;
      const n = viols.length;
      if (e.key === ' ') { e.preventDefault(); player.current?.toggle(); }
      else if (e.key === 'ArrowLeft') { e.preventDefault(); player.current?.seek(time - 1); }
      else if (e.key === 'ArrowRight') { e.preventDefault(); player.current?.seek(time + 1); }
      else if (!n) return;
      else if (e.key === 'n' || e.key === 'N') select((sel + 1) % n, true);
      else if (e.key === 'p' || e.key === 'P') select((sel - 1 + n) % n, true);
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [job, viols, sel, time, select]);

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
    return <div className="page"><Link className="crumb" to="/checks"><Icon id="back" />{t('crumb')}</Link>
      <div className="card empty"><b>{t(err.status === 404 ? 'chk.gone' : 'chk.loadErr')}</b>{err.status === 404 ? t('chk.goneHint') : err.message}</div></div>;
  }
  if (!job) return <div className="page"><p className="loading">{t('loading')}</p></div>;

  const meta = [job.duration_sec ? t('meta.long', { t: tc(job.duration_sec) }) : '', job.created_at ? t('meta.uploaded', { ago: ago(job.created_at) }) : '',
    job.created_by ? t('meta.by', { n: job.created_by }) : '', job.processing_sec ? t('meta.analysed', { s: job.processing_sec }) : ''].filter(Boolean).join(' · ');
  const head = (extra?: React.ReactNode) => (
    <>
      <Link className="crumb" to="/checks"><Icon id="back" />{t('crumb')}</Link>
      <div className="check-head"><div><h1>{job.filename}</h1><div className="meta">{meta}</div></div>
        <div className="acts">{extra}{can('operator') && <button className="btn danger" onClick={del}><Icon id="trash" />{t(job.status === 'processing' ? 'del.cancelBtn' : 'act.delete')}</button>}</div></div>
    </>
  );

  if (job.status === 'processing') {
    const stage = job.stage === 'started' || job.stage === 'retry' ? 'queued' : (job.stage || 'queued');
    const ci = Math.max(0, STEPS.indexOf(stage));
    const pct = Math.round((job.progress || 0) * 100);
    return (
      <div className="page">{head()}
        <div className="card proc">
          <h2>{stage === 'queued' ? (job.queue_position ? t('proc.queue', { n: job.queue_position }) : t('proc.starting')) : t('proc.title')}</h2>
          <p className="muted">{job.stage === 'retry' ? t('proc.retry') : t('proc.sub')}</p>
          <div className="bigbar"><i style={{ width: `${Math.max(3, pct)}%` }} /></div>
          <div className="steps">{STEPS.map((k, i) => <div key={k} className={`step ${i < ci ? 'done' : i === ci ? 'now' : ''}`}><b>{t(`step.${k}`)}</b><span>{i === ci && i > 0 ? `${pct}%` : ''}</span></div>)}</div>
          <div className="proc-foot"><span>{job.eta_sec != null ? t('proc.eta', { s: job.eta_sec }) : ''}</span><span className="sp" />{local[id] && <span>{t('proc.preview')}</span>}</div>
          {local[id] && <video src={local[id]} controls muted playsInline style={{ width: '100%', maxHeight: 360, borderRadius: 16, background: 'var(--video)', marginTop: 12 }} />}
        </div>
      </div>
    );
  }

  const n = viols.length, failed = job.status === 'failed';
  const decided = findings.filter(f => f.decision).length;
  const confirmed = findings.filter(f => f.decision === 'confirm').length;
  let verdict: React.ReactNode;
  if (failed) verdict = <div className="verdict fail"><span className="vi"><Icon id="x" /></span><div><h2>{t('v.failTitle')}</h2><p>{t('v.failText', { err: job.error || t('v.unknownErr') })}</p></div></div>;
  else if (n) verdict = (
    <div className={`verdict ${decided === n ? 'done' : 'bad'}`}><span className="vi"><Icon id={decided === n ? 'check' : 'alert'} /></span>
      <div><h2>{t(decided === n ? 'v.doneTitle' : 'v.badTitle')}</h2><p>{decided === n ? t('v.doneText', { c: confirmed, d: decided - confirmed }) : t('v.badText', { n })}</p></div>
      <div className="rv"><b>{t('rev.progress', { a: decided, b: n })}</b><div className="minibar"><i style={{ width: `${decided / n * 100}%` }} /></div></div></div>
  );
  else verdict = <div className="verdict ok"><span className="vi"><Icon id="shield" /></span><div><h2>{t('v.okTitle')}</h2><p>{t('v.okText')}</p></div></div>;

  const markers: Marker[] = viols.map((v, i) => ({ t: v.timecode_sec, label: String(i + 1), title: `${typeName(v.type_code, v.type)} · ${tc(v.timecode_sec)}`,
    state: fById[i]?.decision === 'confirm' ? 'confirm' : fById[i]?.decision ? 'done' : '' }));
  const poster = viols[sel]?.evidence_frames?.[0] ? `data:image/jpeg;base64,${viols[sel].evidence_frames[0].image_base64}` : undefined;
  const src = local[id] || (job.video_available !== false ? `/ui/api/jobs/${id}/video` : null);
  const scenes = ((job.meta as { scenes?: { t: number; scene: string }[] } | undefined)?.scenes) || [];

  return (
    <div className="page">
      {head(job.status === 'done' ? <a className={`btn ${n && decided === n ? 'primary' : ''}`} href={reportUrl(id, lang)} target="_blank" rel="noopener"><Icon id="doc" />{t('act.report')}</a> : null)}
      {verdict}
      {job.partial && <div className="note"><Icon id="alert" /><span>{t('v.partial')}</span></div>}
      <div className="layout">
        <div className="card player-card">
          <Player ref={player} src={src} poster={poster} duration={dur} markers={markers} selected={sel} onSelect={i => select(i, true)} onTime={onTime}
            initialT={n ? Math.max(0, viols[0].timecode_sec - 1) : 0}
            hint={n ? <span dangerouslySetInnerHTML={{ __html: t('keys') }} /> : null} />
        </div>
        <div>
          <div className="findings">
            {!n ? (
              <div className="card clear-card"><h3>{t(failed ? 'c.noResult' : 'c.whatChecked')}</h3>
                <p className="muted">{failed ? '' : scenes.length ? t('c.scenes', { n: scenes.length }) : t('c.scanned')}</p>
                {scenes.length > 0 && <ul className="scenes">{scenes.map((s, i) => <li key={i}><button onClick={() => player.current?.seek(s.t, true)}><span className="t num">{tc(s.t)}</span><span lang="ru">{s.scene}</span></button></li>)}</ul>}
              </div>
            ) : viols.map((v, i) => {
              const f: FindingBrief | undefined = fById[i];
              return (
                <article key={i} data-i={i} className={`card find ${i === sel ? 'on' : ''} ${f?.decision === 'confirm' ? 'confirm' : f?.decision ? 'reject' : ''}`}
                  onClick={e => { if (!(e.target as HTMLElement).closest('button,a,summary,textarea,input')) select(i, true); }}>
                  <div className="find-h"><span className="num">{i + 1}</span><h3>{typeName(v.type_code, v.type)}</h3>
                    <div className="tc">{f && <Link className="btn xs ghost" to={`/findings/${f.id}`} onClick={e => e.stopPropagation()}>{t('ev.open')}</Link>}
                      <button className="btn sm" onClick={e => { e.stopPropagation(); select(i, false); player.current?.seek(Math.max(0, v.timecode_sec - 1), true); }}><Icon id="play" /><span className="num">{tc(v.timecode_sec)}</span></button></div></div>
                  <div className="find-b">
                    <FrameStrip frames={v.evidence_frames || []} keyT={v.timecode_sec} caption={job.filename || ''} />
                    <div>
                      {f ? <DescriptionBlock f={f} editable={can('operator')} onChange={onFindingChange} />
                        : <><p className="label">{t('f.seen')}</p><p className="desc" lang="ru">{v.description}</p></>}
                      <RuleBlock rule={v.rule || {}} typeCode={v.type_code} clipUrl={(job.clips || []).includes(i) ? `/ui/api/jobs/${id}/violations/${i}/clip.mp4` : null} />
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
    </div>
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
      return <path d={`${d} L1000 16 Z`} fill="var(--info)" fillOpacity=".25" stroke="var(--info)" vectorEffect="non-scaling-stroke" />;
    }
    const rects: React.ReactNode[] = []; let start: number | null = null;
    const push = (a: number, b: number) => rects.push(<rect key={rects.length} x={(a / dur * 1000).toFixed(1)} y="3" width={Math.max(2, (b - a) / dur * 1000).toFixed(1)} height="10" rx="2" fill="var(--warn)" />);
    tl!.t.forEach((tt, i) => { if (vals[i] && start === null) start = tt; if (!vals[i] && start !== null) { push(start, tt); start = null; } });
    if (start !== null) push(start, dur);
    return <>{rects}</>;
  };
  const scenes = (m.scenes as { t: number; scene: string }[] | undefined) || [];
  return (
    <details className="tech card">
      <summary><Icon id="chev" />{t('tech.title')}</summary>
      <div className="tech-body">
        <div className="kv">
          <div>{t('kv.analyzer')}<b>{job.analyzer || '—'}</b></div><div>{t('kv.frames')}<b>{String(m.frames ?? '—')}</b></div>
          <div>{t('kv.moments')}<b>{((m.candidates as unknown[]) || []).length || '—'}</b></div><div>{t('kv.calls')}<b>{String(m.vlm_calls ?? '—')}</b></div>
          <div>{t('kv.time')}<b>{job.processing_sec ?? '—'} {t('sec')}</b></div><div>{t('kv.id')}<b>{job.job_id}</b></div>
        </div>
        {lanes.length > 0 && <div><p className="label">{t('tech.signals')}</p><div className="lanes">{lanes.map(k => <div key={k} className="lrow"><span className="lab">{t(`lane.${k}`)}</span><div className="track"><svg viewBox="0 0 1000 16" preserveAspectRatio="none">{lane(k)}</svg></div></div>)}</div></div>}
        {scenes.length > 0 && <div><p className="label">{t('tech.saw')}</p><ul className="scenes">{scenes.map((s, i) => <li key={i}><button onClick={() => onSeek(s.t)}><span className="t num">{tc(s.t)}</span><span lang="ru">{s.scene}</span></button></li>)}</ul></div>}
        {job.warning && <div className="muted small">{job.warning}</div>}
      </div>
    </details>
  );
}

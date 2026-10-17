import { useCallback, useEffect, useRef, useState } from 'react';
import { Link, useParams, useSearchParams } from 'react-router-dom';
import { ApiError, api } from '../api';
import { useAuth } from '../auth';
import { refreshFeed } from '../components/events';
import { DecisionBar, DescriptionBlock, FrameStrip, RuleBlock, VerifyBlock } from '../components/finding';
import { Player, SequencePlayer, type Marker, type PlayerHandle } from '../components/Player';
import { useI18n } from '../i18n';
import type { Finding, HistoryItem } from '../types';
import { fmtDate, Icon, keyFrame, serial, tc, useAgo } from '../ui';

export default function FindingPage() {
  const { id = '' } = useParams();
  const [sp] = useSearchParams();
  const { t, typeName, locale } = useI18n();
  const { can } = useAuth();
  const ago = useAgo();
  const [f, setF] = useState<Finding | null>(null);
  const [err, setErr] = useState<ApiError | null>(null);
  const player = useRef<PlayerHandle>(null);

  const load = useCallback(async () => {
    try { setF(await api<Finding>(`/ui/api/findings/${id}`)); setErr(null); }
    catch (e) { setErr(e as ApiError); }
  }, [id]);
  useEffect(() => { load(); }, [load]);

  const onChange = (nf: Finding) => { setF(x => x ? { ...x, ...nf, frames: x.frames, sequence: x.sequence, siblings: x.siblings, history: nf.history || x.history } : nf); load(); refreshFeed(); };

  if (err) return <div className="page"><Link className="crumb" to="/live"><Icon id="back" />{t('fd.crumbLive')}</Link><div className="card empty"><b>{t('fd.gone')}</b>{err.message}</div></div>;
  if (!f) return <div className="page"><p className="loading">{t('loading')}</p></div>;

  const from = sp.get('from');
  const back = from === 'review' ? { to: '/review', label: t('fd.crumbReview') } : from === 'check' && f.job_id ? { to: `/checks/${f.job_id}`, label: f.filename || t('fd.upload') } : { to: '/live', label: t('fd.crumbLive') };
  const where = f.source === 'camera' ? f.camera_name || f.camera_id : f.filename;
  const marker: Marker[] = f.t_sec != null ? [{ t: f.t_sec, label: '!', title: typeName(f.type_code, f.type_name), state: f.decision === 'confirm' ? 'confirm' : f.decision ? 'done' : '', thumb: keyFrame(f.frames, f.t_sec) }] : [];
  const sib = f.siblings || [];
  const pos = sib.findIndex(s => s.id === f.id);
  const prev = pos > 0 ? sib[pos - 1] : null, next = pos >= 0 && pos < sib.length - 1 ? sib[pos + 1] : null;

  let media: React.ReactNode;
  if (f.source === 'upload') {
    media = <Player ref={player} src={f.video_url} poster={f.frames[0] ? `data:image/jpeg;base64,${f.frames[0].image_base64}` : undefined} duration={Math.max(0.1, f.duration_sec || 0.1)}
      markers={marker} selected={0} initialT={Math.max(0, (f.t_sec || 0) - 1)} />;
  } else if (f.clip_url) {
    media = <Player ref={player} src={f.clip_url} duration={Math.max(0.1, f.duration_sec || 0.1)} markers={marker} selected={0} initialT={Math.max(0, (f.t_sec || 0) - 1)} wide />;
  } else if (f.sequence?.length) {
    media = <SequencePlayer ref={player} frames={f.sequence} markers={marker} initialT={Math.max(0, (f.t_sec || 0) - 1)} wide />;
  } else {
    media = <Player src={null} duration={1} poster={f.frames[0] ? `data:image/jpeg;base64,${f.frames[0].image_base64}` : undefined} removedTitle={t('p.noClip')} removedHint={t('p.noClipHint')} wide />;
  }

  return (
    <div className="page wide">
      <Link className="crumb" to={back.to}><Icon id="back" />{back.label}</Link>
      <div className="check-head">
        <div>
          <h1>{typeName(f.type_code, f.type_name)}</h1>
          <div className="meta">
            <span className="pill neutral xs"><Icon id={f.source === 'camera' ? 'cam' : 'film'} />{t(f.source === 'camera' ? 'fd.camera' : 'fd.upload')}</span>{' '}
            <span>{where}</span>{f.t_sec != null && <span className="num">{t('ev.at', { t: tc(f.t_sec) })}</span>}<span>{ago(f.created_at)}</span><span className="serial">№ {serial(f.id)}</span>
          </div>
        </div>
        <div className="acts">
          {f.job_id && <Link className="btn" to={`/checks/${f.job_id}`}><Icon id="film" />{t('fd.openCheck')}</Link>}
          {prev && <Link className="btn" to={`/findings/${prev.id}?from=${from || ''}`}><Icon id="back" />{t('fd.prev')}</Link>}
          {next && <Link className="btn" to={`/findings/${next.id}?from=${from || ''}`}>{t('fd.next')}<Icon id="chev" /></Link>}
        </div>
      </div>

      <div className={`verdict ${f.decision === 'confirm' ? 'bad' : f.decision === 'reject' ? 'info' : 'bad'}`}>
        <span className="vi"><Icon id={f.decision === 'confirm' ? 'alert' : f.decision === 'reject' ? 'check' : 'alert'} /></span>
        <div>
          <h2>{f.decision === 'confirm' ? t('f.confirmed') : f.decision === 'reject' ? t('f.notViolation') : t('v.badTitle')}</h2>
          <p>{f.decision ? `${t('f.decidedBy', { n: f.decided_by_name || f.decided_by || '' })}${f.decided_at ? `, ${fmtDate(f.decided_at, locale)}` : ''}` : t('f.question')}</p>
        </div>
        <div className="rv">
          {f.verified ? <span className={`pill ${f.verify_result === 'agree' ? 'ok' : 'bad'}`}><Icon id={f.verify_result === 'agree' ? 'check' : 'flag'} />{t('fd.verifiedBy', { n: f.verified_by_name || f.verified_by || '' })}</span>
            : f.decision ? <span className="pill neutral">{t('fd.notVerified')}</span> : null}
        </div>
      </div>

      <div className="layout">
        <div className="side">
          <div className="card player-card" style={{ position: 'static', padding: 14 }}>{media}</div>
          <VerifyBlock f={f} onChange={onChange} />
          <div className="card">
            <h3>{t('fd.history')}</h3>
            <History items={f.history} />
          </div>
          {f.alert && (
            <div className="card">
              <h3>{t('fd.alert')}</h3>
              <div className="row"><span className={`pill ${f.alert.severity === 'critical' ? 'bad' : f.alert.severity === 'high' ? 'warn' : 'neutral'}`}>{t(`sev.${f.alert.severity}`)}</span>
                <span className="muted small">{t(f.alert.state === 'open' ? 'ev.pending' : f.alert.state === 'false_positive' ? 'ev.markedFalse' : f.alert.state === 'resolved' ? 'ev.resolved' : 'ev.acked')}{f.alert.count > 1 ? `, ×${f.alert.count}` : ''}{f.alert.escalation_level ? `, ${t('ev.escalated')}` : ''}</span></div>
            </div>
          )}
        </div>
        <div className="side">
          <article className={`card find on ${f.decision === 'confirm' ? 'confirm' : f.decision ? 'reject' : ''}`}>
            <div className="find-h"><span className="num">!</span><h3>{typeName(f.type_code, f.type_name)}</h3>
              {f.t_sec != null && <div className="tc"><button className="btn sm" onClick={() => player.current?.seek(Math.max(0, f.t_sec! - 1), true)}><Icon id="play" /><span className="num">{tc(f.t_sec)}</span></button></div>}</div>
            <div className="find-b">
              <FrameStrip frames={f.frames} keyT={f.t_sec} caption={where || ''} />
              <div>
                <DescriptionBlock f={f} editable={can('operator') && !f.verified} onChange={onChange} />
                <RuleBlock rule={f.rule || {}} typeCode={f.type_code} clipUrl={f.clip_url} />
              </div>
            </div>
            <DecisionBar f={f} editable={can('operator') && !f.verified} onChange={onChange} />
          </article>
          {sib.length > 1 && (
            <div className="card" style={{ padding: 20 }}>
              <h3>{t('fd.others')}</h3>
              <ul className="scenes" style={{ marginTop: 0 }}>
                {sib.map(s => <li key={s.id}><Link to={`/findings/${s.id}?from=${from || ''}`} style={{ textDecoration: 'none', color: 'inherit' }}>
                  <button style={s.id === f.id ? { background: 'var(--surface-3)' } : undefined}><span className="t num">{tc(s.t_sec)}</span><span>{typeName(undefined, s.type_name)}</span>{s.decision ? <span className="muted small sc-d">{t(s.decision === 'confirm' ? 'f.confirmed' : 'f.notViolation')}</span> : null}</button></Link></li>)}
              </ul>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export function History({ items }: { items: HistoryItem[] }) {
  const { t, locale } = useI18n();
  if (!items?.length) return <p className="muted small">{t('fd.noHistory')}</p>;
  const label = (h: HistoryItem) => {
    const p = h.payload || {};
    const d = (v: unknown) => v === 'confirm' ? t('f.confirmed') : v === 'reject' ? t('f.notViolation') : v === 'agree' ? t('fd.agree') : v === 'disagree' ? t('fd.disagree') : String(v ?? '');
    switch (h.action) {
      case 'edit': return t('h.edit');
      case 'decide': return t('h.decide', { d: d(p.after) });
      case 'undo': return t('h.undo');
      case 'verify': return t('h.verify', { d: d(p.result) });
      case 'unverify': return t('h.unverify');
      default: return h.action;
    }
  };
  const cls = (h: HistoryItem) => h.action === 'verify' ? (h.payload?.result === 'agree' ? 'ok' : 'bad') : h.action === 'decide' ? (h.payload?.after === 'confirm' ? 'bad' : 'ok') : h.action === 'edit' ? 'info' : '';
  const icon = (h: HistoryItem) => h.action === 'edit' ? 'edit' : h.action === 'verify' ? 'eye' : h.action === 'decide' ? 'check' : 'undo';
  return (
    <ul className="timeline">
      {items.slice().reverse().map(h => (
        <li key={h.id}><span className={`dot ${cls(h)}`}><Icon id={icon(h)} /></span>
          <div><b>{h.actor_name || h.actor}</b> {label(h)}{h.payload?.comment ? <> - «{String(h.payload.comment)}»</> : null}
            {h.action === 'edit' && h.payload?.after ? <div className="desc-box op small" style={{ marginTop: 6 }}>{String(h.payload.after)}</div> : null}
            <small>{fmtDate(h.created_at, locale)}, {t(`role.${h.actor_role}`) !== `role.${h.actor_role}` ? t(`role.${h.actor_role}`) : h.actor_role}</small></div></li>
      ))}
    </ul>
  );
}

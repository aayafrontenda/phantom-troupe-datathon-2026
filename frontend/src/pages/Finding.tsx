import { AlertTriangle, Check, ChevronLeft, ChevronRight, Eye, Film, Flag, Pencil, Play, Undo2, Video } from 'lucide-react';
import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react';
import { Link, useParams, useSearchParams } from 'react-router-dom';
import { ApiError, api } from '../api';
import { useAuth } from '../auth';
import { refreshFeed } from '../components/events';
import { DecisionBar, DescriptionBlock, FrameStrip, RuleBlock, VerifyBlock } from '../components/finding';
import { Crumb, EmptyState, Loading, Page } from '../components/page';
import { Player, SequencePlayer, type Marker, type PlayerHandle } from '../components/Player';
import { Badge } from '../components/ui/badge';
import { Button } from '../components/ui/button';
import { Card, cardClass } from '../components/ui/card';
import { useI18n } from '../i18n';
import { cn } from '../lib/utils';
import type { Finding, HistoryItem } from '../types';
import { fmtDate, keyFrame, serial, tc, useAgo } from '../ui';
import { Verdict } from './Check';

/* side sections are type-led and unboxed: a hairline above, the heading carries the structure */
function SideSection({ title, children }: { title: ReactNode; children: ReactNode }) {
  return <section className="border-t border-border pt-4 pb-1"><h3 className="mb-3 text-[15px] font-semibold">{title}</h3>{children}</section>;
}

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

  if (err) return <Page><Crumb to="/live">{t('fd.crumbLive')}</Crumb><Card><EmptyState title={t('fd.gone')}>{err.message}</EmptyState></Card></Page>;
  if (!f) return <Page><Loading /></Page>;

  const from = sp.get('from');
  const back = from === 'review' ? { to: '/review', label: t('fd.crumbReview') } : from === 'check' && f.job_id ? { to: `/checks/${f.job_id}`, label: f.filename || t('fd.upload') } : { to: '/live', label: t('fd.crumbLive') };
  const where = f.source === 'camera' ? f.camera_name || f.camera_id : f.filename;
  const marker: Marker[] = f.t_sec != null ? [{ t: f.t_sec, label: '!', title: typeName(f.type_code, f.type_name), state: f.decision === 'confirm' ? 'confirm' : f.decision ? 'done' : '', thumb: keyFrame(f.frames, f.t_sec) }] : [];
  const sib = f.siblings || [];
  const pos = sib.findIndex(s => s.id === f.id);
  const prev = pos > 0 ? sib[pos - 1] : null, next = pos >= 0 && pos < sib.length - 1 ? sib[pos + 1] : null;

  let media: ReactNode;
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

  const decisionTone = f.decision === 'reject' ? 'info' : 'bad';
  const verifyBadge = f.verified
    ? <Badge variant={f.verify_result === 'agree' ? 'success' : 'destructive'}>{f.verify_result === 'agree' ? <Check /> : <Flag />}{t('fd.verifiedBy', { n: f.verified_by_name || f.verified_by || '' })}</Badge>
    : f.decision ? <Badge variant="muted">{t('fd.notVerified')}</Badge> : null;

  return (
    <Page wide>
      <Crumb to={back.to}>{back.label}</Crumb>
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <h1 className="text-[26px] font-semibold tracking-tight break-words">{typeName(f.type_code, f.type_name)}</h1>
          <div className="mt-1.5 flex flex-wrap items-center gap-x-[18px] gap-y-1 text-[13.5px] text-muted-foreground">
            <Badge variant="muted">{f.source === 'camera' ? <Video /> : <Film />}{t(f.source === 'camera' ? 'fd.camera' : 'fd.upload')}</Badge>
            <span>{where}</span>{f.t_sec != null && <span className="tabular-nums">{t('ev.at', { t: tc(f.t_sec) })}</span>}<span>{ago(f.created_at)}</span>
            <span className="font-medium tracking-wider text-faint tabular-nums">№ {serial(f.id)}</span>
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          {f.job_id && <Button asChild variant="secondary"><Link to={`/checks/${f.job_id}`}><Film />{t('fd.openCheck')}</Link></Button>}
          {prev && <Button asChild variant="secondary"><Link to={`/findings/${prev.id}?from=${from || ''}`}><ChevronLeft />{t('fd.prev')}</Link></Button>}
          {next && <Button asChild variant="secondary"><Link to={`/findings/${next.id}?from=${from || ''}`}>{t('fd.next')}<ChevronRight /></Link></Button>}
        </div>
      </div>

      <Verdict tone={decisionTone} icon={f.decision === 'reject' ? <Check /> : <AlertTriangle />}
        title={f.decision === 'confirm' ? t('f.confirmed') : f.decision === 'reject' ? t('f.notViolation') : t('v.badTitle')}
        text={f.decision ? `${t('f.decidedBy', { n: f.decided_by_name || f.decided_by || '' })}${f.decided_at ? `, ${fmtDate(f.decided_at, locale)}` : ''}` : t('f.question')}
        aside={verifyBadge} />

      <div className="grid items-start gap-5 xl:grid-cols-[minmax(280px,380px)_minmax(0,1fr)]">
        <div className="flex min-w-0 flex-col gap-3.5">
          <Card className="overflow-visible p-3.5">{media}</Card>
          <VerifyBlock f={f} onChange={onChange} />
          <SideSection title={t('fd.history')}><History items={f.history} /></SideSection>
          {f.alert && (
            <SideSection title={t('fd.alert')}>
              <div className="flex flex-wrap items-center gap-2">
                <Badge variant={f.alert.severity === 'critical' ? 'destructive' : f.alert.severity === 'high' ? 'warning' : 'muted'}>{t(`sev.${f.alert.severity}`)}</Badge>
                <span className="text-[13px] text-muted-foreground">{t(f.alert.state === 'open' ? 'ev.pending' : f.alert.state === 'false_positive' ? 'ev.markedFalse' : f.alert.state === 'resolved' ? 'ev.resolved' : 'ev.acked')}{f.alert.count > 1 ? `, ×${f.alert.count}` : ''}{f.alert.escalation_level ? `, ${t('ev.escalated')}` : ''}</span>
              </div>
            </SideSection>
          )}
        </div>
        <div className="flex min-w-0 flex-col gap-3.5">
          <article className={cn(cardClass, 'border-foreground ring-1 ring-foreground')}>
            <div className="flex flex-wrap items-center gap-3 border-b border-border px-4 py-3.5 sm:px-5 sm:py-4">
              <span className={cn('grid h-7 min-w-7 shrink-0 place-items-center rounded-md px-1.5 text-[13px] font-semibold tabular-nums',
                f.decision === 'confirm' ? 'bg-destructive text-white' : f.decision ? 'bg-muted text-faint' : 'bg-primary text-white')}>!</span>
              <h3 className="flex-[1_1_60%] text-[17px] font-semibold leading-tight sm:text-lg">{typeName(f.type_code, f.type_name)}</h3>
              {f.t_sec != null && (
                <div className="ml-auto flex shrink-0 items-center gap-1.5">
                  <Button size="sm" variant="secondary" onClick={() => player.current?.seek(Math.max(0, f.t_sec! - 1), true)}><Play className="fill-current" /><span className="tracking-wide tabular-nums">{tc(f.t_sec)}</span></Button>
                </div>
              )}
            </div>
            <div className="grid gap-5 px-4 py-[18px] sm:grid-cols-[auto_minmax(0,1fr)] sm:px-5">
              <FrameStrip frames={f.frames} keyT={f.t_sec} caption={where || ''} />
              <div className="min-w-0">
                <DescriptionBlock f={f} editable={can('operator') && !f.verified} onChange={onChange} />
                <RuleBlock rule={f.rule || {}} typeCode={f.type_code} clipUrl={f.clip_url} />
              </div>
            </div>
            <DecisionBar f={f} editable={can('operator') && !f.verified} onChange={onChange} />
          </article>
          {sib.length > 1 && (
            <SideSection title={t('fd.others')}>
              <ul className="flex flex-col gap-px">
                {sib.map(s => (
                  <li key={s.id}>
                    <Link to={`/findings/${s.id}?from=${from || ''}`} aria-current={s.id === f.id ? 'page' : undefined}
                      className={cn('grid grid-cols-[64px_minmax(0,1fr)_auto] items-baseline gap-3 rounded-md px-2.5 py-2 text-sm no-underline transition-colors hover:bg-subtle', s.id === f.id && 'bg-subtle')}>
                      <span className="text-xs font-semibold tracking-wide text-primary-ink tabular-nums">{tc(s.t_sec)}</span>
                      <span>{typeName(undefined, s.type_name)}</span>
                      {s.decision ? <span className="text-[13px] text-muted-foreground">{t(s.decision === 'confirm' ? 'f.confirmed' : 'f.notViolation')}</span> : <span />}
                    </Link>
                  </li>
                ))}
              </ul>
            </SideSection>
          )}
        </div>
      </div>
    </Page>
  );
}

const DOT: Record<string, string> = { ok: 'bg-success-soft text-success', bad: 'bg-destructive-soft text-destructive', info: 'bg-info-soft text-info', '': 'bg-muted text-muted-foreground' };

export function History({ items }: { items: HistoryItem[] }) {
  const { t, locale } = useI18n();
  if (!items?.length) return <p className="text-[13px] text-muted-foreground">{t('fd.noHistory')}</p>;
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
  const icon = (h: HistoryItem) => h.action === 'edit' ? <Pencil /> : h.action === 'verify' ? <Eye /> : h.action === 'decide' ? <Check /> : <Undo2 />;
  return (
    <ul className="relative flex flex-col gap-3.5">
      {items.slice().reverse().map(h => (
        <li key={h.id} className="relative grid grid-cols-[26px_minmax(0,1fr)] gap-2.5 text-sm not-last:before:absolute not-last:before:top-7 not-last:before:-bottom-3.5 not-last:before:left-[12.5px] not-last:before:border-l not-last:before:border-dashed not-last:before:border-border-strong not-last:before:content-['']">
          <span className={cn('grid size-[26px] place-items-center rounded-[7px] [&_svg]:size-3.5', DOT[cls(h)])}>{icon(h)}</span>
          <div className="min-w-0">
            <b className="font-semibold">{h.actor_name || h.actor}</b> {label(h)}{h.payload?.comment ? <> - «{String(h.payload.comment)}»</> : null}
            {h.action === 'edit' && h.payload?.after ? <div className="mt-1.5 rounded-[10px] bg-info-soft px-3.5 py-3 text-[13px] leading-snug">{String(h.payload.after)}</div> : null}
            <small className="block text-xs text-muted-foreground tabular-nums">{fmtDate(h.created_at, locale)}, {t(`role.${h.actor_role}`) !== `role.${h.actor_role}` ? t(`role.${h.actor_role}`) : h.actor_role}</small>
          </div>
        </li>
      ))}
    </ul>
  );
}

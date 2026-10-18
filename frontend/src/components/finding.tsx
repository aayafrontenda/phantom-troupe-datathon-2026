import { Check, ChevronRight, Clapperboard, ExternalLink, Flag, Pencil, Undo2, X } from 'lucide-react';
import { useEffect, useState } from 'react';
import { api } from '../api';
import { useAuth } from '../auth';
import { useI18n } from '../i18n';
import { cn } from '../lib/utils';
import type { Finding, FindingBrief, Frame, Rule } from '../types';
import { observedPart, shortDesc, tc, useUi } from '../ui';
import { Badge } from './ui/badge';
import { Button } from './ui/button';
import { Input, Textarea } from './ui/input';

export const labelClass = 'mb-1.5 text-xs font-semibold text-muted-foreground';
const descClass = 'max-w-[68ch] text-[15px] leading-relaxed';
const linkClass = 'inline-flex items-center gap-1 underline decoration-border-strong underline-offset-[3px] hover:decoration-foreground';

export function Conf({ f }: { f: { confidence: number | null; below_threshold?: boolean } }) {
  const { t } = useI18n();
  if (f.confidence == null) return null;
  return (
    <span className="inline-flex items-center gap-2 text-[13px] text-muted-foreground">
      {t('f.confidence', { p: Math.round(f.confidence * 100) })}
      {f.below_threshold && <Badge variant="muted" title={t('f.belowThresholdTip')}>{t('f.belowThreshold')}</Badge>}
    </span>
  );
}

export function FrameStrip({ frames, keyT, caption }: { frames: Frame[]; keyT?: number | null; caption: string }) {
  const { t } = useI18n();
  const { zoom } = useUi();
  if (!frames.length) return null;
  return (
    <div className="flex gap-1.5">
      {frames.map((f, k) => {
        const key = keyT != null && Math.abs(f.timestamp_sec - keyT) < 0.3;
        return (
          <button key={k} type="button" title={t('f.enlarge')}
            className="group flex cursor-zoom-in flex-col gap-1 text-[11.5px] font-medium text-muted-foreground tabular-nums"
            onClick={e => { e.stopPropagation(); zoom(`data:image/jpeg;base64,${f.image_base64}`, `${caption} · ${tc(f.timestamp_sec)}`); }}>
            <img src={`data:image/jpeg;base64,${f.image_base64}`} alt={t('f.frameAt', { t: tc(f.timestamp_sec) })}
              className={cn('block aspect-[464/848] w-[84px] rounded-md border border-border bg-video object-cover transition-[transform,border-color] duration-200 pointer-fine:group-hover:-translate-y-0.5 pointer-fine:group-hover:border-foreground',
                key && 'outline-2 outline-offset-1 outline-primary')} />
            <span className={cn(key && 'font-semibold text-primary-ink')}>{tc(f.timestamp_sec)}</span>
          </button>
        );
      })}
    </div>
  );
}

const nb = (s: string) => s.replace(/(№|п\.|пп\.) /g, '$1 ');
const KIND_CLASS: Record<string, string> = { direct: 'text-success', indirect: 'text-warning', internal: 'text-muted-foreground' };

export function KindLabel({ kind, className }: { kind?: string | null; className?: string }) {
  const { t, has } = useI18n();
  if (!kind) return null;
  return <span className={cn('text-xs font-semibold whitespace-nowrap', KIND_CLASS[kind] || 'text-muted-foreground', className)}>{has(`kind.${kind}`) ? t(`kind.${kind}`) : kind}</span>;
}

export function RuleBlock({ rule, typeCode, clipUrl, open = true }: { rule: Rule; typeCode?: string | null; clipUrl?: string | null; open?: boolean }) {
  const { t, lang, docName: docRaw, pointName: pointRaw, docUrl, typeField } = useI18n();
  const docName = (r: Parameters<typeof docRaw>[0]) => nb(docRaw(r));
  const pointName = (p: Parameters<typeof pointRaw>[0]) => nb(pointRaw(p));
  const refs = rule.refs || [];
  const title = refs.length ? `${refs[0].point ? pointName(refs[0].point) + ', ' : ''}${docName(refs[0])}` : t('f.internalReg');
  const caveat = typeField(typeCode, 'caveat', rule.caveat);
  return (
    <details className="group mt-4 border-t border-border" open={open}>
      <summary className="flex cursor-pointer list-none items-start gap-2 pt-3 pb-1 text-[13.5px] transition-colors hover:text-foreground [&::-webkit-details-marker]:hidden">
        <ChevronRight className="mt-[3px] size-[15px] shrink-0 text-faint transition-transform duration-200 group-open:rotate-90 group-hover:text-foreground" />
        <span className="min-w-0 flex-1">{t('f.rule')}: <b className="font-semibold">{title}</b></span>
        <KindLabel kind={rule.kind} className="mt-0.5 shrink-0 pl-2" />
      </summary>
      <div className="flex flex-col gap-2 py-1.5 pl-3.5 text-[13.5px] sm:pl-[23px]">
        {refs.length ? refs.map((r, i) => (
          <div key={i}><b className="font-semibold">{docName(r)}</b>{r.point ? `, ${pointName(r.point)}` : ''}
            {r.quote && <><br /><q lang="ru">{r.quote}</q>{lang !== 'ru' && <small className="text-muted-foreground"> ({t('f.quoteRu')})</small>}</>}
            {!r.quote && r.paraphrase && <><br /><span lang="ru">{r.paraphrase}</span> <small className="text-muted-foreground">({t('f.paraphrase')})</small></>}
            {r.url && <><br /><a href={docUrl(r.url)} target="_blank" rel="noopener" className={linkClass}>{t('f.openAdilet')} <ExternalLink className="size-3.5" /></a></>}
          </div>
        )) : <div>{t('f.noPublic')}</div>}
        {caveat && <div className="text-xs text-warning">{caveat}</div>}
        {clipUrl && <a href={clipUrl} target="_blank" rel="noopener" className={cn(linkClass, 'w-fit')}><Clapperboard className="size-4" /> {t('f.clip')}</a>}
      </div>
    </details>
  );
}

export function DescriptionBlock({ f, onChange, editable }: { f: FindingBrief; onChange: (f: Finding) => void; editable: boolean }) {
  const { t, lang, typeField } = useI18n();
  const { toast } = useUi();
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState(f.description_edit || '');
  const [busy, setBusy] = useState(false);
  useEffect(() => { if (!editing) setText(f.description_edit || ''); }, [f.description_edit, editing]);

  const ai = shortDesc(f.description_ai);
  const why = typeField(f.type_code, 'why');
  const obs = observedPart(f.description_ai);
  const aiBody = lang !== 'ru' && why
    ? <><p className={labelClass}>{t('f.why')}</p><p className={descClass}>{why}</p>{obs && <><p className={cn(labelClass, 'mt-3.5')}>{t('f.modelNote')}</p><p className={cn(descClass, 'text-muted-foreground')} lang="ru">{obs}.</p></>}</>
    : <><p className={labelClass}>{f.description_edit ? t('f.aiDesc') : t('f.seen')}</p><p className={cn(descClass, f.description_edit && 'text-muted-foreground')} lang="ru">{ai}</p></>;

  const save = async (value: string | null) => {
    setBusy(true);
    try {
      const nf = await api<Finding>(`/ui/api/findings/${f.id}/description`, { method: 'PATCH', json: { text: value ?? '' } });
      onChange(nf); setEditing(false); toast(t('f.savedDesc'));
    } catch (e) { toast(t('toast.saveErr', { e: (e as Error).message }), 'err'); }
    finally { setBusy(false); }
  };

  return (
    <div>
      {f.description_edit && !editing && (
        <div className="mb-3.5 rounded-[10px] bg-info-soft px-3.5 py-3 text-[15px] leading-snug">
          <p className={cn(labelClass, 'text-info')}>{t('f.opDesc')}</p>{f.description_edit}
          {f.decided_by && <span className="mt-2 block text-xs text-muted-foreground">{t('f.editedBy', { n: f.decided_by_name || f.decided_by })}</span>}
        </div>
      )}
      {!editing && aiBody}
      {editable && !editing && (
        <div className="mt-2.5"><Button size="xs" variant="secondary" onClick={() => { setText(f.description_edit || ai); setEditing(true); }}><Pencil />{t('f.edit')}</Button></div>
      )}
      {editing && (
        <div className="flex flex-col gap-2.5" onClick={e => e.stopPropagation()}>
          <p className={cn(labelClass, 'mb-0')}>{t('f.edit')}</p>
          <p className="text-[13px] text-muted-foreground">{t('f.editHint')}</p>
          <Textarea value={text} onChange={e => setText(e.target.value)} placeholder={t('f.editPh')} maxLength={2000} autoFocus />
          <div className="flex flex-wrap items-center gap-2">
            <Button size="sm" disabled={busy || !text.trim()} onClick={() => save(text)}><Check />{t('f.saveDesc')}</Button>
            {f.description_edit && <Button size="sm" variant="secondary" disabled={busy} onClick={() => save(null)}><Undo2 />{t('f.resetDesc')}</Button>}
            <Button size="sm" variant="ghost" disabled={busy} onClick={() => setEditing(false)}>{t('cancel')}</Button>
          </div>
        </div>
      )}
    </div>
  );
}

const footClass = 'flex flex-wrap items-center gap-2 border-t border-border bg-subtle px-4 py-3 sm:px-5';

export function DecisionBar({ f, onChange, editable, names }: { f: FindingBrief; onChange: (f: Finding) => void; editable: boolean; names?: Record<string, string> }) {
  const { t } = useI18n();
  const { toast } = useUi();
  const [comment, setComment] = useState('');
  const [busy, setBusy] = useState(false);
  const decide = async (decision: 'confirm' | 'reject' | null) => {
    setBusy(true);
    try {
      const nf = await api<Finding>(`/ui/api/findings/${f.id}/decision`, { method: 'POST', json: { decision, comment: comment || null } });
      setComment(''); onChange(nf);
    } catch (e) { toast(t('toast.saveErr', { e: (e as Error).message }), 'err'); }
    finally { setBusy(false); }
  };
  const who = f.decided_by_name || names?.[f.decided_by || ''] || f.decided_by;
  if (f.decision) {
    return (
      <div className={footClass}>
        <div className="flex flex-wrap items-center gap-2.5">
          {f.decision === 'confirm'
            ? <Badge variant="destructive" className="origin-[30%_60%] animate-stamp"><Check />{t('f.confirmed')}</Badge>
            : <Badge variant="muted" className="origin-[30%_60%] animate-stamp"><X />{t('f.notViolation')}</Badge>}
          {who && <span className="text-[13px] text-muted-foreground">{t('f.decidedBy', { n: who })}</span>}
          {f.decision_comment && <span className="text-[13px] text-muted-foreground">«{f.decision_comment}»</span>}
          {editable && <Button size="xs" variant="ghost" disabled={busy} onClick={e => { e.stopPropagation(); decide(null); }}><Undo2 />{t('f.undo')}</Button>}
        </div>
        <span className="flex-1" />
        <Conf f={f} />
      </div>
    );
  }
  if (!editable) {
    return <div className={footClass}><Badge variant="warning">{t('fd.notDecided')}</Badge><span className="flex-1" /><Conf f={f} /></div>;
  }

  return (
    <div className={cn(footClass, busy && '[&_button]:opacity-60 [&_button]:blur-[.6px] [&_button]:transition-[filter,opacity]')} aria-busy={busy} onClick={e => e.stopPropagation()}>
      <span className="mr-1.5 text-[14.5px] font-semibold">{t('f.question')}</span>
      <Button size="sm" variant="outline" disabled={busy} onClick={() => decide('confirm')} className="hover:border-transparent hover:bg-destructive hover:text-white"><Check />{t('f.yes')}</Button>
      <Button size="sm" variant="outline" disabled={busy} onClick={() => decide('reject')} className="hover:border-transparent hover:bg-foreground hover:text-background"><X />{t('f.no')}</Button>
      <Input size="sm" className="max-w-[360px] flex-[1_1_200px]" placeholder={t('f.comment')} value={comment} onChange={e => setComment(e.target.value)} maxLength={1000} />
      <Conf f={f} />
    </div>
  );
}

export function VerifyBlock({ f, onChange }: { f: Finding; onChange: (f: Finding) => void }) {
  const { t } = useI18n();
  const { can } = useAuth();
  const { toast } = useUi();
  const [comment, setComment] = useState('');
  const [busy, setBusy] = useState(false);
  if (!can('supervisor')) return null;
  const verify = async (result: 'agree' | 'disagree' | null) => {
    setBusy(true);
    try {
      const nf = await api<Finding>(`/ui/api/findings/${f.id}/verify`, { method: 'POST', json: { result, comment: comment || null } });
      setComment(''); onChange(nf);
    } catch (e) { toast(t('toast.saveErr', { e: (e as Error).message }), 'err'); }
    finally { setBusy(false); }
  };
  return (
    <section className="border-t border-border pt-4 pb-1">
      <h3 className="mb-3 text-[15px] font-semibold">{t('fd.verification')}</h3>
      {f.verified ? (
        <>
          <div className="mb-2.5 flex flex-wrap items-center gap-2.5">
            <Badge variant={f.verify_result === 'agree' ? 'success' : 'destructive'}>{f.verify_result === 'agree' ? <Check /> : <Flag />}{t(f.verify_result === 'agree' ? 'fd.agree' : 'fd.disagree')}</Badge>
            <span className="text-[13px] text-muted-foreground">{t('fd.verifiedBy', { n: f.verified_by_name || f.verified_by || '' })}</span>
          </div>
          {f.verify_comment && <p className="mb-2.5 rounded-[10px] bg-subtle px-3.5 py-3 text-[15px] leading-snug">«{f.verify_comment}»</p>}
          <Button size="xs" variant="ghost" disabled={busy} onClick={() => verify(null)}><Undo2 />{t('fd.unverify')}</Button>
        </>
      ) : f.decision ? (
        <>
          <p className="mb-2.5 text-[13px] text-muted-foreground">{t('fd.verifyQ')} {t('fd.verifyHint')}</p>
          <Textarea className="mb-2.5 min-h-[72px]" placeholder={t('f.comment')} value={comment} onChange={e => setComment(e.target.value)} maxLength={1000} />
          <div className="flex flex-wrap items-center gap-2">
            <Button size="sm" variant="success" disabled={busy} onClick={() => verify('agree')}><Check />{t('fd.agree')}</Button>
            <Button size="sm" variant="destructive" disabled={busy} onClick={() => verify('disagree')}><Flag />{t('fd.disagree')}</Button>
          </div>
        </>
      ) : <p className="text-[13px] text-muted-foreground">{t('fd.notDecided')}</p>}
    </section>
  );
}

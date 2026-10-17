/* Building blocks of a finding: frames, description (AI vs operator wording), regulation, decision, verification. */
import { useEffect, useState } from 'react';
import { api } from '../api';
import { useAuth } from '../auth';
import { useI18n } from '../i18n';
import type { Finding, FindingBrief, Frame, Rule } from '../types';
import { Icon, observedPart, shortDesc, tc, useUi } from '../ui';

export function FrameStrip({ frames, keyT, caption }: { frames: Frame[]; keyT?: number | null; caption: string }) {
  const { t } = useI18n();
  const { zoom } = useUi();
  if (!frames.length) return null;
  return (
    <div className="frames">
      {frames.map((f, k) => (
        <button key={k} className={`frame ${keyT != null && Math.abs(f.timestamp_sec - keyT) < 0.3 ? 'key' : ''}`} title={t('f.enlarge')}
          onClick={e => { e.stopPropagation(); zoom(`data:image/jpeg;base64,${f.image_base64}`, `${caption} · ${tc(f.timestamp_sec)}`); }}>
          <img src={`data:image/jpeg;base64,${f.image_base64}`} alt={t('f.frameAt', { t: tc(f.timestamp_sec) })} /><span>{tc(f.timestamp_sec)}</span>
        </button>
      ))}
    </div>
  );
}

export function RuleBlock({ rule, typeCode, clipUrl }: { rule: Rule; typeCode?: string | null; clipUrl?: string | null }) {
  const { t, lang, docName, pointName, docUrl, typeField, has } = useI18n();
  const refs = rule.refs || [];
  const title = refs.length ? `${refs[0].point ? pointName(refs[0].point) + ' · ' : ''}${docName(refs[0])}` : t('f.internalReg');
  const caveat = typeField(typeCode, 'caveat', rule.caveat);
  return (
    <details className="rule">
      <summary><Icon id="chev" /><span>{t('f.rule')}: <b>{title}</b></span>{rule.kind && <> <span className={`kind ${rule.kind}`}>{has(`kind.${rule.kind}`) ? t(`kind.${rule.kind}`) : rule.kind}</span></>}</summary>
      <div className="rb">
        {refs.length ? refs.map((r, i) => (
          <div key={i}><b>{docName(r)}</b>{r.point ? `, ${pointName(r.point)}` : ''}
            {r.quote && <><br /><q lang="ru">{r.quote}</q>{lang !== 'ru' && <small className="muted"> ({t('f.quoteRu')})</small>}</>}
            {r.url && <><br /><a href={docUrl(r.url)} target="_blank" rel="noopener">{t('f.openAdilet')} <Icon id="link" /></a></>}
          </div>
        )) : <div>{t('f.noPublic')}</div>}
        {caveat && <div className="caveat">{caveat}</div>}
        {clipUrl && <a href={clipUrl} target="_blank" rel="noopener"><Icon id="clip" /> {t('f.clip')}</a>}
      </div>
    </details>
  );
}

/* AI description, operator wording, and the editor (operators only). */
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
    ? <><p className="label">{t('f.why')}</p><p className="desc">{why}</p>{obs && <><p className="label">{t('f.modelNote')}</p><p className="desc muted" lang="ru">{obs}.</p></>}</>
    : <><p className="label">{f.description_edit ? t('f.aiDesc') : t('f.seen')}</p><p className={`desc ${f.description_edit ? 'muted' : ''}`} lang="ru">{ai}</p></>;

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
        <div className="desc-box op"><p className="label" style={{ color: 'var(--info)' }}>{t('f.opDesc')}</p>{f.description_edit}
          {f.decided_by && <span className="who">{t('f.editedBy', { n: f.decided_by_name || f.decided_by })}</span>}</div>
      )}
      {!editing && aiBody}
      {editable && !editing && (
        <div style={{ marginTop: 10 }}><button className="btn xs" onClick={() => { setText(f.description_edit || ai); setEditing(true); }}><Icon id="edit" />{t('f.edit')}</button></div>
      )}
      {editing && (
        <div className="editor" onClick={e => e.stopPropagation()}>
          <p className="label">{t('f.edit')}</p>
          <p className="muted small">{t('f.editHint')}</p>
          <textarea className="field" value={text} onChange={e => setText(e.target.value)} placeholder={t('f.editPh')} maxLength={2000} autoFocus />
          <div className="acts">
            <button className="btn sm primary" disabled={busy || !text.trim()} onClick={() => save(text)}><Icon id="check" />{t('f.saveDesc')}</button>
            {f.description_edit && <button className="btn sm" disabled={busy} onClick={() => save(null)}><Icon id="undo" />{t('f.resetDesc')}</button>}
            <button className="btn sm ghost" disabled={busy} onClick={() => setEditing(false)}>{t('cancel')}</button>
          </div>
        </div>
      )}
    </div>
  );
}

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
      <div className="find-f">
        <div className="decided">
          {f.decision === 'confirm' ? <span className="pill bad"><Icon id="check" />{t('f.confirmed')}</span> : <span className="pill neutral"><Icon id="x" />{t('f.notViolation')}</span>}
          {who && <span className="muted small">{t('f.decidedBy', { n: who })}</span>}
          {f.decision_comment && <span className="muted small">«{f.decision_comment}»</span>}
          {editable && <button className="btn xs ghost" disabled={busy} onClick={e => { e.stopPropagation(); decide(null); }}><Icon id="undo" />{t('f.undo')}</button>}
        </div>
        <span className="sp" />
        {f.confidence != null && <span className="muted small">{t('f.confidence', { p: Math.round(f.confidence * 100) })}</span>}
      </div>
    );
  }
  if (!editable) {
    return <div className="find-f"><span className="pill warn">{t('fd.notDecided')}</span><span className="sp" />{f.confidence != null && <span className="muted small">{t('f.confidence', { p: Math.round(f.confidence * 100) })}</span>}</div>;
  }
  return (
    <div className="find-f" onClick={e => e.stopPropagation()}>
      <span className="q">{t('f.question')}</span>
      <button className="btn sm yes" disabled={busy} onClick={() => decide('confirm')}><Icon id="check" />{t('f.yes')}</button>
      <button className="btn sm no" disabled={busy} onClick={() => decide('reject')}><Icon id="x" />{t('f.no')}</button>
      <input className="field sm" style={{ flex: '1 1 200px', maxWidth: 360 }} placeholder={t('f.comment')} value={comment} onChange={e => setComment(e.target.value)} maxLength={1000} />
      {f.confidence != null && <span className="muted small">{t('f.confidence', { p: Math.round(f.confidence * 100) })}</span>}
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
    <div className="card">
      <h3>{t('fd.verification')}</h3>
      {f.verified ? (
        <>
          <div className="status-line">
            <span className={`pill ${f.verify_result === 'agree' ? 'ok' : 'bad'}`}><Icon id={f.verify_result === 'agree' ? 'check' : 'flag'} />{t(f.verify_result === 'agree' ? 'fd.agree' : 'fd.disagree')}</span>
            <span className="muted small">{t('fd.verifiedBy', { n: f.verified_by_name || f.verified_by || '' })}</span>
          </div>
          {f.verify_comment && <p className="desc-box" style={{ marginBottom: 10 }}>«{f.verify_comment}»</p>}
          <button className="btn xs ghost" disabled={busy} onClick={() => verify(null)}><Icon id="undo" />{t('fd.unverify')}</button>
        </>
      ) : f.decision ? (
        <>
          <p className="muted small" style={{ marginBottom: 10 }}>{t('fd.verifyQ')} {t('fd.verifyHint')}</p>
          <textarea className="field" style={{ minHeight: 72, marginBottom: 10 }} placeholder={t('f.comment')} value={comment} onChange={e => setComment(e.target.value)} maxLength={1000} />
          <div className="row">
            <button className="btn sm ok" disabled={busy} onClick={() => verify('agree')}><Icon id="check" />{t('fd.agree')}</button>
            <button className="btn sm danger" disabled={busy} onClick={() => verify('disagree')}><Icon id="flag" />{t('fd.disagree')}</button>
          </div>
        </>
      ) : <p className="muted small">{t('fd.notDecided')}</p>}
    </div>
  );
}

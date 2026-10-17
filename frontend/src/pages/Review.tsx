import { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { api } from '../api';
import { useFeed } from '../components/events';
import { useI18n } from '../i18n';
import type { FindingBrief, RuleType } from '../types';
import { Icon, tc, useAgo } from '../ui';

type Quick = 'all' | 'pending' | 'rejected' | 'confirmed' | 'toVerify' | 'verified' | 'disagreed' | 'edited';
const QUICK: Record<Quick, Record<string, string>> = {
  all: {}, pending: { decision: 'pending' }, rejected: { decision: 'reject' }, confirmed: { decision: 'confirm' },
  toVerify: { decision: 'decided', verified: 'false' }, verified: { verified: 'true' }, disagreed: { verified: 'true', disagree: '1' }, edited: { edited: 'true' },
};
const PAGE = 50;

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
  const [limit, setLimit] = useState(PAGE);
  const [types, setTypes] = useState<RuleType[]>([]);
  const [ops, setOps] = useState<string[]>([]);
  const feed = useFeed();
  const counts = feed.counts;

  const set = (k: string, v: string) => { const n = new URLSearchParams(sp); if (v) n.set(k, v); else n.delete(k); setSp(n, { replace: true }); setLimit(PAGE); };

  const load = useCallback(async () => {
    const p = new URLSearchParams({ limit: String(limit) });
    const q = QUICK[quick] || {};
    if (q.decision) p.set('decision', q.decision);
    if (q.verified) p.set('verified', q.verified);
    if (q.edited) p.set('edited', q.edited);
    if (source) p.set('source', source);
    if (type) p.set('type_code', type);
    if (op) p.set('decided_by', op);
    if (text) p.set('q', text);
    if (period) p.set('since', String(Date.now() / 1000 - { today: 86400, week: 7 * 86400, month: 30 * 86400 }[period]!));
    try {
      const d = await api<{ findings: FindingBrief[]; total: number }>(`/ui/api/findings?${p}`);
      const list = q.disagree ? d.findings.filter(f => f.verify_result === 'disagree') : d.findings;
      setRows(list); setTotal(q.disagree ? list.length : d.total);
      setOps(o => Array.from(new Set([...o, ...d.findings.map(f => f.decided_by).filter((x): x is string => !!x)])).sort());
    } catch { /* keep */ }
  }, [quick, source, type, op, text, period, limit]);

  useEffect(() => { load(); }, [load, feed.items]);
  useEffect(() => { api<{ types: RuleType[] }>('/ui/api/rules').then(d => setTypes(d.types)).catch(() => { }); }, []);

  const tiles: [Quick, string, number | undefined][] = useMemo(() => [
    ['rejected', 'attn', counts.rejected], ['toVerify', 'warn', counts.to_verify], ['confirmed', 'bad', counts.confirmed],
    ['pending', '', counts.pending], ['verified', 'ok', counts.verified], ['disagreed', 'bad', counts.disagreed], ['edited', '', counts.edited], ['all', '', counts.total],
  ], [counts]);

  return (
    <div className="page wide">
      <div className="page-head">
        <div><h1>{t('rv.title')}</h1><p>{t('rv.lead')}</p></div>
        <div className="acts"><a className="btn" href="/ui/api/findings.csv"><Icon id="download" />{t('rv.export')}</a></div>
      </div>
      <div className="chips" style={{ marginBottom: 20 }}>
        {tiles.map(([k, c, n]) => <button key={k} className={`chip ${quick === k ? 'on' : ''} ${c}`} onClick={() => set('q', k)}>{t(`rv.${k}`)}{n != null && <span className="n">{n}</span>}</button>)}
      </div>
      <div className="filters">
        <select className="field sm" value={source} onChange={e => set('source', e.target.value)}>
          <option value="">{t('rv.src.all')}</option><option value="upload">{t('rv.src.upload')}</option><option value="camera">{t('rv.src.camera')}</option>
        </select>
        <select className="field sm" value={type} onChange={e => set('type', e.target.value)}>
          <option value="">{t('rv.anyType')}</option>{types.map(x => <option key={x.code} value={x.code}>{x.code} · {typeName(x.code, x.type)}</option>)}
        </select>
        <select className="field sm" value={op} onChange={e => set('op', e.target.value)}>
          <option value="">{t('rv.anyOp')}</option>{ops.map(o => <option key={o} value={o}>{o}</option>)}
        </select>
        <select className="field sm" value={period} onChange={e => set('period', e.target.value)}>
          <option value="">{t('rv.any')}</option><option value="today">{t('rv.today')}</option><option value="week">{t('rv.week')}</option><option value="month">{t('rv.month')}</option>
        </select>
        <label className="search" style={{ maxWidth: 280 }}><span style={{ position: 'absolute', left: 14, top: 11, color: 'var(--faint)' }}><Icon id="search" /></span><input className="field sm" style={{ paddingLeft: 40 }} placeholder={t('search.any')} defaultValue={text} onKeyDown={e => { if (e.key === 'Enter') set('text', (e.target as HTMLInputElement).value); }} /></label>
      </div>
      <div className="card">
        {!rows.length ? <div className="empty"><b>{t('rv.empty')}</b>{t('rv.emptyHint')}</div> : (
          <>
            <table className="table">
              <thead><tr><th>{t('rv.th.when')}</th><th>{t('rv.th.where')}</th><th>{t('rv.th.type')}</th><th>{t('rv.th.ai')}</th><th>{t('rv.th.decision')}</th><th>{t('rv.th.verify')}</th><th /></tr></thead>
              <tbody>
                {rows.map(f => (
                  <tr key={f.id} className="click" onClick={() => nav(`/findings/${f.id}?from=review`)}>
                    <td className="muted">{ago(f.created_at)}</td>
                    <td><div className="fname"><span className="ic"><Icon id={f.source === 'camera' ? 'cam' : 'film'} /></span><div><b>{f.source === 'camera' ? f.camera_name || f.camera_id : f.filename || f.job_id}</b>{f.t_sec != null && <small className="num">{tc(f.t_sec)}</small>}</div></div></td>
                    <td>{typeName(f.type_code, f.type_name)}{f.edited && <> <span className="pill xs info" title={t('rv.edited')}><Icon id="edit" /></span></>}</td>
                    <td><span className="pill xs warn">{f.confidence != null ? t('rv.aiViolation', { p: Math.round(f.confidence * 100) }) : t('v.badTitle')}</span>{f.below_threshold && <> <span className="pill xs neutral" title={t('f.belowThresholdTip')}>{t('f.belowThreshold')}</span></>}</td>
                    <td>{f.decision ? <><span className={`pill xs ${f.decision === 'confirm' ? 'bad' : 'neutral'}`}>{t(f.decision === 'confirm' ? 'f.confirmed' : 'f.notViolation')}</span><div className="muted small">{f.decided_by_name || f.decided_by}</div></> : <span className="pill xs warn">{t('fd.notDecided')}</span>}</td>
                    <td>{f.verified ? <><span className={`pill xs ${f.verify_result === 'agree' ? 'ok' : 'bad'}`}><Icon id={f.verify_result === 'agree' ? 'check' : 'flag'} />{t(f.verify_result === 'agree' ? 'fd.agree' : 'fd.disagree')}</span><div className="muted small">{f.verified_by_name || f.verified_by}</div></> : f.decision ? <span className="muted">{t('fd.notVerified')}</span> : <span className="muted">—</span>}</td>
                    <td className="c-acts"><div className="row-acts"><span className={`btn xs ${f.decision && !f.verified ? 'primary' : ''}`}>{t(f.decision && !f.verified ? 'rv.verifyBtn' : 'act.open')}</span></div></td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div className="pager"><span>{t('rv.total', { n: rows.length, t: total })}</span>{rows.length < total && <button className="btn xs" onClick={() => setLimit(l => l + PAGE)}>{t('rv.more')}</button>}</div>
          </>
        )}
      </div>
    </div>
  );
}

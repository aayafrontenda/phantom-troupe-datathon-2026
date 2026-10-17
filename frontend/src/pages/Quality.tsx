import { useCallback, useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { api } from '../api';
import { useFeed } from '../components/events';
import { useI18n } from '../i18n';
import type { Quality } from '../types';
import { Icon } from '../ui';

const PERIODS: [number, string][] = [[7, 'q.p7'], [30, 'q.p30'], [0, 'q.pAll']];

function pct(v: number | null | undefined, digits = 0): string {
  return v == null ? '-' : `${(v * 100).toFixed(digits)}%`;
}

export default function QualityPage() {
  const { t, typeName, locale } = useI18n();
  const nav = useNavigate();
  const [days, setDays] = useState(30);
  const [cam, setCam] = useState('');
  const [data, setData] = useState<Quality | null>(null);
  const [cams, setCams] = useState<{ id: string; name: string }[]>([]);
  const feed = useFeed();

  const load = useCallback(async () => {
    const p = new URLSearchParams({ days: String(days) });
    if (cam) p.set('camera_id', cam);
    try { setData(await api<Quality>(`/ui/api/quality?${p}`)); } catch { /* keep */ }
  }, [days, cam]);
  useEffect(() => { load(); }, [load, feed.items]);
  useEffect(() => { api<{ cameras: { id: string; name: string }[] }>('/ui/api/cameras').then(d => setCams(d.cameras)).catch(() => { }); }, []);

  const nf = new Intl.NumberFormat(locale);
  const s = data?.summary;
  const verifiedBasis = s?.basis === 'verified';
  const accuracy = s?.accuracy ?? null;
  const delta = s?.accuracy_delta_pp ?? null;
  const maxDecided = Math.max(1, ...(data?.by_type.map(x => x.decided) || [1]));
  const raised = data?.by_type.filter(x => x.threshold.status === 'raised') || [];
  const retrain = data?.by_type.filter(x => x.threshold.status === 'retrain') || [];
  const fmtTh = (v: number) => v.toLocaleString(locale, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const steps = [1, 2, 3, 4, 5] as const;

  return (
    <div className="page wide">
      <div className="page-head">
        <div><h1>{t('q.title')}</h1><p>{t('q.lead')}</p></div>
        <div className="acts">
          {cams.length > 0 && (
            <select className="field sm" style={{ maxWidth: 220 }} value={cam} onChange={e => setCam(e.target.value)}>
              <option value="">{t('q.camAll')}</option>{cams.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
          )}
          <div className="seg">{PERIODS.map(([d, k]) => <button key={d} className={days === d ? 'on' : ''} onClick={() => setDays(d)}>{t(k)}</button>)}</div>
          <a className="btn primary" href={`/ui/api/quality/dataset.zip?days=${days}`} title={t('q.exportHint')}><Icon id="download" />{t('q.export')}</a>
        </div>
      </div>

      {!data ? <div className="loading">{t('loading')}</div> : !s?.decided ? (
        <div className="card empty"><b>{t('q.empty')}</b>{t('q.emptyHint')}</div>
      ) : (
        <>
          <div className="stats q-stats">
            <div className="stat ok">
              <div className="n num">{pct(accuracy)}</div>
              <div className="l">{t(verifiedBasis ? 'q.accuracy' : 'q.accuracyOp')}</div>
              <div className="sub">{delta != null && days > 0 ? <span className={`pill xs ${delta >= 0 ? 'ok' : 'bad'}`}>{t('q.delta', { d: (delta > 0 ? '+' : '') + delta.toLocaleString(locale), n: days })}</span> : <span className="muted">{days > 0 ? t('q.noPrev') : ''}</span>}</div>
            </div>
            <div className="stat warn">
              <div className="n num">{pct(accuracy == null ? null : 1 - accuracy)}</div>
              <div className="l">{t(verifiedBasis ? 'q.false' : 'q.falseOp')}</div>
              <div className="sub muted">{verifiedBasis ? `${nf.format(s.false_verified)} / ${nf.format(s.verified)}` : `${nf.format(s.rejected)} / ${nf.format(s.decided)}`}</div>
            </div>
            <div className="stat">
              <div className="n num">{nf.format(s.decided)}</div>
              <div className="l">{t('q.decided', { n: nf.format(s.verified) })}</div>
              <div className="sub muted">{s.coverage != null && t('q.coverage', { p: Math.round(s.coverage * 100) })}</div>
            </div>
            <div className="stat attn">
              <div className="n num">{nf.format(s.flagged)}</div>
              <div className="l">{t('q.flagged')}</div>
              <div className="sub"><Link to="/review?q=disagreed">{t('q.openReview')}</Link></div>
            </div>
          </div>

          <div className="q-grid">
            <div className="card pad">
              <h2>{t('q.byType')}</h2>
              <p className="muted small">{t('q.byTypeLead')}</p>
              <div className="q-bars">
                {data.by_type.filter(x => x.decided > 0).map(x => (
                  <div key={x.type_code} className="q-bar" onClick={() => nav(`/review?q=all&type=${x.type_code}`)}>
                    <div className="lab"><span className="code">{x.type_code}</span><span>{typeName(x.type_code, x.type_name)}</span></div>
                    <div className="track" title={x.threshold.status === 'raised' ? t('q.thRaised', { v: fmtTh(x.threshold.applied), b: fmtTh(x.threshold.base) }) : t('q.thBase', { v: fmtTh(x.threshold.applied) })}>
                      <i style={{ width: `${(x.confirm_rate || 0) * 100}%` }} />
                      <em style={{ width: `${(x.decided / maxDecided) * 100}%` }} />
                    </div>
                    <div className="val num"><span>{pct(x.confirm_rate)} · {nf.format(x.decided)}</span>{x.threshold.status === 'raised' && <span className="pill xs brand">{t('q.thRaised', { v: fmtTh(x.threshold.applied), b: fmtTh(x.threshold.base) })}</span>}</div>
                  </div>
                ))}
              </div>
              <div className="note">
                <Icon id="shield" />
                <span>
                  {raised.length ? t('q.raised', { list: raised.map(x => `${x.type_code} → ${fmtTh(x.threshold.applied)}`).join(', '), n: nf.format(data.dataset.verified) })
                    : t('q.noRaised', { base: fmtTh(data.thresholds.base), p: Math.round(data.thresholds.target * 100), n: data.thresholds.min_samples })}
                  {retrain.length > 0 && <> {t('q.retrain', { list: retrain.map(x => x.type_code).join(', '), p: Math.round(data.thresholds.target * 100) })}</>}
                </span>
              </div>
            </div>

            <div className="card pad">
              <h2>{t('q.weekly')}</h2>
              <p className="muted small">{t('q.weeklyLead')}</p>
              <div className="q-cols">
                {data.weekly.map(w => {
                  const h = w.rate == null ? 0 : Math.max(4, w.rate * 100);
                  const recent = data.period.since == null || w.start + 7 * 86400 > data.period.since;
                  return (
                    <div key={w.start} className="q-col" title={`${nf.format(w.false)} / ${nf.format(w.decided)}`}>
                      <span className="v num">{w.rate == null ? '' : pct(w.rate)}</span>
                      <div className="stack"><i className={recent ? 'now' : ''} style={{ height: `${h}%` }} /></div>
                      <span className="w num">{w.week}</span>
                    </div>
                  );
                })}
              </div>
              <div className="muted small" style={{ marginTop: 4 }}>{t('q.week')}</div>
              <div className="q-mini">
                <div><b className="num">{nf.format(data.dataset.examples)}</b><span>{t('q.dsExamples')}</span></div>
                <div><b className="num">{nf.format(data.dataset.negatives)}</b><span>{t('q.dsNeg')}</span></div>
                <div><b className="num">{raised.length} ⁄ {data.by_type.length}</b><span>{t('q.dsRaised')}</span></div>
              </div>
            </div>
          </div>

          <div className="card" style={{ marginBottom: 20 }}>
            <div className="q-card-head"><div><h2>{t('q.ops')}</h2><p className="muted small">{t('q.opsLead')}</p></div></div>
            <table className="table">
              <thead><tr><th>{t('q.th.op')}</th><th>{t('q.th.decided')}</th><th>{t('q.th.rejected')}</th><th>{t('q.th.edited')}</th><th>{t('q.th.verified')}</th><th>{t('q.th.disagreed')}</th><th /></tr></thead>
              <tbody>
                {data.operators.map(o => (
                  <tr key={o.login} className={`click ${o.flagged ? 'q-flag' : ''}`} onClick={() => nav(`/review?q=all&op=${encodeURIComponent(o.login)}`)}>
                    <td><div className="fname"><span className="ic"><Icon id="user" /></span><div><b>{o.name}</b><small>{o.flagged ? <span className="q-why">{t(o.flag_reason === 'disagree' ? 'q.flagDisagree' : 'q.flagRejects', { n: o.disagreed })}</span> : t(`role.${o.role || 'operator'}`)}</small></div></div></td>
                    <td className="num" data-l={t('q.th.decided')}>{nf.format(o.decided)}</td>
                    <td className="num" data-l={t('q.th.rejected')}><span className={o.flagged && o.flag_reason === 'rejects' ? 'q-hot' : ''}>{pct(o.reject_rate)}</span> <span className="muted">· {nf.format(o.rejected)}</span></td>
                    <td className="num c-hide" data-l={t('q.th.edited')}>{nf.format(o.edited)}</td>
                    <td className="num c-hide" data-l={t('q.th.verified')}>{pct(o.coverage)}</td>
                    <td className="num" data-l={t('q.th.disagreed')}>{o.disagreed ? <span className={o.flagged && o.flag_reason === 'disagree' ? 'q-hot' : ''}>{nf.format(o.disagreed)} · {pct(o.disagree_rate, 1)}</span> : <span className="muted">0</span>}</td>
                    <td className="c-acts"><span className={`btn xs ${o.flagged ? 'primary' : ''}`}>{t(o.flagged ? 'q.review' : 'act.open')}</span></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="card pad q-loop">
            <h2>{t('q.loop')}</h2>
            <p className="muted small">{t('q.loopLead')}</p>
            <ol className="q-steps">
              {steps.map(i => <li key={i}><span className="n">{i}</span><b>{t(`q.s${i}`)}</b><span className="muted small">{t(`q.s${i}d`)}</span></li>)}
            </ol>
          </div>
        </>
      )}
    </div>
  );
}

import { useEffect, useState } from 'react';
import { api } from '../api';
import { useI18n } from '../i18n';
import type { RuleType } from '../types';
import { Icon } from '../ui';

// codes the live mode can raise: ml/live.py (desk_findings: T01/T02/T03/T16, detector conditions: T05/T13/T14/T15)
const LIVE_CODES = new Set(['T01', 'T02', 'T03', 'T05', 'T13', 'T14', 'T15', 'T16']);

export default function RulesPage() {
  const { t, lang, typeName, typeField, docName, pointName, docUrl, has } = useI18n();
  const [data, setData] = useState<{ types: RuleType[]; sources: Record<string, { url?: string; label?: string; short?: string }> } | null>(null);
  const [err, setErr] = useState('');
  useEffect(() => { api<typeof data>('/ui/api/rules').then(setData).catch(e => setErr((e as Error).message)); }, []);
  return (
    <div className="page">
      <div className="page-head"><div><h1>{t('rules.title')}</h1><p>{t('rules.lead')}</p></div></div>
      <div className="card">
        {err ? <div className="empty"><b>{t('rules.loadErr')}</b>{err}</div> : !data ? <div className="empty">{t('loading')}</div> : (
          <div style={{ overflowX: 'auto' }}>
            <table className="table rules-table">
              <thead><tr><th>{t('th.code')}</th><th>{t('th.violation')}</th><th>{t('th.looks')}</th><th>{t('th.regulation')}</th><th>{t('th.live')}</th></tr></thead>
              <tbody>
                {data.types.map(ty => (
                  <tr key={ty.code}>
                    <td><span className="code">{ty.code}</span></td>
                    <td><b>{typeName(ty.code, ty.type)}</b><div style={{ marginTop: 6 }}><span className={`kind ${ty.norm_kind || 'direct'}`}>{has(`kind.${ty.norm_kind || 'direct'}`) ? t(`kind.${ty.norm_kind || 'direct'}`) : ty.norm_kind}</span></div></td>
                    <td className="vis">{typeField(ty.code, 'visual', ty.visual)}</td>
                    <td style={{ fontSize: 13 }}>
                      {ty.refs?.length ? ty.refs.map((r, i) => (
                        <div key={i} style={{ marginBottom: 8 }}>
                          {r.point && <b>{pointName(r.point)} - </b>}{docName(r)}{r.url && <> <a href={docUrl(r.url)} target="_blank" rel="noopener" aria-label={t('f.openAdilet')}><Icon id="link" /></a></>}
                          {r.quote ? <div className="muted"><q lang="ru">{r.quote}</q>{lang !== 'ru' && t('f.quoteRu') ? <> ({t('f.quoteRu')})</> : null}</div>
                            : r.paraphrase ? <div className="muted"><span lang="ru">{r.paraphrase}</span> ({t('f.paraphrase')})</div> : null}
                        </div>
                      )) : <span className="muted">{t('f.noPublic')}</span>}
                      {typeField(ty.code, 'caveat', ty.caveat) && <div className="caveat">{typeField(ty.code, 'caveat', ty.caveat)}</div>}
                    </td>
                    <td>{LIVE_CODES.has(ty.code) ? <span className="pill ok">{t('yes')}</span> : <span className="muted">{t('rules.recordings')}</span>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
      {data && <p className="muted small" style={{ marginTop: 12 }}>{t('rules.sources')} {Object.values(data.sources).filter(s => s.url).map((s, i) => <span key={i}>{i > 0 && ' · '}<a href={s.url} target="_blank" rel="noopener">{s.label || s.short}</a></span>)}</p>}
    </div>
  );
}

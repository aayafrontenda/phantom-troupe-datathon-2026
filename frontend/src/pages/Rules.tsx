import { ExternalLink } from 'lucide-react';
import type { ReactNode } from 'react';
import { KindLabel } from '../components/finding';
import { EmptyState, Loading, Page, PageHeader } from '../components/page';
import { Badge } from '../components/ui/badge';
import { Card } from '../components/ui/card';
import { useI18n } from '../i18n';
import { useRules } from '../lib/rules';
import type { RuleType } from '../types';

const LIVE_CODES = new Set(['T01', 'T02', 'T03', 'T05', 'T13', 'T14', 'T15', 'T16']);

const th = 'px-4 py-3 text-left text-xs font-semibold text-muted-foreground';
const td = 'px-4 py-3.5 align-top';
const link = 'inline-flex items-center gap-1 underline decoration-border-strong underline-offset-[3px] hover:decoration-foreground';

export default function RulesPage() {
  const { t, lang, typeName, typeField, docName, pointName, docUrl } = useI18n();
  const { data, error } = useRules();

  const regulation = (ty: RuleType): ReactNode => (
    <div className="flex flex-col gap-2 text-[13px]">
      {ty.refs?.length ? ty.refs.map((r, i) => (
        <div key={i}>
          {r.point && <b className="font-semibold">{pointName(r.point)} - </b>}{docName(r)}
          {r.url && <> <a href={docUrl(r.url)} target="_blank" rel="noopener" aria-label={t('f.openAdilet')} className={link}><ExternalLink className="size-3.5" /></a></>}
          {r.quote ? <div className="text-muted-foreground"><q lang="ru">{r.quote}</q>{lang !== 'ru' && t('f.quoteRu') ? <> ({t('f.quoteRu')})</> : null}</div>
            : r.paraphrase ? <div className="text-muted-foreground"><span lang="ru">{r.paraphrase}</span> ({t('f.paraphrase')})</div> : null}
        </div>
      )) : <span className="text-muted-foreground">{t('f.noPublic')}</span>}
      {typeField(ty.code, 'caveat', ty.caveat) && <div className="text-xs text-warning">{typeField(ty.code, 'caveat', ty.caveat)}</div>}
    </div>
  );
  const live = (ty: RuleType) => LIVE_CODES.has(ty.code) ? <Badge variant="success">{t('yes')}</Badge> : <span className="text-muted-foreground">{t('rules.recordings')}</span>;
  const code = (ty: RuleType) => <Badge variant="secondary" className="tracking-wider">{ty.code}</Badge>;

  return (
    <Page>
      <PageHeader title={t('rules.title')} lead={t('rules.lead')} />
      <Card>
        {error ? <EmptyState title={t('rules.loadErr')}>{error}</EmptyState> : !data ? <Loading /> : (
          <>

            <table className="hidden w-full text-sm lg:table">
              <thead className="border-b border-border">
                <tr><th className={th}>{t('th.code')}</th><th className={th}>{t('th.violation')}</th><th className={th}>{t('th.looks')}</th><th className={th}>{t('th.regulation')}</th><th className={th}>{t('th.live')}</th></tr>
              </thead>
              <tbody className="divide-y divide-border">
                {data.types.map(ty => (
                  <tr key={ty.code}>
                    <td className={`${td} w-[72px]`}>{code(ty)}</td>
                    <td className={`${td} w-[22%] min-w-[180px]`}><b className="font-semibold">{typeName(ty.code, ty.type)}</b><div className="mt-1.5"><KindLabel kind={ty.norm_kind || 'direct'} /></div></td>
                    <td className={`${td} w-[26%] max-w-[34ch] text-muted-foreground`}>{typeField(ty.code, 'visual', ty.visual)}</td>
                    <td className={td}>{regulation(ty)}</td>
                    <td className={`${td} w-[110px] whitespace-nowrap`}>{live(ty)}</td>
                  </tr>
                ))}
              </tbody>
            </table>

            <ul className="divide-y divide-border lg:hidden">
              {data.types.map(ty => (
                <li key={ty.code} className="flex flex-col gap-3 px-4 py-4 text-sm">
                  <div className="flex flex-wrap items-start gap-x-3 gap-y-1.5">
                    {code(ty)}
                    <div className="min-w-0 flex-1"><b className="font-semibold">{typeName(ty.code, ty.type)}</b><div className="mt-1"><KindLabel kind={ty.norm_kind || 'direct'} /></div></div>
                    <div className="flex shrink-0 items-center gap-1.5 text-xs text-muted-foreground"><span>{t('th.live')}:</span>{live(ty)}</div>
                  </div>
                  <div><div className="mb-1 text-xs font-semibold text-muted-foreground">{t('th.looks')}</div><p className="text-muted-foreground">{typeField(ty.code, 'visual', ty.visual)}</p></div>
                  <div><div className="mb-1 text-xs font-semibold text-muted-foreground">{t('th.regulation')}</div>{regulation(ty)}</div>
                </li>
              ))}
            </ul>
          </>
        )}
      </Card>
      {data && (
        <p className="-mt-2 text-[13px] text-muted-foreground">{t('rules.sources')} {Object.values(data.sources).filter(s => s.url).map((s, i) => (
          <span key={i}>{i > 0 && ' · '}<a href={s.url} target="_blank" rel="noopener" className={link}>{s.label || s.short}</a></span>
        ))}</p>
      )}
    </Page>
  );
}

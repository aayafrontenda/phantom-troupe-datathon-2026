import { useCallback, useEffect, useState } from 'react';
import { api } from '../api';
import { useI18n } from '../i18n';
import { Icon, fmtDate, useUi } from '../ui';

interface TgStatus { enabled: boolean; bot: string | null; linked: boolean; telegram: { username: string | null; linked_at: number } | null; photos: boolean }

/** Rendered by the modal host, which sits outside AuthProvider: the role comes in as a prop. */
export function TelegramDialog({ close, role }: { close: () => void; role: string }) {
  const { t, locale } = useI18n();
  const { toast } = useUi();
  const [st, setSt] = useState<TgStatus | null>(null);
  const [url, setUrl] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try { setSt(await api<TgStatus>('/ui/api/auth/telegram')); } catch { /* keep */ }
  }, []);
  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    if (!url || st?.linked) return;
    const id = setInterval(load, 2000);
    return () => clearInterval(id);
  }, [url, st?.linked, load]);

  useEffect(() => { if (url && st?.linked) { toast(t('tg.done')); setUrl(null); } }, [st?.linked, url, toast, t]);

  const connect = async () => {
    setBusy(true);
    try {
      const r = await api<{ url: string }>('/ui/api/auth/telegram/link', { method: 'POST' });
      setUrl(r.url);
      window.open(r.url, '_blank', 'noopener');
    } catch (e) { toast((e as Error).message, 'err'); }
    finally { setBusy(false); }
  };
  const unlink = async () => {
    setBusy(true);
    try { await api('/ui/api/auth/telegram', { method: 'DELETE' }); toast(t('tg.unlinked')); await load(); }
    catch (e) { toast((e as Error).message, 'err'); }
    finally { setBusy(false); }
  };

  return (
    <div>
      <h3 style={{ display: 'flex', alignItems: 'center', gap: 10 }}><Icon id="tg" />{t('tg.title')}</h3>
      <p>{t('tg.lead')}</p>
      {!st ? <p className="muted" style={{ marginTop: 16 }}>{t('loading')}</p> : !st.enabled ? (
        <div className="note" style={{ margin: '16px 0 0' }}><Icon id="alert" /><span>{t('tg.off')}</span></div>
      ) : (
        <>
          <div className="tg-what"><b>{t('tg.youGet')}</b><span>{t(`tg.what.${role}`)}</span></div>
          {!st.photos && <p className="muted small" style={{ marginTop: 10 }}>{t('tg.noPhotos')}</p>}
          {st.linked ? (
            <div className="tg-state ok">
              <span className="pill ok"><Icon id="check" />{t('tg.linked', { u: st.telegram?.username ? '@' + st.telegram.username : 'Telegram' })}</span>
              {st.telegram?.linked_at && <span className="muted small">{t('tg.since', { d: fmtDate(st.telegram.linked_at, locale) })}</span>}
            </div>
          ) : url ? (
            <div className="tg-state">
              <span className="pill info"><Icon id="clock" />{t('tg.waiting')}</span>
              <a href={url} target="_blank" rel="noopener noreferrer" className="small">{t('tg.openAgain')}</a>
            </div>
          ) : (
            <p className="muted small" style={{ marginTop: 14 }}>{t('tg.step', { bot: st.bot ? '@' + st.bot : 'PhantomGuard' })}</p>
          )}
        </>
      )}
      <div className="acts">
        {st?.enabled && st.linked && <button className="btn sm danger" disabled={busy} onClick={unlink}>{t('tg.unlink')}</button>}
        <button className="btn sm" onClick={close}>{t('close')}</button>
        {st?.enabled && !st.linked && <button className="btn sm primary" disabled={busy} onClick={connect}><Icon id="tg" />{t(url ? 'tg.newLink' : 'tg.connect')}</button>}
      </div>
    </div>
  );
}

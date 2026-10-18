import { Check, Clock, Send } from 'lucide-react';
import { useCallback, useEffect, useState } from 'react';
import { api } from '../api';
import { useI18n } from '../i18n';
import { fmtDate, useUi } from '../ui';
import { Note } from './page';
import { Badge } from './ui/badge';
import { Button } from './ui/button';
import { DialogDescription, DialogFooter, DialogTitle } from './ui/dialog';

interface TgStatus { enabled: boolean; bot: string | null; linked: boolean; telegram: { username: string | null; linked_at: number } | null; photos: boolean }

export function TelegramDialog({ close, role }: { close: () => void; role: string }) {
  const { t, locale } = useI18n();
  const { toast } = useUi();
  const [st, setSt] = useState<TgStatus | null>(null);
  const [url, setUrl] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try { setSt(await api<TgStatus>('/ui/api/auth/telegram')); } catch {}
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
      <DialogTitle><Send className="size-[18px]" strokeWidth={1.8} />{t('tg.title')}</DialogTitle>
      <DialogDescription>{t('tg.lead')}</DialogDescription>
      {!st ? <p className="mt-4 text-sm text-muted-foreground">{t('loading')}</p> : !st.enabled ? (
        <Note className="mt-4">{t('tg.off')}</Note>
      ) : (
        <>
          <div className="mt-4 flex flex-col gap-1 rounded-[10px] bg-muted px-4 py-3.5 text-sm"><b className="text-heading">{t('tg.youGet')}</b><span>{t(`tg.what.${role}`)}</span></div>
          {!st.photos && <p className="mt-2.5 text-[13px] text-muted-foreground">{t('tg.noPhotos')}</p>}
          {st.linked ? (
            <div className="mt-3.5 flex flex-wrap items-center gap-3">
              <Badge variant="success"><Check />{t('tg.linked', { u: st.telegram?.username ? '@' + st.telegram.username : 'Telegram' })}</Badge>
              {st.telegram?.linked_at && <span className="text-[13px] text-muted-foreground">{t('tg.since', { d: fmtDate(st.telegram.linked_at, locale) })}</span>}
            </div>
          ) : url ? (
            <div className="mt-3.5 flex flex-wrap items-center gap-3">
              <Badge variant="info"><Clock />{t('tg.waiting')}</Badge>
              <a href={url} target="_blank" rel="noopener noreferrer" className="text-[13px] underline decoration-border-strong hover:decoration-foreground">{t('tg.openAgain')}</a>
            </div>
          ) : (
            <p className="mt-3.5 text-[13px] text-muted-foreground">{t('tg.step', { bot: st.bot ? '@' + st.bot : 'PhantomGuard' })}</p>
          )}
        </>
      )}
      <DialogFooter>
        {st?.enabled && st.linked && <Button variant="destructive" size="sm" disabled={busy} onClick={unlink}>{t('tg.unlink')}</Button>}
        <Button variant="secondary" size="sm" onClick={close}>{t('close')}</Button>
        {st?.enabled && !st.linked && <Button size="sm" disabled={busy} onClick={connect}><Send />{t(url ? 'tg.newLink' : 'tg.connect')}</Button>}
      </DialogFooter>
    </div>
  );
}

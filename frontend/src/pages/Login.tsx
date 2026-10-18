import { AlertTriangle, Moon, Sun } from 'lucide-react';
import { useState, type FormEvent } from 'react';
import { useAuth } from '../auth';
import { Mark, Rosette } from '../components/Guilloche';
import { Button } from '../components/ui/button';
import { Input, Label, PasswordInput } from '../components/ui/input';
import { Segmented } from '../components/ui/segmented';
import { LANGS, useI18n, type Lang } from '../i18n';
import { useTheme } from '../ui';

export default function LoginPage() {
  const { t, lang, setLang } = useI18n();
  const { login } = useAuth();
  const { dark, toggle } = useTheme();
  const [u, setU] = useState('');
  const [p, setP] = useState('');
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setErr(''); setBusy(true);
    try { await login(u.trim(), p); }
    catch { setErr(t('login.err')); }
    finally { setBusy(false); }
  };

  return (
    <div className="grid h-dvh overflow-y-auto bg-background xl:grid-cols-[minmax(0,1.15fr)_minmax(380px,1fr)]">

      <section className="relative flex min-h-[220px] flex-col justify-between overflow-hidden bg-foreground px-6 py-7 text-background md:min-h-[280px] xl:px-12 xl:py-10">
        <Rosette className="absolute top-[60%] left-[72%] aspect-square w-[620px] -translate-x-1/2 -translate-y-1/2 animate-turn text-background will-change-[rotate] xl:top-[38%] xl:left-[64%] xl:w-[min(82vh,760px)]" />
        <div className="relative flex items-center gap-2.5"><Mark size={30} className="text-background" dotClassName="fill-salmon" /><b className="text-xl font-semibold tracking-tight">PhantomGuard</b></div>
        <div>
          <p className="relative max-w-[20ch] text-[26px] leading-[1.08] font-semibold tracking-tight text-background md:text-[clamp(28px,3.2vw,44px)]">{t('login.claim')}</p>
          <p className="relative mt-3.5 hidden max-w-[42ch] text-[15px] text-background/70 md:block">{t('login.claimSub')}</p>
        </div>
      </section>
      <main className="grid place-items-center p-8">
        <form className="w-[min(400px,100%)]" onSubmit={submit}>
          <h1 className="mb-1.5 text-[26px] font-semibold tracking-tight">{t('login.title')}</h1>
          <p className="mb-6 text-muted-foreground">{t('login.lead')}</p>
          <div className="flex flex-col gap-3.5">
            <div>
              <Label htmlFor="login">{t('login.login')}</Label>
              <Input id="login" autoComplete="username" autoFocus value={u} onChange={e => setU(e.target.value)} required />
            </div>
            <div>
              <Label htmlFor="password">{t('login.password')}</Label>
              <PasswordInput id="password" autoComplete="current-password" value={p} onChange={e => setP(e.target.value)} required showLabel={t('pw.show')} hideLabel={t('pw.hide')} />
            </div>
            {err && <div className="flex items-center gap-2 text-sm text-destructive" role="alert"><AlertTriangle className="size-[18px] shrink-0" strokeWidth={1.7} />{err}</div>}
            <Button type="submit" size="lg" className="mt-1.5 w-full" disabled={busy}>{t(busy ? 'login.busy' : 'login.btn')}</Button>
          </div>
          <div className="mt-5 flex items-center justify-between gap-3 border-t border-border pt-4">
            <small className="text-[13px] text-muted-foreground">{t('login.hint')}</small>
            <span className="flex shrink-0 items-center gap-2">
              <Segmented size="sm" value={lang} onChange={setLang} aria-label={t('lang')}
                options={(Object.keys(LANGS) as Lang[]).map(l => ({ value: l, label: LANGS[l].label, lang: l }))} />
              <Button type="button" variant="outline" size="icon-sm" onClick={toggle} aria-label={t('theme')}>{dark ? <Sun /> : <Moon />}</Button>
            </span>
          </div>
        </form>
      </main>
    </div>
  );
}

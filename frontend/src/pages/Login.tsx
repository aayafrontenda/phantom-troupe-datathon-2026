import { useState, type FormEvent } from 'react';
import { useAuth } from '../auth';
import { LANGS, useI18n, type Lang } from '../i18n';
import { Icon, useTheme } from '../ui';

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
    <div className="login">
      <form className="login-card" onSubmit={submit}>
        <div className="brand"><b style={{ fontSize: 28, color: 'var(--brand)', fontWeight: 700, letterSpacing: '-.03em' }}>CashGuard</b></div>
        <h1>{t('login.title')}</h1>
        <p>{t('login.lead')}</p>
        <div className="form">
          <div>
            <label className="lbl" htmlFor="login">{t('login.login')}</label>
            <input id="login" className="field" autoComplete="username" autoFocus value={u} onChange={e => setU(e.target.value)} required />
          </div>
          <div>
            <label className="lbl" htmlFor="password">{t('login.password')}</label>
            <input id="password" className="field" type="password" autoComplete="current-password" value={p} onChange={e => setP(e.target.value)} required />
          </div>
          {err && <div className="err" role="alert">{err}</div>}
          <button className="btn primary lg wide" type="submit" disabled={busy}>{t('login.btn')}</button>
        </div>
        <div className="foot">
          <small className="muted">{t('login.hint')}</small>
          <span className="row">
            <span className="lang-sw" role="group" aria-label={t('lang')}>
              {(Object.keys(LANGS) as Lang[]).map(l => <button type="button" key={l} className={l === lang ? 'on' : ''} onClick={() => setLang(l)}>{LANGS[l].label}</button>)}
            </span>
            <button type="button" className="icon-btn outline" onClick={toggle} aria-label={t('theme')}><Icon id={dark ? 'sun' : 'moon'} /></button>
          </span>
        </div>
      </form>
    </div>
  );
}

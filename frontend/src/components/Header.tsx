import { useEffect, useRef, useState } from 'react';
import { NavLink } from 'react-router-dom';
import { api } from '../api';
import { useAuth } from '../auth';
import { LANGS, useI18n, type Lang } from '../i18n';
import { Icon, useTheme } from '../ui';
import { useOpenCount } from './events';

interface Health { analyzer: string; queue: number; running: string[]; version: string }

export default function Header() {
  const { t, lang, setLang } = useI18n();
  const { user, logout, can } = useAuth();
  const { dark, toggle } = useTheme();
  const [health, setHealth] = useState<Health | null | 'down'>(null);
  const [menu, setMenu] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);
  const openCount = useOpenCount();

  useEffect(() => {
    let alive = true;
    const tick = async () => {
      try { const h = await api<Health>('/health'); if (alive) setHealth(h); }
      catch { if (alive) setHealth('down'); }
    };
    tick();
    const id = setInterval(tick, 5000);
    return () => { alive = false; clearInterval(id); };
  }, []);

  useEffect(() => {
    if (!menu) return;
    const close = (e: MouseEvent) => { if (!menuRef.current?.contains(e.target as Node)) setMenu(false); };
    document.addEventListener('mousedown', close);
    return () => document.removeEventListener('mousedown', close);
  }, [menu]);

  const busy = health && health !== 'down' ? health.running.length > 0 : false;
  const statusCls = health === 'down' ? 'bad' : busy ? 'busy' : health ? 'ok' : '';
  const statusText = health === 'down' ? t('status.down') : !health ? t('status.connecting')
    : busy ? t('status.busy', { n: health.queue }) : t('status.ready', { model: t(health.analyzer === 'mock' ? 'status.demo' : 'status.local') });
  const tab = (to: string, label: string, badge?: number) => (
    <NavLink to={to} className={({ isActive }) => `tab ${isActive ? 'on' : ''}`}>{label}{badge ? <span className="badge">{badge}</span> : null}</NavLink>
  );
  const initials = (user?.name || '?').split(/\s+/).map(x => x[0]).slice(0, 2).join('').toUpperCase();

  return (
    <header className="top">
      <NavLink className="brand" to="/"><b>CashGuard</b></NavLink>
      <nav className="tabs" aria-label={t('nav.sections')}>
        {tab('/live', t('nav.live'), openCount)}
        {tab('/checks', t('nav.checks'))}
        {can('supervisor') && tab('/review', t('nav.review'))}
        {tab('/rules', t('nav.rules'))}
        {can('admin') && tab('/admin', t('nav.admin'))}
      </nav>
      <div className="top-right">
        <span className={`status ${statusCls}`} title={health && health !== 'down' ? t('status.tip', { a: health.analyzer, v: health.version }) : ''}>
          <i className="dot" /><span>{statusText}</span>
        </span>
        <div className="lang-sw" role="group" aria-label={t('lang')}>
          {(Object.keys(LANGS) as Lang[]).map(l => (
            <button key={l} lang={l} className={l === lang ? 'on' : ''} aria-pressed={l === lang} onClick={() => setLang(l)}>{LANGS[l].label}</button>
          ))}
        </div>
        <button className="icon-btn outline" onClick={toggle} aria-label={t('theme')} title={t('theme')}><Icon id={dark ? 'sun' : 'moon'} /></button>
        <div style={{ position: 'relative' }} ref={menuRef}>
          <button className="user-chip" onClick={() => setMenu(m => !m)} aria-haspopup="menu" aria-expanded={menu}>
            <span><b>{user?.name}</b><small>{t(user?.kind === 'anon' ? 'role.anon' : `role.${user?.role}`)}</small></span>
            <span className="av">{initials}</span>
          </button>
          {menu && (
            <div className="user-menu" role="menu">
              <div style={{ padding: '6px 12px 10px', color: 'var(--muted)', fontSize: 13 }}>{t('signedAs')} <b style={{ color: 'var(--fg)' }}>{user?.login}</b></div>
              <button role="menuitem" onClick={() => { setMenu(false); logout(); }}><Icon id="logout" />{t('logout')}</button>
            </div>
          )}
        </div>
      </div>
    </header>
  );
}

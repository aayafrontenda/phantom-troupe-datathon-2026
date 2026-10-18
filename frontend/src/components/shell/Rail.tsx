import { LogOut, Moon, Send, Sun } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { useAuth } from '../../auth';
import { LANGS, useI18n, type Lang } from '../../i18n';
import { cn } from '../../lib/utils';
import { useTheme, useUi } from '../../ui';
import { TelegramDialog } from '../Telegram';
import { Tip } from '../ui/tooltip';
import { Mark } from '../Guilloche';

export const initials = (name?: string) => (name || '?').split(/\s+/).map(x => x[0]).slice(0, 2).join('').toUpperCase();

export function Rail() {
  return (
    <div className="hidden w-[60px] shrink-0 flex-col items-center bg-rail py-3 md:flex">
      <Tip label="PhantomGuard" side="right">
        <Link to="/" aria-label="PhantomGuard" className="grid size-9 place-items-center rounded-lg bg-white/[.07]">
          <Mark size={24} className="text-rail-foreground" />
        </Link>
      </Tip>
      <div className="flex-1" />
      <ProfileMenu />
    </div>
  );
}

export function ProfileMenu({ inline = false }: { inline?: boolean }) {
  const { t, lang, setLang } = useI18n();
  const { user, logout } = useAuth();
  const { dark, toggle } = useTheme();
  const { modal } = useUi();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => { if (!ref.current?.contains(e.target as Node)) setOpen(false); };
    const esc = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false); };
    document.addEventListener('mousedown', close); document.addEventListener('keydown', esc);
    return () => { document.removeEventListener('mousedown', close); document.removeEventListener('keydown', esc); };
  }, [open]);
  const role = t(user?.kind === 'anon' ? 'role.anon' : `role.${user?.role}`);
  return (
    <div ref={ref} className="relative">
      <Tip label={open ? null : `${user?.name} · ${role}`} side="right">
        <button onClick={() => setOpen(o => !o)} aria-haspopup="menu" aria-expanded={open} aria-label={user?.name}
          className={cn('relative grid size-9 place-items-center rounded-lg text-[12px] font-semibold tracking-wide transition-transform active:scale-95',
            inline ? 'bg-foreground text-background' : 'bg-rail-foreground text-rail')}>
          {initials(user?.name)}
          <span aria-hidden="true" className={cn('absolute -right-0.5 -bottom-0.5 size-2.5 rounded-full bg-success ring-2', inline ? 'ring-card' : 'ring-rail')} />
        </button>
      </Tip>
      {open && (
        <div role="menu" className={cn('absolute z-30 w-64 rounded-xl border border-border bg-popover p-1.5 text-sm shadow-sm [animation:pop-in_.16s_var(--ease-out)]',
          inline ? 'right-0 top-11' : 'bottom-0 left-12')}>
          <div className="px-2.5 pt-1.5 pb-2.5">
            <div className="font-semibold text-heading">{user?.name}</div>
            <div className="text-xs text-muted-foreground">{role}</div>
            <div className="mt-1 text-xs text-muted-foreground">{t('signedAs')} <b className="font-medium text-foreground">{user?.login}</b></div>
          </div>
          <div className="border-t border-border px-2.5 py-2.5">
            <div className="mb-1.5 text-xs text-muted-foreground">{t('lang')}</div>
            <div className="flex gap-1 rounded-lg bg-muted p-0.5" role="group" aria-label={t('lang')}>
              {(Object.keys(LANGS) as Lang[]).map(l => (
                <button key={l} lang={l} aria-pressed={l === lang} onClick={() => setLang(l)}
                  className={cn('h-7 flex-1 rounded-md text-xs font-semibold transition-colors', l === lang ? 'bg-card text-foreground shadow-sm' : 'text-muted-foreground hover:text-foreground')}>
                  {LANGS[l].label}
                </button>
              ))}
            </div>
          </div>
          <div className="border-t border-border pt-1.5">
            <button role="menuitem" onClick={toggle} className="flex w-full items-center gap-2.5 rounded-md px-2.5 py-2 text-left hover:bg-accent">
              {dark ? <Sun className="size-4 text-muted-foreground" /> : <Moon className="size-4 text-muted-foreground" />}{t('theme')}
            </button>
            {user && user.kind === 'user' && user.role !== 'admin' && (
              <button role="menuitem" onClick={() => { setOpen(false); modal<null>(close => <TelegramDialog role={user.role} close={() => close(null)} />); }}
                className="flex w-full items-center gap-2.5 rounded-md px-2.5 py-2 text-left hover:bg-accent">
                <Send className="size-4 text-muted-foreground" />{t('tg.menu')}
              </button>
            )}
            <button role="menuitem" onClick={() => { setOpen(false); logout(); }} className="flex w-full items-center gap-2.5 rounded-md px-2.5 py-2 text-left hover:bg-accent">
              <LogOut className="size-4 text-muted-foreground" />{t('logout')}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

/* Collapsible main sidebar: the sections (former top tabs) with the open-findings badge. */
import { PanelLeftClose } from 'lucide-react';
import { NavLink, useLocation } from 'react-router-dom';
import { useAuth } from '../../auth';
import { useI18n } from '../../i18n';
import { cn } from '../../lib/utils';
import { useOpenCount } from '../events';
import { Button } from '../ui/button';
import { Tip } from '../ui/tooltip';
import { NAV, section } from './state';

export function SidebarNav({ onCollapse, onNavigate, className }: { onCollapse?: () => void; onNavigate?: () => void; className?: string }) {
  const { t } = useI18n();
  const { can } = useAuth();
  const open = useOpenCount();
  const sec = section(useLocation().pathname);

  return (
    <aside className={cn('flex w-60 shrink-0 flex-col border-r border-border bg-sidebar', className)}>
      <div className="flex h-[52px] items-center gap-2 border-b border-border pr-2 pl-4">
        <div className="min-w-0 flex-1 truncate text-[15px] font-semibold text-heading">PhantomGuard</div>
        {onCollapse && (
          <Tip label={t('sb.collapse')}>
            <Button variant="ghost" size="icon-sm" onClick={onCollapse} aria-label={t('sb.collapse')}><PanelLeftClose /></Button>
          </Tip>
        )}
      </div>
      <nav aria-label={t('nav.sections')} className="min-h-0 flex-1 overflow-y-auto px-2.5 py-3">
        <ul className="flex flex-col gap-0.5">
          {NAV.filter(n => !n.need || can(n.need)).map(n => {
            const on = n.match.includes(sec);
            const badge = n.badge === 'open' ? open : 0;
            return (
              <li key={n.to}>
                <NavLink to={n.to} onClick={onNavigate} aria-current={on ? 'page' : undefined}
                  className={cn('group flex h-8 items-center gap-2.5 rounded-md px-2.5 text-sm transition-colors duration-150',
                    on ? 'bg-card font-medium text-foreground shadow-sm ring-1 ring-border' : 'text-muted-foreground hover:bg-accent hover:text-foreground')}>
                  <n.icon className={cn('size-4 shrink-0', on ? 'text-primary' : 'text-faint group-hover:text-muted-foreground')} strokeWidth={1.9} />
                  <span className="flex-1 truncate">{t(n.label)}</span>
                  {badge > 0 && <span className="min-w-5 rounded-md bg-primary px-1.5 text-center text-[11px] leading-5 font-semibold text-primary-foreground tabular-nums">{badge}</span>}
                </NavLink>
              </li>
            );
          })}
        </ul>
      </nav>
    </aside>
  );
}

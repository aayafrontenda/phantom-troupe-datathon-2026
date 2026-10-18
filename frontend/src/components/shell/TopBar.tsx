import { ChevronRight, Menu, PanelLeftOpen } from 'lucide-react';
import { Link, useLocation } from 'react-router-dom';
import { useI18n } from '../../i18n';
import { Button } from '../ui/button';
import { Tip } from '../ui/tooltip';
import { NAV, section } from './state';

export function TopBar({ collapsed, onExpand, onMenu }: { collapsed: boolean; onExpand: () => void; onMenu: () => void }) {
  const { t } = useI18n();
  const loc = useLocation();
  const item = NAV.find(n => n.match.includes(section(loc.pathname)));
  const deep = loc.pathname.split('/').filter(Boolean).length > 1;

  return (
    <header className="flex h-[52px] shrink-0 items-center gap-2 border-b border-border bg-card px-3 sm:px-4">
      <a className="skip" href="#main">{t('skip')}</a>
      <Button variant="ghost" size="icon-sm" className="md:hidden" onClick={onMenu} aria-label={t('sb.menu')}><Menu /></Button>
      {collapsed && (
        <Tip label={t('sb.expand')}>
          <Button variant="ghost" size="icon-sm" className="hidden md:inline-flex" onClick={onExpand} aria-label={t('sb.expand')}><PanelLeftOpen /></Button>
        </Tip>
      )}
      <nav aria-label="breadcrumb" className="min-w-0 flex-1">
        <ol className="flex min-w-0 items-center gap-1 text-sm">
          <li className="hidden text-muted-foreground sm:block">PhantomGuard</li>
          {item && <>
            <li aria-hidden="true" className="hidden text-faint sm:block"><ChevronRight className="size-3.5" /></li>
            <li className="min-w-0 truncate">
              {deep ? <Link to={item.to} className="text-muted-foreground transition-colors hover:text-foreground">{t(item.label)}</Link>
                : <span aria-current="page" className="font-medium text-foreground">{t(item.label)}</span>}
            </li>
          </>}
        </ol>
      </nav>
    </header>
  );
}

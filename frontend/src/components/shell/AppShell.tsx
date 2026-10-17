/* App shell: 100vh, no window scroll. Rail | collapsible sidebar | (top bar + the only scrolling area). */
import { useCallback, useState, type ReactNode } from 'react';
import { useLocation } from 'react-router-dom';
import { useI18n } from '../../i18n';
import { Sheet, SheetContent, SheetTitle } from '../ui/sheet';
import { TooltipProvider } from '../ui/tooltip';
import { ProfileMenu, Rail } from './Rail';
import { SidebarNav } from './SidebarNav';
import { TopBar } from './TopBar';

const KEY = 'cg_sidebar';

export function AppShell({ children }: { children: ReactNode }) {
  const { t } = useI18n();
  const loc = useLocation();
  const [collapsed, setCollapsedState] = useState(() => { try { return localStorage.getItem(KEY) === 'collapsed'; } catch { return false; } });
  const [mobile, setMobile] = useState(false);

  const setCollapsed = useCallback((c: boolean) => {
    setCollapsedState(c);
    try { localStorage.setItem(KEY, c ? 'collapsed' : 'open'); } catch { /* ignore */ }
  }, []);

  return (
    <TooltipProvider delayDuration={300} skipDelayDuration={200}>
        <div className="flex h-dvh overflow-hidden bg-background text-foreground">
          <Rail />
          <div className={`hidden overflow-hidden transition-[width] duration-200 ease-out md:block ${collapsed ? 'w-0' : 'w-60'}`} aria-hidden={collapsed || undefined} inert={collapsed || undefined}>
            <SidebarNav className="h-full" onCollapse={() => setCollapsed(true)} />
          </div>
          <div className="flex min-w-0 flex-1 flex-col">
            <TopBar collapsed={collapsed} onExpand={() => setCollapsed(false)} onMenu={() => setMobile(true)} />
            <main id="main" key={loc.pathname.split('/')[1]} className="flex-1 overflow-y-auto p-4 sm:p-6">{children}</main>
          </div>
        </div>
        <Sheet open={mobile} onOpenChange={setMobile}>
          <SheetContent side="left" className="w-72 p-0" closeLabel={t('close')} aria-describedby={undefined}>
            <SheetTitle className="sr-only">{t('sb.menu')}</SheetTitle>
            <SidebarNav className="h-full w-full border-r-0" onNavigate={() => setMobile(false)} />
            <div className="absolute right-14 top-2.5"><ProfileMenu inline /></div>
          </SheetContent>
        </Sheet>
    </TooltipProvider>
  );
}

import { Navigate, Route, Routes } from 'react-router-dom';
import { useAuth } from './auth';
import { EmptyState, Loading, Page } from './components/page';
import { AppShell } from './components/shell/AppShell';
import { Card } from './components/ui/card';
import { UploadProvider } from './components/uploads';
import { useI18n } from './i18n';
import AdminPage from './pages/Admin';
import CheckPage from './pages/Check';
import ChecksPage from './pages/Checks';
import FindingPage from './pages/Finding';
import LivePage from './pages/Live';
import LoginPage from './pages/Login';
import QualityPage from './pages/Quality';
import ReviewPage from './pages/Review';
import RulesPage from './pages/Rules';

const HOME = '/checks';

function Guard({ role, children }: { role: 'operator' | 'supervisor' | 'admin'; children: React.ReactNode }) {
  const { can } = useAuth();
  const { t } = useI18n();
  if (!can(role)) return <Page><Card><EmptyState title={t('err.403')} /></Card></Page>;
  return <>{children}</>;
}

export default function App() {
  const { ready, user } = useAuth();
  if (!ready) return <Loading className="pt-[30vh]" />;
  if (!user) return <LoginPage />;
  return (
    <UploadProvider>
      <AppShell>
        <Routes>
          <Route path="/" element={<Navigate to={HOME} replace />} />
          <Route path="/live" element={<LivePage />} />
          <Route path="/checks" element={<ChecksPage />} />
          <Route path="/checks/:id" element={<CheckPage />} />
          <Route path="/findings/:id" element={<FindingPage />} />
          <Route path="/review" element={<Guard role="supervisor"><ReviewPage /></Guard>} />
          <Route path="/quality" element={<Guard role="supervisor"><QualityPage /></Guard>} />
          <Route path="/rules" element={<RulesPage />} />
          <Route path="/admin" element={<Guard role="admin"><AdminPage /></Guard>} />
          <Route path="*" element={<Navigate to={HOME} replace />} />
        </Routes>
      </AppShell>
    </UploadProvider>
  );
}

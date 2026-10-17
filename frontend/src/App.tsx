import { Navigate, Route, Routes, useLocation } from 'react-router-dom';
import { useAuth } from './auth';
import Header from './components/Header';
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

function Guard({ role, children }: { role: 'operator' | 'supervisor' | 'admin'; children: React.ReactNode }) {
  const { can } = useAuth();
  const { t } = useI18n();
  if (!can(role)) return <div className="page"><div className="card empty"><b>{t('err.403')}</b></div></div>;
  return <>{children}</>;
}

export default function App() {
  const { ready, user } = useAuth();
  const { t } = useI18n();
  const loc = useLocation();
  if (!ready) return <div className="loading">{t('loading')}</div>;
  if (!user) return <LoginPage />;
  const home = user.role === 'supervisor' ? '/review' : '/live';
  return (
    <UploadProvider>
      <Header />
      <main key={loc.pathname.split('/')[1]}>
        <Routes>
          <Route path="/" element={<Navigate to={home} replace />} />
          <Route path="/live" element={<LivePage />} />
          <Route path="/checks" element={<ChecksPage />} />
          <Route path="/checks/:id" element={<CheckPage />} />
          <Route path="/findings/:id" element={<FindingPage />} />
          <Route path="/review" element={<Guard role="supervisor"><ReviewPage /></Guard>} />
          <Route path="/quality" element={<Guard role="supervisor"><QualityPage /></Guard>} />
          <Route path="/rules" element={<RulesPage />} />
          <Route path="/admin" element={<Guard role="admin"><AdminPage /></Guard>} />
          <Route path="*" element={<Navigate to={home} replace />} />
        </Routes>
      </main>
    </UploadProvider>
  );
}

import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import App from './App';
import { AuthProvider } from './auth';
import { I18nProvider } from './i18n';
import './styles/index.css';
import { UiProvider } from './ui';

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <I18nProvider>
      <UiProvider>
        <AuthProvider>
          <BrowserRouter>
            <App />
          </BrowserRouter>
        </AuthProvider>
      </UiProvider>
    </I18nProvider>
  </StrictMode>,
);

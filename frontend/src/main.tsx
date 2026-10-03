import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router'
import './index.css'
import App from './App.tsx'

import * as Sentry from '@sentry/react';
import { initSentry } from './lib/sentry';

initSentry(import.meta.env.VITE_SENTRY_DSN);

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <Sentry.ErrorBoundary fallback={<p role="alert">Something went wrong. Reload the page.</p>}>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </Sentry.ErrorBoundary>
  </StrictMode>,
)

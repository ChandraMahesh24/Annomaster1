import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { App } from './App';
import { ThemeProvider } from './theme/ThemeProvider';

// The ORIGINAL app's stylesheets, ported verbatim, in the same cascade order.
// This is what makes the React port look like the Flask app (both themes).
import './theme/ported/tokens.css';
import './theme/ported/base.css';
import './theme/ported/layout.css';
import './theme/ported/workspace.css';
import './theme/ported/dashboard.css';
import './theme/ported/settings.css';
import './theme/ported/upload.css';
import './theme/ported/main.css';         // annotator engine styles
import './theme/ported/annotate-v2.css';  // annotator override layer
import './react-glue.css';                // small React-only additions
// Bridge: the not-yet-rewired pages (Login/Dashboard/Members/Settings) still use
// first-pass classes. Loaded LAST so it overrides only where those pages need
// it; removed screen-by-screen as each is rewired to the original markup (U1/U3).
import './app.css';

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false } },
});

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <App />
      </ThemeProvider>
    </QueryClientProvider>
  </StrictMode>,
);

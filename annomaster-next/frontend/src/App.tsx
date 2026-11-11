import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import { RequireAuth } from './components/RequireAuth';
import { Dashboard } from './routes/Dashboard';
import { Login } from './routes/Login';
import { Register } from './routes/Register';
import { Members } from './routes/Members';
import { Settings } from './routes/Settings';
import { Workspace } from './routes/Workspace';

/**
 * Router. The original app's hash tabs become real routes. Every authed route
 * is wrapped in RequireAuth. The annotator (/…/annotate) lands in C3.
 */
export function App() {
  const authed = (el: JSX.Element) => <RequireAuth>{el}</RequireAuth>;
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/register" element={<Register />} />
        <Route path="/" element={authed(<Dashboard />)} />
        <Route path="/settings" element={authed(<Settings />)} />
        <Route path="/w/:wid/members" element={authed(<Members />)} />
        {/* The project workspace = the annotate.html SPA: one shell, 6 hash sections */}
        <Route path="/w/:wid/p/:project" element={authed(<Workspace />)} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  );
}

import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useRegister } from '../api/auth';
import { ApiError } from '../api/client';
import './register.css';

/** Register — faithful port of auth/register.html: the split promo/form panel
 *  (.auth-left steps + .auth-right form). Styled by the extracted register.css. */
export function Register() {
  const [email, setEmail] = useState('');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [err, setErr] = useState('');
  const reg = useRegister();
  const nav = useNavigate();

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setErr('');
    if (password.length < 8) { setErr('Password must be at least 8 characters'); return; }
    try { await reg.mutateAsync({ email, username, password }); nav('/', { replace: true }); }
    catch (e) { setErr(e instanceof ApiError ? e.message : 'Registration failed'); }
  }

  const steps = [
    ['Create your account', 'Free forever, no credit card'],
    ['Create a workspace', 'Invite your team, set roles'],
    ['Start annotating', 'Upload images, export YOLO datasets'],
  ];

  return (
    <div className="register-page">
      <div className="auth-left">
        <div className="auth-left-logo"><i className="fas fa-crosshairs" /></div>
        <div className="auth-left-brand">Anno<span>Master</span></div>
        <p className="auth-left-tagline">Start annotating in 3 simple steps</p>
        <div className="steps">
          {steps.map(([t, d], i) => (
            <div className="step" key={i}>
              <div className="step-num">{i + 1}</div>
              <div className="step-text"><strong>{t}</strong>{d}</div>
            </div>
          ))}
        </div>
      </div>

      <div className="auth-right">
        <div className="auth-form-wrap">
          <h1 className="auth-form-title">Create your account</h1>
          <p className="auth-form-subtitle">Free forever · No credit card required</p>

          <form onSubmit={onSubmit}>
            <div className="form-group">
              <label className="form-label">Username</label>
              <div className="input-wrap">
                <i className="fas fa-at input-icon" />
                <input className="form-input" type="text" placeholder="johndoe" autoComplete="username" autoFocus
                       value={username} onChange={(e) => setUsername(e.target.value)} />
              </div>
            </div>
            <div className="form-group">
              <label className="form-label">Email</label>
              <div className="input-wrap">
                <i className="fas fa-envelope input-icon" />
                <input className="form-input" type="email" placeholder="you@company.com" autoComplete="email"
                       value={email} onChange={(e) => setEmail(e.target.value)} />
              </div>
            </div>
            <div className="form-group">
              <label className="form-label">Password</label>
              <div className="input-wrap">
                <i className="fas fa-lock input-icon" />
                <input className="form-input" type="password" placeholder="At least 8 characters" autoComplete="new-password"
                       value={password} onChange={(e) => setPassword(e.target.value)} />
              </div>
            </div>
            <div className="form-error">{err}</div>
            <button className="btn-submit" type="submit" disabled={reg.isPending}>
              {reg.isPending ? 'Creating…' : 'Create Account'}
            </button>
          </form>

          <p className="auth-switch">Have an account? <Link to="/login">Sign in</Link></p>
        </div>
      </div>
    </div>
  );
}

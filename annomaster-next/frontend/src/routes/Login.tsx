import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useLogin } from '../api/auth';
import { ApiError } from '../api/client';
import './login.css';

const M = ({ children }: { children: string }) => <span className="msym">{children}</span>;

/**
 * Login — faithful port of auth/login.html: mesh background, floating orbs/chips,
 * the CSS 3-D cube, the animated annotation-preview card, and the glass sign-in
 * form. Styled by the extracted login.css. The decorative particle-canvas JS is
 * intentionally omitted (purely cosmetic); everything else matches.
 */
export function Login() {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [showPw, setShowPw] = useState(false);
  const [err, setErr] = useState('');
  const login = useLogin();
  const nav = useNavigate();

  async function doLogin(e: React.FormEvent) {
    e.preventDefault();
    setErr('');
    try { await login.mutateAsync({ email, password }); nav('/', { replace: true }); }
    catch (e) { setErr(e instanceof ApiError ? e.message : 'Sign in failed'); }
  }

  return (
    <main className="mesh-bg">
      {/* Parallax 3D background (static — no particle JS) */}
      <div id="bg-3d" aria-hidden>
        <div id="orb1" style={{ position: 'absolute', top: -128, left: -128, width: 560, height: 560, borderRadius: '50%', background: 'rgba(0,108,73,.20)', filter: 'blur(60px)' }} />
        <div id="orb2" style={{ position: 'absolute', bottom: -160, right: -128, width: 620, height: 620, borderRadius: '50%', background: 'rgba(124,58,237,.15)', filter: 'blur(60px)' }} />
        <div id="orb3" style={{ position: 'absolute', top: '33%', left: '50%', width: 400, height: 400, borderRadius: '50%', background: 'rgba(0,168,107,.15)', filter: 'blur(60px)' }} />
        <div className="bg-chip glass sh-card" style={{ left: '12%', top: '22%' }}><M>deployed_code</M></div>
        <div className="bg-chip glass sh-card" style={{ left: '82%', top: '18%' }}><M>bubble_chart</M></div>
        <div className="bg-chip glass sh-card" style={{ left: '18%', top: '78%' }}><M>scatter_plot</M></div>
        <div className="bg-chip glass sh-card" style={{ left: '86%', top: '72%' }}><M>polyline</M></div>
        <div id="ring1" style={{ position: 'absolute', top: '14%', right: '28%', width: 96, height: 96, borderRadius: '50%', border: '1px solid rgba(0,108,73,.20)' }} />
        <div id="ring2" style={{ position: 'absolute', bottom: '18%', left: '34%', width: 144, height: 144, borderRadius: '50%', border: '1px solid rgba(124,58,237,.20)' }} />
      </div>

      <div className="page-wrap">
        <header className="page-header">
          <a href="/" className="logo-link">
            <div className="logo-icon sh-glow"><M>hub</M></div>
            <div className="logo-text">
              <span className="logo-name">AnnoMaster</span>
              <span className="logo-sub">AI Platform</span>
            </div>
          </a>
          <div className="status-badge glass-subtle">
            <div className="status-dot-wrap"><span className="status-dot-ring a-ping" /><span className="status-dot" /></div>
            <span className="status-text">All systems operational</span>
          </div>
        </header>

        <div className="main-grid">
          {/* LEFT — hero + cube + preview */}
          <section className="left-section a-fade-up">
            <div>
              <div style={{ display: 'flex', alignItems: 'flex-start', gap: 24, marginTop: 32 }}>
                <div style={{ flex: 1 }}>
                  <h1 className="hero-heading">Build better<br /><span className="text-grad">AI datasets.</span><br />Train better models.</h1>
                  <p className="hero-sub">Enterprise infrastructure for high-precision labeling, quality control, and dataset lifecycle management — trusted by frontier AI teams.</p>
                </div>
                <div className="iso-cube-wrap">
                  <div className="iso-cube">
                    <div className="iso-cube-inner a-spin-3d">
                      <div className="cube-face sh-glow"><div className="cube-grid" /><div className="cube-subj" /></div>
                      <div className="cube-bbox" style={{ transform: 'translateZ(28px)' }}>
                        <span className="cube-bbox-lbl">person · 0.98</span>
                        <span className="cube-corner" style={{ top: -4, left: -4 }} /><span className="cube-corner" style={{ top: -4, right: -4 }} />
                        <span className="cube-corner" style={{ bottom: -4, left: -4 }} /><span className="cube-corner" style={{ bottom: -4, right: -4 }} />
                      </div>
                      <div className="cube-bbox2" style={{ transform: 'translateZ(48px)' }}><span className="cube-bbox2-lbl">object</span></div>
                      <div className="cube-cross"><span className="cross-v" /><span className="cross-h" /></div>
                    </div>
                  </div>
                </div>
              </div>

              <div className="preview-wrap">
                <div className="preview-card glass sh-elegant preserve-3d">
                  <div className="preview-header">
                    <div style={{ display: 'flex', alignItems: 'center' }}>
                      <div className="preview-dots"><span className="dot-r" /><span className="dot-y" /><span className="dot-g" /></div>
                      <span className="preview-fn">dataset_v4.parquet</span>
                    </div>
                    <div className="live-badge"><span className="live-dot a-pulse" />LIVE</div>
                  </div>
                  <div className="anno-canvas">
                    <div className="anno-grid a-grid-fade" />
                    <div className="anno-box a-layer-drift" style={{ left: '14%', top: '20%', width: '30%', height: '44%', borderColor: 'var(--primary)' }}>
                      <span className="anno-lbl" style={{ background: 'var(--primary)' }}>person · 0.98</span>
                    </div>
                    <div className="anno-box a-layer-drift" style={{ right: '12%', top: '30%', width: '28%', height: '36%', borderColor: 'var(--secondary)', animationDelay: '.8s' }}>
                      <span className="anno-lbl" style={{ background: 'var(--secondary)' }}>vehicle · 0.94</span>
                    </div>
                    <div className="anno-scan a-scan" />
                  </div>
                </div>
              </div>
            </div>
            <div className="trust-row">
              <div className="trust-item"><M>groups</M><span>500+ ML teams</span></div>
              <span className="trust-sep" />
              <div className="trust-item"><M>verified_user</M><span>SOC 2 · GDPR · ISO 27001</span></div>
            </div>
          </section>

          {/* RIGHT — sign-in card */}
          <section className="right-section a-fade-up" style={{ animationDelay: '120ms' }}>
            <div className="form-outer">
              <div className="form-card glass sh-elegant">
                <div className="mobile-brand">
                  <div className="logo-icon sh-glow"><M>hub</M></div>
                  <span className="logo-name">AnnoMaster</span>
                </div>
                <h2 className="form-title">Welcome back</h2>
                <p className="form-subtitle">Access your AI dataset dashboard</p>

                <form onSubmit={doLogin}>
                  <div className="field-group">
                    <label className="field-lbl" htmlFor="email">Email address</label>
                    <div className="input-wrap">
                      <span className="input-icon"><M>mail</M></span>
                      <input className="form-input" type="email" id="email" placeholder="you@company.com"
                             value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="email" autoFocus />
                    </div>
                  </div>
                  <div className="field-group">
                    <div className="field-row">
                      <label className="field-lbl" htmlFor="password">Password</label>
                      <a href="#" className="field-forgot" onClick={(e) => e.preventDefault()}>Forgot?</a>
                    </div>
                    <div className="input-wrap">
                      <span className="input-icon"><M>lock</M></span>
                      <input className="form-input" type={showPw ? 'text' : 'password'} id="password" placeholder="••••••••••••"
                             value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" />
                      <button className="input-toggle" type="button" onClick={() => setShowPw((s) => !s)}>
                        <M>{showPw ? 'visibility_off' : 'visibility'}</M>
                      </button>
                    </div>
                  </div>
                  <div className="form-error">{err}</div>
                  <button className="btn-submit" type="submit" disabled={login.isPending}>
                    <span className="btn-shimmer" />
                    <span>{login.isPending ? 'Signing in…' : 'Sign in to dashboard'}</span>
                    <M>arrow_forward</M>
                  </button>
                </form>

                <p className="form-switch" style={{ textAlign: 'center', marginTop: 20, fontSize: 14, color: 'var(--muted-fg)' }}>
                  New here? <Link to="/register" style={{ color: 'var(--primary)', fontWeight: 600 }}>Create an account</Link>
                </p>
              </div>
            </div>
          </section>
        </div>
      </div>
    </main>
  );
}

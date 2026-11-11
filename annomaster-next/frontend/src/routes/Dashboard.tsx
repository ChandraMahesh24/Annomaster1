import { useEffect, useMemo, useRef, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { Modal } from '../components/Modal';
import { useMe, useLogout } from '../api/auth';
import { useTheme } from '../theme/ThemeProvider';
import { useCreateProject, useCreateWorkspace, useProjects, useWorkspaces } from '../api/hooks';
import type { Project } from '../api/hooks';
import './dashboard-v2.css';

/**
 * Workspace Dashboard — implements design_handoff_dashboard_redesign.
 *
 * The design replaces the shared top navbar with a 252px rail + its own top bar,
 * so this route deliberately does NOT wrap in <AppLayout>; everything the navbar
 * offered (theme toggle, settings, sign out) moves into the top-bar account menu.
 * Styling is `dashboard-v2.css`, which resolves every colour through the token
 * layer — so both themes work without a second stylesheet.
 *
 * The handoff's `Sort` and view toggle were visual-only; here they are real state
 * (persisted), and the search box really filters. KPI totals are aggregates over
 * the project list, never hardcoded.
 */

type View = 'grid' | 'list';
type SortKey = 'recent' | 'name' | 'progress';

const SORTS: { key: SortKey; label: string }[] = [
  { key: 'recent', label: 'Recent' },
  { key: 'name', label: 'Name' },
  { key: 'progress', label: 'Progress' },
];

const VIEW_KEY = 'am_dash_view';
const SORT_KEY = 'am_dash_sort';

function readPref<T extends string>(key: string, allowed: readonly T[], fallback: T): T {
  try {
    const v = localStorage.getItem(key) as T | null;
    return v && allowed.includes(v) ? v : fallback;
  } catch { return fallback; }
}

/** "2h ago" / "yesterday" / "5d ago" — matches the handoff's meta line. */
function relTime(iso?: string | null): string {
  if (!iso) return 'never';
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return 'never';
  const mins = Math.floor((Date.now() - t) / 60000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  if (days === 1) return 'yesterday';
  if (days < 7) return `${days}d ago`;
  const wks = Math.floor(days / 7);
  if (wks < 5) return `${wks}w ago`;
  const mos = Math.floor(days / 30);
  return mos < 12 ? `${mos}mo ago` : `${Math.floor(days / 365)}y ago`;
}

/**
 * Deterministic avatar hue from the user id, so the same collaborator keeps the
 * same colour across cards and reloads. Unrelated to CLASS_PALETTE (which must
 * stay fixed because it identifies annotation classes) — these are people.
 */
function avatarColor(id: number): string {
  return `hsl(${(id * 137.508) % 360} 55% 45%)`;
}

export function Dashboard() {
  const { data: workspaces = [], isLoading: wsLoading } = useWorkspaces();
  const { data: me } = useMe();
  const [wid, setWid] = useState<number | null>(null);
  const [showWs, setShowWs] = useState(false);
  const [showProj, setShowProj] = useState(false);
  const [query, setQuery] = useState('');
  const [view, setView] = useState<View>(() => readPref(VIEW_KEY, ['grid', 'list'] as const, 'grid'));
  const [sort, setSort] = useState<SortKey>(() => readPref(SORT_KEY, ['recent', 'name', 'progress'] as const, 'recent'));
  const [railOpen, setRailOpen] = useState(false);
  const nav = useNavigate();

  useEffect(() => { if (wid == null && workspaces.length) setWid(workspaces[0].id); }, [workspaces, wid]);
  useEffect(() => { try { localStorage.setItem(VIEW_KEY, view); } catch { /* ignore */ } }, [view]);
  useEffect(() => { try { localStorage.setItem(SORT_KEY, sort); } catch { /* ignore */ } }, [sort]);

  const active = workspaces.find((w) => w.id === wid) || null;
  const { data: projects = [], isLoading: projLoading } = useProjects(wid);
  const canEdit = active?.role === 'owner' || active?.role === 'editor';

  // KPI totals + the filtered/sorted list all derive from `projects`.
  const totals = useMemo(() => {
    const images = projects.reduce((n, p) => n + p.images, 0);
    const done = projects.reduce((n, p) => n + p.annotated, 0);
    return { images, done, pending: images - done, pct: images ? Math.round((done / images) * 100) : 0 };
  }, [projects]);

  const shown = useMemo(() => {
    const q = query.trim().toLowerCase();
    const list = q ? projects.filter((p) => p.name.toLowerCase().includes(q)) : projects.slice();
    list.sort((a, b) => {
      if (sort === 'name') return a.name.localeCompare(b.name);
      if (sort === 'progress') return b.progress - a.progress || a.name.localeCompare(b.name);
      return Date.parse(b.updated_at || '') - Date.parse(a.updated_at || '') || a.name.localeCompare(b.name);
    });
    return list;
  }, [projects, query, sort]);

  const openProject = (name: string) =>
    active && nav(`/w/${active.id}/p/${encodeURIComponent(name)}#annotate`);

  return (
    <div className="dsh">
      {railOpen && <div className="dsh-scrim" onClick={() => setRailOpen(false)} />}

      <aside className={`dsh-rail${railOpen ? ' open' : ''}`}>
        <Link to="/" className="dsh-logo">
          <span className="dsh-logo-tile"><i className="fas fa-vector-square" /></span>
          <span className="dsh-logo-text">Anno<b>Master</b></span>
        </Link>

        <nav className="dsh-nav">
          <button className="dsh-nav-item active" type="button">
            <i className="fas fa-layer-group" /> Workspaces
          </button>
          <button className="dsh-nav-item" type="button"
                  onClick={() => { setRailOpen(false); document.getElementById('dsh-projects')?.scrollIntoView({ behavior: 'smooth' }); }}>
            <i className="fas fa-folder" /> Projects
          </button>
          <button className="dsh-nav-item" type="button" onClick={() => nav('/settings')}>
            <i className="fas fa-gear" /> Settings
          </button>
        </nav>

        <div className="dsh-rail-group">
          <div className="dsh-rail-head">
            <span className="dsh-rail-label">Your Workspaces</span>
            <button className="dsh-icon-btn" title="New workspace" aria-label="New workspace"
                    onClick={() => setShowWs(true)}>
              <i className="fas fa-plus" />
            </button>
          </div>
          <div className="dsh-ws-list">
            {workspaces.map((w) => (
              <button key={w.id} type="button"
                      className={`dsh-ws-item${w.id === wid ? ' active' : ''}`}
                      onClick={() => { setWid(w.id); setRailOpen(false); }}>
                <span className="dsh-ws-dot" />
                <span className="dsh-ws-name">{w.name}</span>
              </button>
            ))}
            {!workspaces.length && (
              <div className="dsh-rail-empty">{wsLoading ? 'Loading…' : 'No workspaces yet'}</div>
            )}
          </div>
        </div>

        <div className="dsh-rail-foot">
          <div className="dsh-avatar sm">{(me?.username || 'U')[0].toUpperCase()}</div>
          <div className="dsh-rail-foot-mail" title={me?.email}>{me?.email}</div>
        </div>
      </aside>

      <main className="dsh-main">
        <header className="dsh-topbar">
          <button className="dsh-ghost-btn dsh-rail-toggle" aria-label="Menu"
                  onClick={() => setRailOpen((o) => !o)}>
            <i className="fas fa-bars" />
          </button>

          <div className="dsh-crumbs">
            <span>Workspaces</span>
            <span className="sep">/</span>
            <span className="cur">{active?.name || '—'}</span>
          </div>

          <label className="dsh-search">
            <i className="fas fa-magnifying-glass" />
            <input value={query} onChange={(e) => setQuery(e.target.value)}
                   placeholder="Search projects…" aria-label="Search projects" />
            {query && (
              <button className="dsh-search-clear" onClick={() => setQuery('')} aria-label="Clear search">
                <i className="fas fa-times" />
              </button>
            )}
          </label>

          <div className="dsh-topbar-right">
            <ThemeButton />
            <AccountMenu />
          </div>
        </header>

        <div className="dsh-body">
          {active ? (
            <>
              <div className="dsh-head">
                <div className="dsh-head-left">
                  <div className="dsh-title-row">
                    <h1 className="dsh-title">{active.name}</h1>
                    <span className={`dsh-role ${active.role}`}>{active.role}</span>
                  </div>
                  <div className="dsh-sub">
                    {active.public_id} · {projects.length} {projects.length === 1 ? 'project' : 'projects'}
                  </div>
                </div>
                <div className="dsh-head-actions">
                  <button className="dsh-btn dsh-btn-outline" onClick={() => nav(`/w/${active.id}/members`)}>
                    <i className="fas fa-user-plus" /> Share
                  </button>
                  {canEdit && (
                    <button className="dsh-btn dsh-btn-primary" onClick={() => setShowProj(true)}>
                      <i className="fas fa-plus" /> New Project
                    </button>
                  )}
                </div>
              </div>

              <div className="dsh-kpis">
                <div className="dsh-kpi">
                  <div className="dsh-kpi-top">
                    <span className="dsh-kpi-label">Total images</span>
                    <span className="dsh-kpi-chip blue"><i className="fas fa-images" /></span>
                  </div>
                  <div className="dsh-kpi-value"><b>{totals.images.toLocaleString()}</b></div>
                </div>
                <div className="dsh-kpi">
                  <div className="dsh-kpi-top">
                    <span className="dsh-kpi-label">Completed</span>
                    <span className="dsh-kpi-chip green"><i className="fas fa-check" /></span>
                  </div>
                  <div className="dsh-kpi-value">
                    <b>{totals.done.toLocaleString()}</b>
                    {totals.images > 0 && <span className="dsh-kpi-delta">{totals.pct}%</span>}
                  </div>
                </div>
                <div className="dsh-kpi">
                  <div className="dsh-kpi-top">
                    <span className="dsh-kpi-label">Pending</span>
                    <span className="dsh-kpi-chip amber"><i className="far fa-clock" /></span>
                  </div>
                  <div className="dsh-kpi-value"><b>{totals.pending.toLocaleString()}</b></div>
                </div>
              </div>

              <section className="dsh-section" id="dsh-projects">
                <div className="dsh-section-head">
                  <span className="dsh-section-label">
                    Projects{query && ` · ${shown.length} match${shown.length === 1 ? '' : 'es'}`}
                  </span>
                  <div className="dsh-section-tools">
                    <SortControl value={sort} onChange={setSort} />
                    <div className="dsh-seg" role="group" aria-label="View mode">
                      <button className={view === 'grid' ? 'active' : ''} aria-label="Grid view"
                              aria-pressed={view === 'grid'} onClick={() => setView('grid')}>
                        <i className="fas fa-th-large" />
                      </button>
                      <button className={view === 'list' ? 'active' : ''} aria-label="List view"
                              aria-pressed={view === 'list'} onClick={() => setView('list')}>
                        <i className="fas fa-list" />
                      </button>
                    </div>
                  </div>
                </div>

                {projLoading ? (
                  <div className="dsh-grid">
                    {[0, 1, 2, 3].map((i) => <div className="dsh-skel" key={i} />)}
                  </div>
                ) : !projects.length ? (
                  <div className="dsh-empty">
                    <div className="dsh-empty-icon"><i className="fas fa-folder-open" /></div>
                    <h3>No projects yet</h3>
                    <p>Create your first project to start uploading and annotating images.</p>
                    {canEdit && (
                      <button className="dsh-btn dsh-btn-primary" onClick={() => setShowProj(true)}>
                        <i className="fas fa-plus" /> New Project
                      </button>
                    )}
                  </div>
                ) : !shown.length ? (
                  <div className="dsh-empty">
                    <div className="dsh-empty-icon"><i className="fas fa-magnifying-glass" /></div>
                    <h3>No match for “{query}”</h3>
                    <p>Try a different search term.</p>
                  </div>
                ) : view === 'grid' ? (
                  <div className="dsh-grid">
                    {shown.map((p) => <ProjectCard key={p.name} p={p} onOpen={() => openProject(p.name)} />)}
                    {canEdit && (
                      <button className="dsh-ghost" onClick={() => setShowProj(true)}>
                        <span className="dsh-ghost-circle"><i className="fas fa-plus" /></span>
                        <span className="dsh-ghost-label">New Project</span>
                      </button>
                    )}
                  </div>
                ) : (
                  <div className="dsh-list">
                    {shown.map((p) => <ProjectRow key={p.name} p={p} onOpen={() => openProject(p.name)} />)}
                  </div>
                )}
              </section>
            </>
          ) : (
            <div className="dsh-empty">
              <div className="dsh-empty-icon"><i className="fas fa-layer-group" /></div>
              <h3>{wsLoading ? 'Loading workspaces…' : 'No workspaces yet'}</h3>
              <p>Create a workspace to organise your annotation projects.</p>
              {!wsLoading && (
                <button className="dsh-btn dsh-btn-primary" onClick={() => setShowWs(true)}>
                  <i className="fas fa-plus" /> New Workspace
                </button>
              )}
            </div>
          )}
        </div>
      </main>

      {showWs && <CreateWorkspaceModal onClose={() => setShowWs(false)} onCreated={setWid} />}
      {showProj && active && <CreateProjectModal wid={active.id} onClose={() => setShowProj(false)} />}
    </div>
  );
}

/* ── Project card ─────────────────────────────────────────────────────────── */
function ProjectCard({ p, onOpen }: { p: Project; onOpen: () => void }) {
  const pending = p.images - p.annotated;
  return (
    <button className="dsh-card" onClick={onOpen} title={`Open ${p.name}`}>
      <div className="dsh-card-cover"><i className="fas fa-folder-open" /></div>
      <div className="dsh-card-bar"><span style={{ width: `${p.progress}%` }} /></div>
      <div className="dsh-card-body">
        <div className="dsh-card-title-row">
          <span className="dsh-card-name" title={p.name}>{p.name}</span>
          <span className="dsh-card-pct">{p.progress}%</span>
        </div>
        <div className="dsh-pills">
          <span className="dsh-pill blue"><i className="fas fa-images" />{p.images} images</span>
          <span className="dsh-pill green"><i className="fas fa-check" />{p.annotated} done</span>
          <span className="dsh-pill amber"><i className="far fa-clock" />{pending} pending</span>
        </div>
        <div className="dsh-card-foot">
          <span className="dsh-card-updated">Updated {relTime(p.updated_at)}</span>
          <AvatarStack people={p.contributors} />
        </div>
      </div>
    </button>
  );
}

function ProjectRow({ p, onOpen }: { p: Project; onOpen: () => void }) {
  const pending = p.images - p.annotated;
  return (
    <button className="dsh-row" onClick={onOpen} title={`Open ${p.name}`}>
      <span className="dsh-row-icon"><i className="fas fa-folder-open" /></span>
      <span className="dsh-row-name">{p.name}</span>
      <span className="dsh-row-pills">
        <span className="dsh-pill blue"><i className="fas fa-images" />{p.images}</span>
        <span className="dsh-pill green"><i className="fas fa-check" />{p.annotated}</span>
        <span className="dsh-pill amber"><i className="far fa-clock" />{pending}</span>
      </span>
      <span className="dsh-row-bar"><span style={{ width: `${p.progress}%` }} /></span>
      <span className="dsh-row-pct">{p.progress}%</span>
      <span className="dsh-row-updated">{relTime(p.updated_at)}</span>
      <AvatarStack people={p.contributors} />
    </button>
  );
}

/** Overlapping collaborator stack; caps at 3 with a +N bubble. */
function AvatarStack({ people = [] }: { people?: { id: number; name: string }[] }) {
  if (!people.length) return null;
  const shown = people.slice(0, 3);
  const extra = people.length - shown.length;
  return (
    <span className="dsh-stack">
      {shown.map((u) => (
        <span key={u.id} className="dsh-stack-av" title={u.name}
              style={{ background: avatarColor(u.id) }}>
          {u.name[0]?.toUpperCase()}
        </span>
      ))}
      {extra > 0 && (
        <span className="dsh-stack-av dsh-stack-more" title={`${extra} more`}>+{extra}</span>
      )}
    </span>
  );
}

/* ── Section tools ────────────────────────────────────────────────────────── */
function SortControl({ value, onChange }: { value: SortKey; onChange: (k: SortKey) => void }) {
  const [open, setOpen] = useState(false);
  const ref = useCloseOnOutside<HTMLDivElement>(() => setOpen(false));
  const label = SORTS.find((s) => s.key === value)?.label ?? 'Recent';
  return (
    <div className="dsh-sort" ref={ref}>
      <button className="dsh-sort-btn" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
        Sort: {label} <span className="caret" />
      </button>
      {open && (
        <div className="dsh-sort-menu" role="menu">
          {SORTS.map((s) => (
            <button key={s.key} role="menuitem"
                    className={`dsh-sort-opt${s.key === value ? ' active' : ''}`}
                    onClick={() => { onChange(s.key); setOpen(false); }}>
              {s.label} {s.key === value && <i className="fas fa-check" />}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

/* ── Top bar: theme + account (replaces what AppLayout's navbar provided) ─── */
function ThemeButton() {
  const { theme, toggle } = useTheme();
  return (
    <button className="dsh-ghost-btn" onClick={toggle}
            title={`Switch to ${theme === 'dark' ? 'light' : 'dark'} theme`}
            aria-label={`Switch to ${theme === 'dark' ? 'light' : 'dark'} theme`}>
      <i className={theme === 'dark' ? 'fas fa-sun' : 'fas fa-moon'} />
    </button>
  );
}

function AccountMenu() {
  const { data: me } = useMe();
  const { theme, toggle } = useTheme();
  const logout = useLogout();
  const [open, setOpen] = useState(false);
  const ref = useCloseOnOutside<HTMLDivElement>(() => setOpen(false));
  const initial = (me?.username || 'U')[0].toUpperCase();

  return (
    <div className="dsh-account" ref={ref}>
      <button className="dsh-account-trigger" onClick={() => setOpen((o) => !o)}
              aria-expanded={open} aria-label="Account menu">
        <span className="dsh-avatar md">{initial}</span>
      </button>
      {open && (
        <div className="dsh-menu" role="menu">
          <div className="dsh-menu-head">
            <span className="dsh-avatar md">{initial}</span>
            <div style={{ minWidth: 0 }}>
              <div className="dsh-menu-name">{me?.username}</div>
              <div className="dsh-menu-mail" title={me?.email}>{me?.email}</div>
            </div>
          </div>
          <div className="dsh-menu-sep" />
          <button className="dsh-menu-item" onClick={toggle}>
            <i className="fas fa-circle-half-stroke" /> {theme === 'dark' ? 'Light' : 'Dark'} theme
          </button>
          <Link className="dsh-menu-item" to="/settings">
            <i className="fas fa-user-gear" /> Account Settings
          </Link>
          <div className="dsh-menu-sep" />
          <button className="dsh-menu-item danger" onClick={() => logout.mutate()}>
            <i className="fas fa-right-from-bracket" /> Sign Out
          </button>
        </div>
      )}
    </div>
  );
}

/** Close a popover on outside click or Escape. */
function useCloseOnOutside<T extends HTMLElement>(close: () => void) {
  const ref = useRef<T>(null);
  useEffect(() => {
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) close();
    };
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') close(); };
    document.addEventListener('mousedown', onDown);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onDown);
      document.removeEventListener('keydown', onKey);
    };
  }, [close]);
  return ref;
}

/* ── Modals (unchanged behaviour, ported markup) ──────────────────────────── */
function CreateWorkspaceModal({ onClose, onCreated }: { onClose: () => void; onCreated: (id: number) => void }) {
  const [name, setName] = useState('');
  const [err, setErr] = useState('');
  const create = useCreateWorkspace();
  return (
    <Modal title="New Workspace" onClose={onClose} footer={<>
      <button className="btn btn-secondary" onClick={onClose}>Cancel</button>
      <button className="btn btn-primary" disabled={!name.trim() || create.isPending}
        onClick={async () => {
          try { const ws = await create.mutateAsync(name.trim()); onCreated(ws.id); onClose(); }
          catch (e) { setErr((e as Error).message); }
        }}>Create</button>
    </>}>
      <div className="form-group">
        <label className="form-label">Name</label>
        <input className="form-input" value={name} onChange={(e) => setName(e.target.value)} autoFocus />
      </div>
      {err && <div className="form-error">{err}</div>}
    </Modal>
  );
}

function CreateProjectModal({ wid, onClose }: { wid: number; onClose: () => void }) {
  const [name, setName] = useState('');
  const [err, setErr] = useState('');
  const create = useCreateProject(wid);
  return (
    <Modal title="New Project" onClose={onClose} footer={<>
      <button className="btn btn-secondary" onClick={onClose}>Cancel</button>
      <button className="btn btn-primary" disabled={!name.trim() || create.isPending}
        onClick={async () => { try { await create.mutateAsync(name.trim()); onClose(); } catch (e) { setErr((e as Error).message); } }}>Create</button>
    </>}>
      <div className="form-group">
        <label className="form-label">Name</label>
        <input className="form-input" value={name} onChange={(e) => setName(e.target.value)} autoFocus />
      </div>
      {err && <div className="form-error">{err}</div>}
    </Modal>
  );
}

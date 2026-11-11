import { useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import { useClasses, useProjects, type Batch } from '../api/hooks';
import { useAnnotate } from '../canvas/useAnnotate';
import { AnnotateSection } from './sections/AnnotateSection';
import { UploadSection } from './sections/UploadSection';
import { DatasetSection } from './sections/DatasetSection';
import { VersionsSection } from './sections/VersionsSection';
import { ClassesSection } from './sections/ClassesSection';
import { ProjectsSection } from './sections/ProjectsSection';

type Page = 'upload' | 'annotate' | 'dataset' | 'versions' | 'classes' | 'projects';
const PAGES: Page[] = ['upload', 'annotate', 'dataset', 'versions', 'classes', 'projects'];

/**
 * App shell — faithful port of annotate.html: `.toolbar.anno-header` (brand +
 * project pill + progress + image nav + save/autosave/Complete), the
 * `.right-nav` rail switching six sections, and the `.status-bar`. Image nav +
 * save live IN THE HEADER (matching the original), driven by the shared
 * useAnnotate state.
 */
export function Workspace() {
  const { wid: widS, project: projectRaw } = useParams();
  const wid = Number(widS);
  const project = decodeURIComponent(projectRaw ?? '');

  const [page, setPage] = useState<Page>(() => {
    const h = location.hash.replace('#', '') as Page;
    return PAGES.includes(h) ? h : 'annotate';
  });
  useEffect(() => { location.hash = page; }, [page]);

  const { data: projects = [] } = useProjects(wid);
  const { data: classes = [] } = useClasses(wid, project);

  // Batch filter: clicking a batch card opens the annotator on ONLY that batch.
  const [batchFilter, setBatchFilter] = useState<{ id: number; label: string } | null>(null);
  const anno = useAnnotate(wid, project, batchFilter?.id ?? null);

  function openBatch(b: Batch, mode: 'review' | 'raw') {
    const m = (b.datetime_str || '').match(/(\d{4})-(\d{2})-(\d{2})[_T](\d{2})[-:](\d{2})/);
    const label = m ? `${m[3]}/${m[2]} ${m[4]}:${m[5]}` : `Batch #${b.upload_id}`;
    setBatchFilter(b.batch_db_id != null ? { id: b.batch_db_id, label: `${label} · ${mode === 'raw' ? 'raw' : 'review'}` } : null);
    setPage('annotate');
  }

  // Header progress uses PROJECT-wide stats (accurate across pages); the center
  // counter uses the current (possibly batch-filtered) list position.
  const proj = projects.find((p) => p.name === project);
  const total = proj?.images ?? anno.total;
  const done = proj?.annotated ?? 0;
  const pct = proj?.progress ?? (total ? Math.round(done / total * 100) : 0);
  const viewTotal = anno.total;
  const st = anno.current;
  const status = !st ? 'unannotated' : st.is_null ? 'annotated' : st.is_annotated ? 'annotated' : 'unannotated';

  const RAIL: { id: Page; icon: string; label: string; badge?: number }[] = [
    { id: 'upload', icon: 'fa-cloud-upload-alt', label: 'Upload' },
    { id: 'annotate', icon: 'fa-pen-nib', label: 'Annotate', badge: total - done },
    { id: 'dataset', icon: 'fa-images', label: 'Dataset' },
    { id: 'versions', icon: 'fa-history', label: 'Versions' },
    { id: 'classes', icon: 'fa-tags', label: 'Classes', badge: classes.length },
  ];

  return (
    <>
      {/* ═══ TOP HEADER ═══ */}
      <header className="toolbar anno-header" id="annoHeader">
        <div className="ah-left">
          <a className="toolbar-brand" href="/" title="Back to Dashboard">
            <span className="brand-icon"><i className="fas fa-crosshairs" /></span>
            <span className="brand-name">Anno<span className="brand-accent">Master</span></span>
          </a>
          <div className="tb-sep" />
          <div className="project-pill">
            <i className="fas fa-folder-open" />
            <select value={project} onChange={(e) => { location.href = `/w/${wid}/p/${encodeURIComponent(e.target.value)}#${page}`; }}>
              {projects.map((p) => <option key={p.name} value={p.name}>{p.name}</option>)}
            </select>
          </div>
          <div className="tb-sep" />
          <div className="hdr-progress-wrap" title="Annotation progress">
            <div className="hdr-progress-bar"><div className="hdr-progress-fill" style={{ width: `${pct}%` }} /></div>
            <span className="hdr-progress-pct">{pct}%</span>
          </div>
        </div>

        <div className="ah-center">
          <button className="ah-nav-btn" title="Previous (←)" disabled={anno.globalIndex <= 0} onClick={() => anno.nav(-1)}><i className="fas fa-chevron-left" /></button>
          <div className="ah-counter">
            <div className="ah-file-row">
              <span className="ah-filename">{st?.filename ?? '—'}</span>
              <span className={`hdr-status-badge ${status}`}><i className="fas fa-circle" /> {status === 'annotated' ? 'Annotated' : 'Unannotated'}</span>
            </div>
            <span className="ah-idx">{viewTotal ? `${anno.globalIndex + 1} / ${viewTotal}` : '0 / 0'}</span>
          </div>
          <button className="ah-nav-btn" title="Next (→)" disabled={anno.globalIndex >= viewTotal - 1} onClick={() => anno.nav(1)}><i className="fas fa-chevron-right" /></button>
        </div>

        <div className="ah-right">
          <div className={`hdr-save ${anno.saved === 'saving' ? 'saving' : anno.saved === 'saved' ? 'saved' : 'saved'}`}>
            <i className={`fas ${anno.saved === 'saving' ? 'fa-circle-notch fa-spin' : 'fa-check-circle'}`} /> {anno.saved === 'saving' ? 'Saving' : 'Saved'}
          </div>
          <div className="tb-sep" />
          <label className="autosave-toggle" title="Auto-save">
            <input type="checkbox" checked={anno.autoSave} onChange={(e) => anno.setAutoSave(e.target.checked)} />
            <span className="aToggle" /><span className="autosave-lbl">Auto</span>
          </label>
          <div className="tb-sep" />
          <button className="ah-complete-btn" title="Save" onClick={anno.save}><i className="fas fa-check-double" /><span>Save</span></button>
        </div>
      </header>

      {/* ═══ WORKSPACE (sections) ═══ */}
      <div className="workspace">
        {page === 'annotate' && <AnnotateSection wid={wid} project={project} anno={anno}
                                  batchLabel={batchFilter?.label ?? null} onClearBatch={() => setBatchFilter(null)} />}
        {page === 'upload' && <UploadSection wid={wid} project={project} onOpenBatch={openBatch} />}
        {page === 'dataset' && <DatasetSection wid={wid} project={project} />}
        {page === 'versions' && <VersionsSection wid={wid} project={project} />}
        {page === 'classes' && <ClassesSection wid={wid} project={project} />}
        {page === 'projects' && <ProjectsSection wid={wid} project={project} />}
      </div>

      {/* ═══ LEFT NAV RAIL ═══ */}
      <nav className="right-nav" id="rightNav">
        <div className="rn-pages">
          {RAIL.map((r) => (
            <button key={r.id} className={`rn-item${page === r.id ? ' active' : ''}`} data-page={r.id} title={r.label} onClick={() => setPage(r.id)}>
              <i className={`fas ${r.icon}`} />
              <span className="rn-label">{r.label}</span>
              {r.badge != null && <span className="rn-badge">{r.badge}</span>}
            </button>
          ))}
          <div style={{ flex: 1 }} />
          <button className={`rn-item${page === 'projects' ? ' active' : ''}`} data-page="projects" title="Projects" onClick={() => setPage('projects')}>
            <i className="fas fa-briefcase" /><span className="rn-label">Projects</span>
          </button>
        </div>
      </nav>

      {/* ═══ STATUS BAR ═══ */}
      <footer className="status-bar">
        <span className="sb-item"><i className="fas fa-file-image" /> {st?.filename ?? '—'}</span>
        <span className="sb-sep" />
        <span className="sb-item mono"><i className="fas fa-list-ol" /> {total ? `${anno.idx + 1} / ${total}` : '0 / 0'}</span>
        <span className="sb-sep" />
        <span className="sb-item"><i className="fas fa-draw-polygon" /> {anno.state.boxes.filter((b) => b.state !== 'rejected').length} objects</span>
        <span className="sb-spacer" />
        <span className="sb-mode-chip"><i className="fas fa-vector-square" /> {anno.state.mode === 'draw' ? 'Draw' : 'Select'}</span>
      </footer>
    </>
  );
}

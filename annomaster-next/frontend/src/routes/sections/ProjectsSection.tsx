import { useState } from 'react';
import { useProjects, useCreateProject } from '../../api/hooks';

/** #projects — ports #page-projects: .proj-page-header + .proj-grid (.project-card). */
export function ProjectsSection({ wid, project }: { wid: number; project: string }) {
  const { data: projects = [] } = useProjects(wid);
  const create = useCreateProject(wid);
  const [name, setName] = useState('');
  const [creating, setCreating] = useState(false);

  async function doCreate() {
    if (!name.trim()) return;
    await create.mutateAsync(name.trim()); setName(''); setCreating(false);
  }

  return (
    <div className="page" id="page-projects">
      <div className="proj-page-header">
        <div className="proj-page-title">
          <i className="fas fa-layer-group" />
          <span>Projects</span>
          <span className="proj-page-count">{projects.length}</span>
        </div>
        <div className="proj-page-actions">
          {creating ? (
            <div className="proj-search-wrap" style={{ display: 'flex', gap: 6 }}>
              <input className="input" placeholder="project-name…" value={name} autoFocus
                     onChange={(e) => setName(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && doCreate()} />
              <button className="proj-create-btn" onClick={doCreate}><i className="fas fa-check" /></button>
            </div>
          ) : (
            <button className="proj-create-btn" onClick={() => setCreating(true)}>
              <i className="fas fa-plus" /><span>Create Project</span>
            </button>
          )}
        </div>
      </div>

      <div className="proj-grid-body">
        {projects.length ? (
          <div className="proj-grid projects-grid">
            {projects.map((p) => (
              <a key={p.name} className="project-card" href={`/w/${wid}/p/${encodeURIComponent(p.name)}#annotate`}
                 style={{ outline: p.name === project ? '2px solid var(--accent)' : 'none' }}>
                <div className="project-card-cover"><span className="pc-icon">📂</span>
                  <div className="proj-cover-progress"><div className="proj-cover-progress-fill" style={{ width: `${p.progress}%` }} /></div>
                </div>
                <div className="project-card-body">
                  <div className="project-card-name">{p.name}</div>
                  <div className="project-card-stats">
                    <span className="pcs-chip blue"><i className="fas fa-images" />{p.images}</span>
                    <span className="pcs-chip green"><i className="fas fa-check-circle" />{p.annotated}</span>
                    <span className="pcs-chip amber"><i className="fas fa-hourglass-half" />{p.images - p.annotated}</span>
                  </div>
                  <div className="project-progress"><div className="project-progress-fill" style={{ width: `${p.progress}%` }} /></div>
                  <div className="project-progress-label">{p.progress}% complete</div>
                </div>
              </a>
            ))}
          </div>
        ) : (
          <div className="proj-empty">
            <div className="proj-empty-icon"><i className="fas fa-folder-open" /></div>
            <div className="proj-empty-title">No projects yet</div>
            <div className="proj-empty-sub">Create your first project to get started</div>
            <button className="proj-create-btn" onClick={() => setCreating(true)}><i className="fas fa-plus" /><span>Create Project</span></button>
          </div>
        )}
      </div>
    </div>
  );
}

import { useState } from 'react';
import { useParams } from 'react-router-dom';
import { AppLayout } from '../components/AppLayout';
import { useInviteMember, useMembers, useRemoveMember, useSetRole } from '../api/hooks';

/** Members — ports workspace/members.html (.members-page / .invite-card /
 *  .members-list / .member-row). Styled by ported layout.css + workspace.css. */
export function Members() {
  const wid = Number(useParams().wid);
  const { data: members = [] } = useMembers(wid);
  const invite = useInviteMember(wid);
  const remove = useRemoveMember(wid);
  const setRole = useSetRole(wid);
  const [email, setEmail] = useState('');
  const [role, setRoleVal] = useState('editor');
  const [err, setErr] = useState('');
  const [ok, setOk] = useState('');

  return (
    <AppLayout>
      <div className="members-page">
        <div className="members-container">
          <div className="members-header">
            <a href="/" className="btn btn-secondary btn-sm">← Dashboard</a>
            <div>
              <h1 style={{ fontSize: '1.4rem', fontWeight: 800 }}>Members</h1>
              <p className="text-muted" style={{ marginTop: '.2rem' }}>{members.length} member(s)</p>
            </div>
          </div>

          <div className="invite-card">
            <h3>Invite a Member</h3>
            <div className="invite-form">
              <input className="form-input" type="email" placeholder="colleague@example.com"
                     value={email} onChange={(e) => setEmail(e.target.value)} />
              <select className="form-select" style={{ width: 'auto' }} value={role} onChange={(e) => setRoleVal(e.target.value)}>
                <option value="editor">Editor – can annotate &amp; upload</option>
                <option value="viewer">Viewer – read only</option>
              </select>
              <button className="btn btn-primary" onClick={async () => {
                setErr(''); setOk('');
                try { await invite.mutateAsync({ email, role }); setOk('Invited.'); setEmail(''); }
                catch (e) { setErr((e as Error).message); }
              }}>Invite</button>
            </div>
            {err && <div id="invite-error">{err}</div>}
            {ok && <div id="invite-success">{ok}</div>}
          </div>

          <div className="members-card">
            <h3>Current Members</h3>
            <div className="members-list">
              {members.map((m) => (
                <div key={m.user_id} className="member-row">
                  <div className="member-avatar">{m.username[0]?.toUpperCase()}</div>
                  <div className="member-info">
                    <div className="member-name">{m.username}</div>
                    <div className="member-email">{m.email}</div>
                  </div>
                  <div className="member-actions">
                    {m.role === 'owner' ? (
                      <span className="badge badge-owner">owner</span>
                    ) : (
                      <>
                        <select className="role-select" value={m.role}
                                onChange={(e) => setRole.mutate({ uid: m.user_id, role: e.target.value })}>
                          <option value="viewer">viewer</option>
                          <option value="editor">editor</option>
                        </select>
                        <button className="btn btn-secondary btn-sm" onClick={() => remove.mutate(m.user_id)}>Remove</button>
                      </>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </AppLayout>
  );
}

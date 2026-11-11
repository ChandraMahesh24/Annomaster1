/**
 * React Query hooks for the non-canvas views. Server state lives here; the
 * components stay thin. Query keys are structured so a mutation can invalidate
 * exactly what it changed.
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from './client';

// ── Types ─────────────────────────────────────────────────────────────────────
export interface Workspace { id: number; public_id: string; name: string; folder_name: string; role: string; }
export interface Contributor { id: number; name: string; }
export interface Project {
  name: string; images: number; annotated: number; progress: number;
  /** ISO-8601 UTC of the last upload/annotation — drives "Updated 2h ago" + Recent sort. */
  updated_at?: string | null;
  /** Everyone who uploaded to or annotated in the project — the card's avatar stack. */
  contributors?: Contributor[];
}
export interface Member { user_id: number; user_public_id: string; username: string; email: string; role: string; }
export interface Klass { id: number; name: string; color?: string; }
export interface DatasetSummary { total: number; splits: Record<string, number>; }
export interface AssignmentBrief {
  assigned_to: number; assignee: string; status: string;
  total_images: number; done_images: number; progress_pct: number;
}
export interface Batch {
  upload_id: number; batch_db_id: number | null; job_name: string; source: string;
  total: number; annotated: number; pending: number; null_count: number;
  in_dataset: boolean; partial_dataset: boolean;
  datetime_str: string | null; uploader_name: string | null;
  assignment: AssignmentBrief | null;
}
export interface Version { name: string; note: string; created_at: string; num_images: number; splits: Record<string, number>; }

// ── Workspaces ────────────────────────────────────────────────────────────────
export const useWorkspaces = () =>
  useQuery({ queryKey: ['workspaces'], queryFn: () => api<Workspace[]>('/workspaces') });

export function useCreateWorkspace() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (name: string) => api<Workspace>('/workspaces', { body: { name } }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['workspaces'] }),
  });
}
export function useDeleteWorkspace() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => api(`/workspaces/${id}`, { method: 'DELETE' }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['workspaces'] }),
  });
}

// ── Projects ──────────────────────────────────────────────────────────────────
export const useProjects = (wid: number | null) =>
  useQuery({
    queryKey: ['projects', wid],
    queryFn: () => api<{ projects: Project[] }>(`/workspaces/${wid}/projects`).then((r) => r.projects),
    enabled: wid != null,
  });

export function useCreateProject(wid: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (name: string) => api<Project>(`/workspaces/${wid}/projects`, { body: { name } }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['projects', wid] }),
  });
}
export function useDeleteProject(wid: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (name: string) => api(`/workspaces/${wid}/projects/${encodeURIComponent(name)}`, { method: 'DELETE' }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['projects', wid] }),
  });
}

// ── Members ───────────────────────────────────────────────────────────────────
export const useMembers = (wid: number) =>
  useQuery({ queryKey: ['members', wid], queryFn: () => api<Member[]>(`/workspaces/${wid}/members`) });

export function useInviteMember(wid: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (b: { email: string; role: string }) => api(`/workspaces/${wid}/members`, { body: b }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['members', wid] }),
  });
}
export function useRemoveMember(wid: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (uid: number) => api(`/workspaces/${wid}/members/${uid}`, { method: 'DELETE' }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['members', wid] }),
  });
}
export function useSetRole(wid: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (b: { uid: number; role: string }) =>
      api(`/workspaces/${wid}/members/${b.uid}/role`, { method: 'PUT', body: { role: b.role } }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['members', wid] }),
  });
}

// ── Classes ───────────────────────────────────────────────────────────────────
export const useClasses = (wid: number, project: string) =>
  useQuery({
    queryKey: ['classes', wid, project],
    queryFn: () => api<{ classes: Klass[] }>(`/workspaces/${wid}/projects/${encodeURIComponent(project)}/classes`).then((r) => r.classes),
  });
export function useSetClasses(wid: number, project: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (classes: Klass[]) =>
      api(`/workspaces/${wid}/projects/${encodeURIComponent(project)}/classes`, { method: 'PUT', body: { classes } }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['classes', wid, project] }),
  });
}

// ── Dataset + versions ────────────────────────────────────────────────────────
const p = (wid: number, project: string) => `/workspaces/${wid}/projects/${encodeURIComponent(project)}`;

export const useDataset = (wid: number, project: string) =>
  useQuery({ queryKey: ['dataset', wid, project], queryFn: () => api<DatasetSummary>(`${p(wid, project)}/dataset`) });

export function useAddToDataset(wid: number, project: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (ratios?: Record<string, number>) => api(`${p(wid, project)}/dataset/add`, { body: { ratios } }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['dataset', wid, project] }),
  });
}

// ── Upload batches (Active Work) ────────────────────────────────────────────
export const useBatches = (wid: number, project: string) =>
  useQuery({
    queryKey: ['batches', wid, project],
    queryFn: () => api<Batch[]>(`${p(wid, project)}/uploads`),
    refetchInterval: 8000,   // Active Work auto-refreshes (matches the original)
  });

export function useAssignBatch(wid: number, project: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (b: { upload_id: number; assigned_to: number; note?: string }) =>
      api<AssignmentBrief>(`${p(wid, project)}/uploads/${b.upload_id}/assign`,
        { body: { assigned_to: b.assigned_to, note: b.note } }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['batches', wid, project] }),
  });
}

export function useUnassignBatch(wid: number, project: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (upload_id: number) =>
      api(`${p(wid, project)}/uploads/${upload_id}/assign`, { method: 'DELETE' }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['batches', wid, project] }),
  });
}

export interface AddDatasetResult {
  success: boolean; moved_annotated: number; remaining_raw: number;
  split_counts: { train: number; val: number; test: number };
}
export function useAddBatchToDataset(wid: number, project: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (b: { upload_id: number; train: number; val: number; test: number }) =>
      api<AddDatasetResult>(`${p(wid, project)}/uploads/${b.upload_id}/add_to_dataset`,
        { body: { train: b.train, val: b.val, test: b.test } }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['batches', wid, project] });
      qc.invalidateQueries({ queryKey: ['dataset', wid, project] });
    },
  });
}

export const useVersions = (wid: number, project: string) =>
  useQuery({ queryKey: ['versions', wid, project], queryFn: () => api<{ versions: Version[] }>(`${p(wid, project)}/versions`).then((r) => r.versions) });

export function useCreateVersion(wid: number, project: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (b: { name: string; note?: string }) => api(`${p(wid, project)}/versions`, { body: b }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['versions', wid, project] }),
  });
}

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from './client';

export interface ModelInfo { name: string; size_mb: number; classes?: string[]; class_count?: number; valid?: boolean; }
export interface AiSettings { model: string | null; conf: number; iou: number; mode: 'review' | 'autosave'; }
export interface Prediction {
  class_name: string; yolo_cls_id: number; conf: number;
  x_center: number; y_center: number; width: number; height: number;
}

export const useModels = () =>
  useQuery({ queryKey: ['ai-models'], queryFn: () => api<{ models: ModelInfo[] }>('/ai/models').then((r) => r.models) });

/** Upload a new .pt YOLO model. The backend validates it on arrival (rejects
 *  unusable weights with 422) and drops it in models/, after which it appears in
 *  the model list. Invalidates the list so the new model shows up immediately. */
export function useUploadModel() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (file: File) => {
      const form = new FormData();
      form.append('file', file);
      return api<{ success: boolean; name: string; valid?: boolean }>('/ai/upload_model', { form });
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['ai-models'] }),
  });
}

export const useModelInfo = (name: string | null) =>
  useQuery({
    queryKey: ['ai-model-info', name],
    queryFn: () => api<ModelInfo>(`/ai/models/${encodeURIComponent(name!)}/info`),
    enabled: !!name,
    retry: false,
  });

export const useAiSettings = (wid: number, project: string) =>
  useQuery({
    queryKey: ['ai-settings', wid, project],
    queryFn: () => api<AiSettings>(`/workspaces/${wid}/projects/${encodeURIComponent(project)}/ai/settings`),
  });

export function useSaveAiSettings(wid: number, project: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (patch: Partial<AiSettings>) =>
      api<AiSettings>(`/workspaces/${wid}/projects/${encodeURIComponent(project)}/ai/settings`, { method: 'PUT', body: patch }),
    onSuccess: (data) => qc.setQueryData(['ai-settings', wid, project], data),
  });
}

/** Run detection on one image. Returns raw predictions; reconciliation is the reducer's job. */
export function predict(wid: number, project: string, path: string, model?: string, conf?: number) {
  return api<{ predictions: Prediction[]; model: string; conf: number }>(
    `/workspaces/${wid}/projects/${encodeURIComponent(project)}/ai/predict`,
    { body: { path, model, conf } },
  );
}

export function logAutosave(wid: number, project: string, body: Record<string, unknown>) {
  return api(`/workspaces/${wid}/projects/${encodeURIComponent(project)}/ai/autosave_log`, { body }).catch(() => {});
}

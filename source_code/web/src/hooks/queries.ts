import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import type { Exclusion, JobPage, LibraryPage, ScanStatus, Status } from "../api/types";

export const useStatus = () =>
  useQuery({ queryKey: ["status"], queryFn: () => api.get<Status>("/api/status"), refetchInterval: 5000 });

export const useLibrary = (source?: string, eligibility?: string, offset = 0, limit = 100) =>
  useQuery({
    queryKey: ["library", source, eligibility, offset, limit],
    queryFn: () => {
      const p = new URLSearchParams();
      if (source) p.set("source", source);
      if (eligibility) p.set("eligibility", eligibility);
      p.set("offset", String(offset));
      p.set("limit", String(limit));
      return api.get<LibraryPage>(`/api/library?${p.toString()}`);
    },
  });

export const useJobs = (state?: string) =>
  useQuery({
    queryKey: ["jobs", state],
    queryFn: () => api.get<JobPage>(`/api/jobs${state ? `?state_filter=${state}` : ""}`),
    refetchInterval: 5000,
  });

export const useExclusions = () =>
  useQuery({ queryKey: ["exclusions"], queryFn: () => api.get<Exclusion[]>("/api/exclusions") });

export const useScanStatus = () =>
  useQuery({ queryKey: ["scanStatus"], queryFn: () => api.get<ScanStatus>("/api/scan/status"), refetchInterval: 3000 });

export function useActions() {
  const qc = useQueryClient();
  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["jobs"] });
    qc.invalidateQueries({ queryKey: ["library"] });
    qc.invalidateQueries({ queryKey: ["status"] });
    qc.invalidateQueries({ queryKey: ["exclusions"] });
    qc.invalidateQueries({ queryKey: ["scanStatus"] });
  };
  return {
    scan: useMutation({ mutationFn: (b: object) => api.post("/api/scan", b), onSuccess: invalidate }),
    enqueue: useMutation({ mutationFn: (b: object) => api.post("/api/enqueue", b), onSuccess: invalidate }),
    cancel: useMutation({ mutationFn: (id: number) => api.post(`/api/jobs/${id}/cancel`), onSuccess: invalidate }),
    retry: useMutation({ mutationFn: (id: number) => api.post(`/api/jobs/${id}/retry`), onSuccess: invalidate }),
    addExclusion: useMutation({ mutationFn: (b: object) => api.post("/api/exclusions", b), onSuccess: invalidate }),
    delExclusion: useMutation({ mutationFn: (id: number) => api.del(`/api/exclusions/${id}`), onSuccess: invalidate }),
  };
}

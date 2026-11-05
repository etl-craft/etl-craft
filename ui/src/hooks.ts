import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError, getJson, postJson, project } from "@/lib/api";
import type { Identity, ProjectHealth } from "@/lib/types";

export function useIdentity(code?: string) {
  return useQuery({
    queryKey: ["whoami", code ?? null],
    queryFn: () => getJson<Identity>("/api/v1/whoami", { project: code }),
  });
}

export function useHealth() {
  return useQuery({
    queryKey: ["health"],
    queryFn: () => getJson<ProjectHealth>("/api/v1/project-health"),
    refetchInterval: 30_000,
  });
}

export const useProjectInfo = (code: string | undefined) => {
  const health = useHealth();
  return { ...health, project: health.data?.projects.find((p) => p.project === code) };
};

export { project };

export function useTimezone(): string {
  return useIdentity().data?.settings.timezone ?? "UTC";
}

/** Whether the signed-in account may start and control runs in the project (a viewer may not). */
export function useCanRun(code: string): boolean {
  const identity = useIdentity(code).data;
  const permission = identity?.project_permission;
  return identity?.role === "admin" || permission === "CAN_RUN" || permission === "CAN_MANAGE";
}

/** One POST to the API as the session; every cached read is refreshed after it succeeds. */
export function useWrite<TResult>(path: string, onDone?: (result: TResult) => void) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: unknown) => postJson<TResult>(path, body),
    onSuccess: (result) => {
      onDone?.(result);
      void client.invalidateQueries();
    },
  });
}

export const failureText = (error: unknown): string | null =>
  error instanceof ApiError ? error.message : error ? "The request did not complete." : null;

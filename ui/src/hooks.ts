import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useParams } from "react-router-dom";
import { ApiError, getJson, postJson, project } from "@/lib/api";
import { readProject } from "@/lib/project-memory";
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

/**
 * The project the interface is working in: the one in the address, else the last one opened, else
 * the account's default project, else the only project there is. Each must still be active, so a
 * disabled project is never offered. ``undefined`` means the person has to choose.
 */
export function useActiveProject(): { code: string | undefined; ready: boolean; choices: string[] } {
  const { project: addressed } = useParams();
  const health = useHealth();
  const identity = useIdentity();
  const choices = (health.data?.projects ?? []).map((p) => p.project);
  const ready = health.isSuccess && identity.isSuccess;
  const found = [addressed, readProject(), identity.data?.settings.default_project, choices.length === 1 ? choices[0] : null].find(
    (code) => code && (code === addressed || choices.includes(code)),
  );
  return { code: found ?? undefined, ready, choices };
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

const ORDER = ["viewer", "operator", "developer", "admin"];

/** Whether the signed-in account's deployment role is at least `minimum`. */
export function useRoleAtLeast(minimum: "operator" | "developer" | "admin"): boolean {
  const role = useIdentity().data?.role ?? "viewer";
  return ORDER.indexOf(role) >= ORDER.indexOf(minimum);
}

export const failureText = (error: unknown): string | null =>
  error instanceof ApiError ? error.message : error ? "The request did not complete." : null;

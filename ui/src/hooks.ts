import { useQuery } from "@tanstack/react-query";
import { getJson, project } from "@/lib/api";
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

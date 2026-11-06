import { useQuery } from "@tanstack/react-query";
import { Loading, Notice } from "@/components/common";
import { getJson } from "@/lib/api";

export const ROLES = ["viewer", "operator", "developer", "admin"];
export const done = (message: string) => () => message;

/** One administration list, read on demand and refreshed after any change. */
export function useAdminList<T>(path: string, params?: Record<string, string | boolean | undefined>, enabled = true) {
  return useQuery({ queryKey: ["admin", path, params], queryFn: () => getJson<T>(path, params), enabled });
}

export function ListState({ query, what }: { query: { isError: boolean; isPending: boolean; error: unknown; fetchStatus: string }; what: string }) {
  if (query.isError) return <Notice>{(query.error as Error).message}</Notice>;
  return query.isPending && query.fetchStatus !== "idle" ? <Loading what={what} /> : null;
}

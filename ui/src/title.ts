import { useEffect } from "react";
import { environmentLabel, type EnvironmentInfo } from "@/lib/environment";

/** The tab title starts with the environment, so a PRODUCTION tab is never mistaken for another. */
export function useDocumentTitle(page: string, projectCode?: string, env?: EnvironmentInfo) {
  const label = env ? environmentLabel(env) : null;
  useEffect(() => {
    document.title = [label, projectCode, page, "etl-craft"].filter(Boolean).join(" · ");
  }, [page, projectCode, label]);
}

export interface EnvironmentInfo {
  type: string;
  name: string | null;
}

/** Mirrors the server's label: production is unmistakable, other types keep their name. */
export function environmentLabel(env: EnvironmentInfo): string {
  if (env.type === "PROD") return "PRODUCTION";
  return env.name ? `${env.type} · ${env.name}` : env.type;
}

export const isProduction = (env: EnvironmentInfo): boolean => env.type === "PROD";

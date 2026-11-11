export type Theme = "light" | "dark";
const KEY = "etl-craft-theme";

function stored(): Theme | null {
  try {
    const value = window.localStorage.getItem(KEY);
    return value === "light" || value === "dark" ? value : null;
  } catch {
    return null;
  }
}

export function initialTheme(serverChoice?: string): Theme {
  const choice = stored() ?? (serverChoice === "light" || serverChoice === "dark" ? serverChoice : null);
  if (choice) return choice;
  return window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

export function applyTheme(theme: Theme, remember = false): void {
  document.documentElement.dataset.theme = theme;
  if (!remember) return;
  try {
    window.localStorage.setItem(KEY, theme);
  } catch {
    /* the choice lasts for this page only */
  }
}

export type Density = "compact" | "default" | "comfortable";
const DENSITY_KEY = "etl-craft-density";

export function storedDensity(): Density {
  try {
    const value = window.localStorage.getItem(DENSITY_KEY);
    return value === "compact" || value === "comfortable" ? value : "default";
  } catch {
    return "default";
  }
}

/** Row height for every table, kept in this browser only. */
export function applyDensity(density: Density, remember = false): void {
  document.documentElement.dataset.density = density;
  if (!remember) return;
  try {
    window.localStorage.setItem(DENSITY_KEY, density);
  } catch {
    /* the choice lasts for this page only */
  }
}

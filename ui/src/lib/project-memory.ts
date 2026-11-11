/** The project last opened in this browser, so pages outside a project keep it. */
const KEY = "etl-craft-project";

export function readProject(): string | null {
  try {
    return window.localStorage.getItem(KEY);
  } catch {
    return null;
  }
}

export function rememberProject(code: string): void {
  try {
    window.localStorage.setItem(KEY, code);
  } catch {
    /* the project stays selected for this page only */
  }
}

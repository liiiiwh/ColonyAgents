export type Theme = 'dark' | 'light';
export const THEMES: Theme[] = ['dark', 'light'];
export const DEFAULT_THEME: Theme = 'dark';
export const THEME_STORAGE_KEY = 'colony-theme';

export function isTheme(value: unknown): value is Theme {
  return typeof value === 'string' && (THEMES as string[]).includes(value);
}

// Dark-first: a valid stored choice overrides; anything else → dark.
export function resolveInitialTheme(stored: string | null | undefined): Theme {
  return isTheme(stored) ? stored : DEFAULT_THEME;
}

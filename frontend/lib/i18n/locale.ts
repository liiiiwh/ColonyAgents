import { DEFAULT_LOCALE, LOCALES, type Locale } from './createI18n';

export const LOCALE_STORAGE_KEY = 'colony-locale';

export function isLocale(value: unknown): value is Locale {
  return typeof value === 'string' && (LOCALES as string[]).includes(value);
}

// Default English; a valid stored choice overrides; anything else → English.
export function resolveInitialLocale(stored: string | null | undefined): Locale {
  return isLocale(stored) ? stored : DEFAULT_LOCALE;
}

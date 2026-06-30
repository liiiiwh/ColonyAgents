import i18next, { type i18n } from 'i18next';
import { en } from './locales/en';
import { zh } from './locales/zh';

export type Locale = 'en' | 'zh';
export const LOCALES: Locale[] = ['en', 'zh'];
export const DEFAULT_LOCALE: Locale = 'en';

export const resources = {
  en: { translation: en },
  zh: { translation: zh },
} as const;

// Node-testable factory: no browser language detector here (keeps it pure).
// The app singleton (index.ts) layers detection + persistence on top.
export async function createI18nInstance(lng: Locale = DEFAULT_LOCALE): Promise<i18n> {
  const instance = i18next.createInstance();
  await instance.init({
    resources,
    lng,
    fallbackLng: DEFAULT_LOCALE,
    interpolation: { escapeValue: false },
    returnNull: false,
  });
  return instance;
}

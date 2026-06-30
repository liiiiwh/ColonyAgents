'use client';
import i18next from 'i18next';
import { initReactI18next } from 'react-i18next';
import { resources, DEFAULT_LOCALE, type Locale } from './createI18n';
import { resolveInitialLocale, LOCALE_STORAGE_KEY } from './locale';

export { LOCALES, DEFAULT_LOCALE, type Locale } from './createI18n';
export { LOCALE_STORAGE_KEY, isLocale } from './locale';

let initialized = false;

export function getI18n() {
  if (!initialized) {
    const stored =
      typeof window !== 'undefined' ? window.localStorage.getItem(LOCALE_STORAGE_KEY) : null;
    i18next.use(initReactI18next).init({
      resources,
      lng: resolveInitialLocale(stored),
      fallbackLng: DEFAULT_LOCALE,
      interpolation: { escapeValue: false },
      returnNull: false,
    });
    initialized = true;
  }
  return i18next;
}

export function setLocale(locale: Locale) {
  if (typeof window !== 'undefined') {
    window.localStorage.setItem(LOCALE_STORAGE_KEY, locale);
    document.documentElement.lang = locale === 'zh' ? 'zh-CN' : 'en';
  }
  void i18next.changeLanguage(locale);
}

export function currentLocale(): Locale {
  return (i18next.language as Locale) || DEFAULT_LOCALE;
}

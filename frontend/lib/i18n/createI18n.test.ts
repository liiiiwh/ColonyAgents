import { describe, it, expect } from 'vitest';
import { createI18nInstance } from './createI18n';

describe('createI18nInstance', () => {
  it('defaults to English (EN is the source language)', async () => {
    const i18n = await createI18nInstance();
    expect(i18n.language).toBe('en');
    expect(i18n.t('login.signIn')).toBe('Sign in');
  });
});

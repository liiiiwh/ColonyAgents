import { describe, it, expect } from 'vitest';
import { resolveInitialLocale, isLocale } from './locale';

describe('resolveInitialLocale', () => {
  it('defaults to English when no preference is stored', () => {
    expect(resolveInitialLocale(null)).toBe('en');
  });

  it('honors a valid stored preference', () => {
    expect(resolveInitialLocale('zh')).toBe('zh');
  });

  it('ignores an invalid stored value, falling back to English', () => {
    expect(resolveInitialLocale('fr')).toBe('en');
    expect(resolveInitialLocale('')).toBe('en');
  });
});

describe('isLocale', () => {
  it('recognizes supported locales only', () => {
    expect(isLocale('en')).toBe(true);
    expect(isLocale('zh')).toBe(true);
    expect(isLocale('jp')).toBe(false);
  });
});

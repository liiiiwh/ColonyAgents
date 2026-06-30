import { describe, it, expect } from 'vitest';
import { resolveInitialTheme, isTheme } from './theme';

describe('resolveInitialTheme', () => {
  it('defaults to dark (dark-first design)', () => {
    expect(resolveInitialTheme(null)).toBe('dark');
  });

  it('honors a valid stored theme', () => {
    expect(resolveInitialTheme('light')).toBe('light');
    expect(resolveInitialTheme('dark')).toBe('dark');
  });

  it('ignores an invalid stored value, falling back to dark', () => {
    expect(resolveInitialTheme('blue')).toBe('dark');
  });
});

describe('isTheme', () => {
  it('recognizes supported themes only', () => {
    expect(isTheme('dark')).toBe(true);
    expect(isTheme('light')).toBe(true);
    expect(isTheme('sepia')).toBe(false);
  });
});

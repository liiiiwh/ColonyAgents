import { describe, it, expect } from 'vitest';
import { splitArgs } from './splitArgs';

describe('splitArgs', () => {
  it('splits on whitespace', () => {
    expect(splitArgs('npx some-server')).toEqual(['npx', 'some-server']);
  });

  it('collapses repeated whitespace', () => {
    expect(splitArgs('cmd   a    b')).toEqual(['cmd', 'a', 'b']);
  });

  it('keeps double-quoted args together (e.g. paths with spaces)', () => {
    expect(splitArgs('cmd "a b" c')).toEqual(['cmd', 'a b', 'c']);
  });

  it('keeps single-quoted args together', () => {
    expect(splitArgs("cmd 'a b' c")).toEqual(['cmd', 'a b', 'c']);
  });

  it('handles quotes adjacent to text', () => {
    expect(splitArgs('--path="/a b/c"')).toEqual(['--path=/a b/c']);
  });

  it('returns [] for empty / whitespace-only', () => {
    expect(splitArgs('')).toEqual([]);
    expect(splitArgs('   ')).toEqual([]);
  });
});

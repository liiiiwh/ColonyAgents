import { describe, it, expect } from 'vitest';
import { cleanThreadKey } from './threadLabel';

describe('cleanThreadKey', () => {
  it('main / health → 中文标签', () => {
    expect(cleanThreadKey('main')).toBe('主线');
    expect(cleanThreadKey('health')).toBe('健康自检');
  });
  it('worker:super:wid → Worker · 短id，不暴露双 uuid', () => {
    const tk = 'worker:37283ba4-a11c-490f-bf58-24b5cb55e261:d3e5753c-677c-4995-beda-c4103cb28839';
    const out = cleanThreadKey(tk);
    expect(out).toBe('Worker · d3e5753c');
    expect(out).not.toContain('37283ba4'); // 不暴露 super_id
  });
  it('未知键 → 原样', () => {
    expect(cleanThreadKey('weird')).toBe('weird');
  });
});

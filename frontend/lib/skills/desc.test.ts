import { describe, expect, it } from 'vitest';
import { pickSkillDesc } from './desc';

describe('pickSkillDesc', () => {
  const both = { description: '描述', description_en: 'Description' };

  it('shows English when lang is en and description_en is set', () => {
    expect(pickSkillDesc(both, 'en')).toBe('Description');
    expect(pickSkillDesc(both, 'en-US')).toBe('Description');
  });

  it('shows the default description when lang is zh', () => {
    expect(pickSkillDesc(both, 'zh')).toBe('描述');
    expect(pickSkillDesc(both, 'zh-CN')).toBe('描述');
  });

  it('falls back to description when description_en is empty/null/absent, even in en', () => {
    expect(pickSkillDesc({ description: '描述', description_en: '' }, 'en')).toBe('描述');
    expect(pickSkillDesc({ description: '描述', description_en: null }, 'en')).toBe('描述');
    expect(pickSkillDesc({ description: '描述' }, 'en')).toBe('描述');
  });

  it('falls back to description when lang is undefined', () => {
    expect(pickSkillDesc(both, undefined)).toBe('描述');
  });
});

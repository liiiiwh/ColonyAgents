import '@testing-library/jest-dom/vitest';
import { afterEach } from 'vitest';
import { cleanup } from '@testing-library/react';

// 每个用例后卸载已渲染的组件，避免 DOM 跨用例泄漏。
afterEach(() => {
  cleanup();
});

import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { Button } from './button';

// 样式测试：通过真实 DOM 渲染断言 variant/size 的 class 映射与基础可访问性。
describe('Button', () => {
  it('renders children', () => {
    render(<Button>Click me</Button>);
    expect(screen.getByRole('button', { name: 'Click me' })).toBeInTheDocument();
  });

  it('applies the default variant + size classes', () => {
    render(<Button>x</Button>);
    const btn = screen.getByRole('button');
    expect(btn).toHaveClass('bg-primary', 'text-primary-foreground', 'h-10', 'px-4');
  });

  it('applies the destructive variant and sm size classes', () => {
    render(
      <Button variant="destructive" size="sm">
        x
      </Button>,
    );
    const btn = screen.getByRole('button');
    expect(btn).toHaveClass('bg-destructive', 'text-destructive-foreground', 'h-8', 'text-xs');
    expect(btn).not.toHaveClass('bg-primary');
  });

  it('merges a caller-provided className', () => {
    render(<Button className="custom-cls">x</Button>);
    expect(screen.getByRole('button')).toHaveClass('custom-cls');
  });

  it('reflects the disabled attribute', () => {
    render(<Button disabled>x</Button>);
    expect(screen.getByRole('button')).toBeDisabled();
  });
});

'use client';

import { useState } from 'react';
import { ChevronDown, Sparkles } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';

export type FormCardItem = {
  id: string;
  title?: string;
  description?: string;
  schema: Record<string, unknown>;
  prefilled?: Record<string, unknown>;
  state?: 'pending' | 'submitted';
  submitLabel?: string;
};

export function FormRequestCard({
  item,
  onSubmit,
}: {
  item: FormCardItem;
  onSubmit: (requestId: string, values: Record<string, unknown>) => void;
}) {
  const [values, setValues] = useState<Record<string, unknown>>(item.prefilled || {});
  const schema = item.schema as {
    properties?: Record<string, { type?: string; title?: string; description?: string; enum?: string[] }>;
    required?: string[];
    fieldLabels?: Record<string, string>;
  };
  const props = schema.properties || {};
  const required = new Set(schema.required || []);
  const fieldLabels = schema.fieldLabels || {};

  const disabled = item.state === 'submitted';

  const allRequiredFilled = Array.from(required).every((k) => {
    const v = values[k];
    return v !== undefined && v !== null && String(v).trim() !== '';
  });

  return (
    <div className="mx-auto max-w-[85%] rounded-[14px] border border-primary/30 bg-primary/5 p-4 text-sm">
      <div className="mb-2 flex items-center gap-2">
        <Sparkles className="h-4 w-4 text-primary" />
        <span className="font-semibold text-foreground">表单请求：{item.title}</span>
        {item.state === 'submitted' && (
          <Badge variant="secondary" className="ml-1 text-[10px]">已提交</Badge>
        )}
      </div>
      {item.description && (
        <p className="mb-3 whitespace-pre-wrap text-[12px] text-muted-foreground">{item.description}</p>
      )}
      <div className="space-y-2.5">
        {Object.entries(props).map(([key, def]) => {
          const label = fieldLabels[key] || def.title || key;
          const isRequired = required.has(key);
          const current = values[key] as string | undefined;
          if (def.enum && def.enum.length > 0) {
            return (
              <div key={key}>
                <label className="mb-1 block text-[12px] font-medium text-foreground">
                  {label}
                  {isRequired && <span className="ml-1 text-destructive">*</span>}
                </label>
                <div className="relative">
                  <select
                    disabled={disabled}
                    value={current ?? ''}
                    onChange={(e) => setValues((prev) => ({ ...prev, [key]: e.target.value }))}
                    className="w-full appearance-none rounded-[8px] border border-border bg-card pl-2 pr-7 py-1.5 text-sm disabled:opacity-60"
                  >
                    <option value="">— 请选择 —</option>
                    {def.enum.map((o) => (
                      <option key={o} value={o}>
                        {o}
                      </option>
                    ))}
                  </select>
                  <ChevronDown className="pointer-events-none absolute right-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
                </div>
                {def.description && (
                  <p className="mt-0.5 text-[10px] text-muted-foreground">{def.description}</p>
                )}
              </div>
            );
          }
          return (
            <div key={key}>
              <label className="mb-1 block text-[12px] font-medium text-foreground">
                {label}
                {isRequired && <span className="ml-1 text-destructive">*</span>}
              </label>
              <input
                disabled={disabled}
                value={current ?? ''}
                onChange={(e) => setValues((prev) => ({ ...prev, [key]: e.target.value }))}
                placeholder={def.description || ''}
                className="w-full rounded-[8px] border border-border bg-card px-2 py-1.5 text-sm disabled:opacity-60"
              />
              {def.description && (
                <p className="mt-0.5 text-[10px] text-muted-foreground">{def.description}</p>
              )}
            </div>
          );
        })}
      </div>
      <div className="mt-3 flex items-center justify-end gap-2">
        {!allRequiredFilled && !disabled && (
          <span className="text-[11px] text-destructive">请填写所有必填字段</span>
        )}
        <Button
          size="sm"
          onClick={() => onSubmit(item.id, values)}
          disabled={disabled || !allRequiredFilled}
        >
          {disabled ? '已提交' : (item.submitLabel || '提交')}
        </Button>
      </div>
    </div>
  );
}

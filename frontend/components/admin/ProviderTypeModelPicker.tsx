'use client';

import { useEffect, useMemo } from 'react';

import { Label } from '@/components/ui/label';
import { Select } from '@/components/ui/select';
import type { LLMModelPublic, LLMModelType, ProviderPublic } from '@/types/provider';

/**
 * 三段式模型选择器：Provider → Type → Model。
 *
 * - Provider 选完后自动 lazy-load 该 provider 的模型清单；
 * - Type 下拉只展示**该 provider 当前确有模型**的类型，避免出现空类型选项；
 * - Model 下拉根据 (provider, type) 联合过滤；
 * - 当 lockType 传入时（如绑 image 辅助模型场景），Type 锁定不可改。
 *
 * 受控组件：所有状态由父组件持有，便于多个 picker 共享 modelsByProvider 缓存。
 */
export type ProviderTypeModelPickerLayout = 'inline' | 'stacked';

interface Props {
  providers: ProviderPublic[];
  modelsByProvider: Record<string, LLMModelPublic[]>;
  loadModelsFor: (providerId: string) => Promise<LLMModelPublic[]>;

  providerId: string;
  modelType: LLMModelType | '';
  modelId: string;

  onChangeProvider: (id: string) => void;
  onChangeType: (t: LLMModelType | '') => void;
  onChangeModel: (id: string) => void;

  /** 锁定 Type（绑 image / video 辅助模型时强制类型一致）。 */
  lockType?: LLMModelType;
  /** 仅允许这些类型出现在 type 下拉里（如批量改主模型只让选 chat）。 */
  allowedTypes?: LLMModelType[];
  /** Provider 占位（"— 不改 —" / "— 选择 —"），不传默认 "— 选择 —"。 */
  providerPlaceholder?: string;
  disabled?: boolean;
  layout?: ProviderTypeModelPickerLayout;
  required?: boolean;
}

const TYPE_LABEL: Record<LLMModelType, string> = {
  chat: 'Chat',
  image: 'Image',
  video: 'Video',
  embedding: 'Embedding',
  completion: 'Completion',
};

export function ProviderTypeModelPicker({
  providers,
  modelsByProvider,
  loadModelsFor,
  providerId,
  modelType,
  modelId,
  onChangeProvider,
  onChangeType,
  onChangeModel,
  lockType,
  allowedTypes,
  providerPlaceholder = '— 选择 —',
  disabled = false,
  layout = 'stacked',
  required = false,
}: Props) {
  // 选了 provider 后异步拉模型
  useEffect(() => {
    if (providerId && !modelsByProvider[providerId]) {
      void loadModelsFor(providerId);
    }
  }, [providerId, modelsByProvider, loadModelsFor]);

  const allModels = useMemo(
    () => (providerId ? modelsByProvider[providerId] ?? [] : []),
    [providerId, modelsByProvider],
  );

  // 该 provider 下确实存在的类型集合
  const availableTypes = useMemo(() => {
    const set = new Set<LLMModelType>();
    for (const m of allModels) if (m.is_enabled) set.add(m.model_type);
    let arr = (['chat', 'image', 'video', 'embedding', 'completion'] as LLMModelType[]).filter(
      (t) => set.has(t),
    );
    if (allowedTypes) arr = arr.filter((t) => allowedTypes.includes(t));
    return arr;
  }, [allModels, allowedTypes]);

  const effectiveType: LLMModelType | '' = lockType ?? modelType;

  // 当 provider 切换 / lockType 解锁后，自动校正 type 到第一个可用值
  useEffect(() => {
    if (lockType) return; // 锁定时父组件保证
    if (effectiveType && !availableTypes.includes(effectiveType as LLMModelType)) {
      onChangeType(availableTypes[0] ?? '');
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [availableTypes, lockType]);

  // Model 候选 = provider × type
  const modelOptions = useMemo(() => {
    const filterType = effectiveType || null;
    return allModels.filter(
      (m) => m.is_enabled && (filterType ? m.model_type === filterType : true),
    );
  }, [allModels, effectiveType]);

  // provider 变了或 type 变了之后，校验当前 modelId 是否还在候选中；不在则清空
  useEffect(() => {
    if (modelId && !modelOptions.some((m) => m.id === modelId)) {
      onChangeModel('');
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [providerId, effectiveType]);

  const colCls =
    layout === 'inline' ? 'grid grid-cols-3 gap-2' : 'grid grid-cols-1 gap-3 sm:grid-cols-3';
  return (
    <div className={colCls}>
      <div className="space-y-1">
        <Label className="text-[11px] text-neutral-600">Provider</Label>
        <Select
          value={providerId}
          onChange={(e) => onChangeProvider(e.target.value)}
          disabled={disabled}
          required={required}
        >
          <option value="">{providerPlaceholder}</option>
          {providers
            .filter((p) => p.is_enabled)
            .map((p) => (
              <option key={p.id} value={p.id}>
                {p.name} ({p.provider_type})
              </option>
            ))}
        </Select>
      </div>
      <div className="space-y-1">
        <Label className="text-[11px] text-neutral-600">Type</Label>
        <Select
          value={effectiveType}
          onChange={(e) => onChangeType(e.target.value as LLMModelType | '')}
          disabled={disabled || !providerId || !!lockType}
          required={required}
        >
          {!providerId && <option value="">— 请先选 Provider —</option>}
          {providerId && availableTypes.length === 0 && <option value="">— 无可用模型 —</option>}
          {providerId &&
            !lockType &&
            !required &&
            availableTypes.length > 0 && <option value="">— 任意类型 —</option>}
          {(lockType ? [lockType] : availableTypes).map((t) => (
            <option key={t} value={t}>
              {TYPE_LABEL[t]}
            </option>
          ))}
        </Select>
      </div>
      <div className="space-y-1">
        <Label className="text-[11px] text-neutral-600">Model</Label>
        <Select
          value={modelId}
          onChange={(e) => onChangeModel(e.target.value)}
          disabled={disabled || !providerId || modelOptions.length === 0}
          required={required}
        >
          {!providerId && <option value="">— 请先选 Provider —</option>}
          {providerId && modelOptions.length === 0 && <option value="">— 无可用模型 —</option>}
          {providerId && modelOptions.length > 0 && <option value="">— 选择 —</option>}
          {modelOptions.map((m) => (
            <option key={m.id} value={m.id}>
              {m.display_name}
              {m.display_name !== m.model_id ? `（${m.model_id}）` : ''}
            </option>
          ))}
        </Select>
      </div>
    </div>
  );
}

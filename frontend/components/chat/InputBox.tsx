'use client';

import { useEffect, useRef } from 'react';
import {
  ArrowUp,
  File as FileIcon,
  Image as ImageIcon,
  Loader2,
  Paperclip,
  Square,
  X,
} from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { cn } from '@/lib/utils';

export interface PendingAttachment {
  id: string;
  kind: 'image' | 'file';
  name: string;
  size: number;
  url: string | null;
  key: string | null;
  mediaType: string;
  uploading: boolean;
  error?: string;
}

interface InputBoxProps {
  value: string;
  onChange: (v: string) => void;
  onSubmit: () => void;
  onAddFiles: (files: FileList | File[]) => void;
  attachments: PendingAttachment[];
  onRemoveAttachment: (id: string) => void;
  placeholder?: string;
  disabled?: boolean;
  sending?: boolean;
  /** 用户点暂停键时调用：取消当前 turn（后端 cancel asyncio.Task + 关 SSE）。
   *  没传则按钮不允许点（fallback 显示 loading 不可交互）。 */
  onCancel?: () => void;
}

export function InputBox({
  value,
  onChange,
  onSubmit,
  onAddFiles,
  attachments,
  onRemoveAttachment,
  placeholder,
  disabled,
  sending,
  onCancel,
}: InputBoxProps) {
  const { t } = useTranslation();
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const effectivePlaceholder = placeholder ?? t('chat.inputPlaceholder');

  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = Math.min(el.scrollHeight, 180) + 'px';
  }, [value]);

  const onKey = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      if (!disabled && (value.trim() || attachments.length > 0)) onSubmit();
    }
  };

  const canSend =
    !disabled &&
    !sending &&
    !attachments.some((a) => a.uploading) &&
    (value.trim() || attachments.length > 0);

  return (
    <div className="px-6 pb-4 pt-2 bg-gradient-to-t from-background via-background to-transparent">
      <div className="max-w-[780px] mx-auto">
        {/* 附件预览 */}
        {attachments.length > 0 && (
          <div className="mb-2 flex flex-wrap gap-1.5">
            {attachments.map((a) => (
              <AttachmentChip key={a.id} att={a} onRemove={() => onRemoveAttachment(a.id)} />
            ))}
          </div>
        )}

        <div
          className={cn(
            'relative bg-card border border-border rounded-[14px] transition-colors',
            'focus-within:border-primary/40',
            disabled && 'opacity-70',
          )}
          onDrop={(e) => {
            e.preventDefault();
            if (e.dataTransfer.files.length > 0) onAddFiles(e.dataTransfer.files);
          }}
          onDragOver={(e) => e.preventDefault()}
        >
          <input
            ref={fileInputRef}
            type="file"
            multiple
            className="hidden"
            onChange={(e) => {
              if (e.target.files) onAddFiles(e.target.files);
              e.target.value = '';
            }}
          />

          <textarea
            ref={textareaRef}
            value={value}
            onChange={(e) => onChange(e.target.value)}
            onPaste={(e) => {
              const items = e.clipboardData.items;
              const files: File[] = [];
              for (let i = 0; i < items.length; i++) {
                const item = items[i];
                if (item.kind === 'file') {
                  const f = item.getAsFile();
                  if (!f) continue;
                  // 浏览器粘贴的截图 File.name 偶尔为空（系统剪贴板源）—— 补个默认名，
                  // 防止后端 `400 缺少文件名` 静默失败。保留扩展名让 S3 content_type 正确。
                  // D7：name 用 timestamp + 4 字符随机后缀防毫秒级碰撞
                  if (!f.name) {
                    const ext = (f.type.split('/')[1] || 'bin').split('+')[0];
                    const rand = Math.random().toString(36).slice(2, 6);
                    const renamed = new File([f], `pasted-${Date.now()}-${rand}.${ext}`, { type: f.type });
                    files.push(renamed);
                  } else {
                    files.push(f);
                  }
                }
              }
              if (files.length > 0) {
                e.preventDefault();
                // 图文混合粘贴（如带图网页 → 同时含 text/plain + image/png）：
                // preventDefault 会把文本部分也阻止，需要手动把文本插回 textarea 当前光标位置
                // D8：用 textareaRef.current 实时读 value（DOM 真值），不依赖 React 闭包里可能 stale 的 value
                const pastedText = e.clipboardData.getData('text/plain');
                if (pastedText) {
                  const el = textareaRef.current;
                  if (el) {
                    const liveValue = el.value;  // DOM 真值，避免闭包 stale
                    const start = el.selectionStart ?? liveValue.length;
                    const end = el.selectionEnd ?? liveValue.length;
                    onChange(liveValue.slice(0, start) + pastedText + liveValue.slice(end));
                  } else {
                    onChange(value + pastedText);
                  }
                }
                onAddFiles(files);
              }
            }}
            onKeyDown={onKey}
            rows={1}
            placeholder={sending ? t('chat.sendingDisabled') : effectivePlaceholder}
            disabled={disabled}
            readOnly={sending}
            className={cn(
              'w-full resize-none bg-transparent px-4 pt-3 pb-11 text-[14px]',
              'placeholder:text-muted-foreground/70 focus:outline-none',
              'max-h-[180px] overflow-y-auto scrollbar-thin',
              // D9：sending=true 时视觉反馈
              sending && 'opacity-60 cursor-not-allowed',
            )}
          />

          <div className="absolute bottom-2.5 left-3 right-2.5 flex items-center justify-between">
            <button
              type="button"
              onClick={() => fileInputRef.current?.click()}
              disabled={disabled || sending}
              className="p-1.5 text-muted-foreground/70 hover:text-muted-foreground transition disabled:cursor-not-allowed"
              title={t('chat.addAttachment')}
            >
              <Paperclip className="w-3.5 h-3.5" />
            </button>
            {sending && onCancel ? (
              <button
                type="button"
                onClick={onCancel}
                className={cn(
                  'h-7 w-7 rounded-full flex items-center justify-center transition-all',
                  'bg-foreground text-background hover:bg-foreground/85 active:scale-95',
                )}
                aria-label={t('chat.stopGenerating')}
                title={t('chat.stopSession')}
              >
                <Square className="w-3 h-3 fill-current" />
              </button>
            ) : (
              <button
                type="button"
                onClick={onSubmit}
                disabled={!canSend}
                className={cn(
                  'h-7 w-7 rounded-full flex items-center justify-center transition-all',
                  canSend
                    ? 'bg-primary text-primary-foreground hover:bg-primary/90 active:scale-95'
                    : 'bg-muted text-muted-foreground/60 cursor-not-allowed',
                )}
                aria-label={t('chat.send')}
              >
                {sending ? (
                  <Loader2 className="w-3.5 h-3.5 animate-spin" />
                ) : (
                  <ArrowUp className="w-3.5 h-3.5" />
                )}
              </button>
            )}
          </div>
        </div>

        <p className="mt-1.5 text-[10.5px] text-muted-foreground/70 text-center">
          {t('chat.aiDisclaimer')}
        </p>
      </div>
    </div>
  );
}

function AttachmentChip({
  att,
  onRemove,
}: {
  att: PendingAttachment;
  onRemove: () => void;
}) {
  const Icon = att.kind === 'image' ? ImageIcon : FileIcon;
  return (
    <div className="flex items-center gap-1.5 rounded-[8px] border border-border bg-card px-2 py-1 text-[12px]">
      <Icon className="h-3.5 w-3.5 text-muted-foreground" />
      <span className="max-w-[140px] truncate font-medium text-foreground">{att.name}</span>
      <span className="text-muted-foreground">{formatSize(att.size)}</span>
      {att.uploading && <Loader2 className="h-3 w-3 animate-spin text-muted-foreground" />}
      {att.error && <span className="text-destructive text-[11px]">{att.error}</span>}
      <button
        onClick={onRemove}
        className="ml-0.5 flex h-4 w-4 items-center justify-center rounded hover:bg-muted"
      >
        <X className="h-3 w-3 text-muted-foreground" />
      </button>
    </div>
  );
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

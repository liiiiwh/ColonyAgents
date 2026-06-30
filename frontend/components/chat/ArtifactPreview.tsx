'use client';

/**
 * v5 · 消息中带 artifact_url 时按 media_type 自动渲染
 */
import { useState } from 'react';
import { Download, ExternalLink, FileText, Image as ImageIcon, Code as CodeIcon } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';

export type ArtifactMeta = {
  url: string;
  name?: string;
  mediaType?: string;
  size?: number;
};

function detectKind(media?: string, url?: string): string {
  const m = (media || '').toLowerCase();
  if (m.startsWith('image/')) return 'image';
  if (m === 'application/pdf') return 'pdf';
  if (m === 'application/json' || m === 'text/json') return 'json';
  if (m.startsWith('video/')) return 'video';
  if (m.startsWith('audio/')) return 'audio';
  if (m === 'text/markdown') return 'markdown';
  // fallback by extension
  const u = (url || '').toLowerCase();
  if (/\.(png|jpe?g|gif|webp|svg|avif)$/.test(u)) return 'image';
  if (u.endsWith('.pdf')) return 'pdf';
  if (u.endsWith('.json')) return 'json';
  if (/\.(mp4|webm|mov)$/.test(u)) return 'video';
  if (/\.(mp3|wav|ogg)$/.test(u)) return 'audio';
  if (u.endsWith('.md')) return 'markdown';
  return 'file';
}

export function ArtifactPreview({ artifact }: { artifact: ArtifactMeta }) {
  const { t } = useTranslation();
  const kind = detectKind(artifact.mediaType, artifact.url);
  const [expanded, setExpanded] = useState(false);
  const sizeKB = artifact.size ? (artifact.size / 1024).toFixed(1) : null;
  const displayName = artifact.name || artifact.url.split('/').pop() || 'artifact';

  if (kind === 'image') {
    return (
      <div className="inline-block my-2">
        <img
          src={artifact.url}
          alt={displayName}
          className={`rounded border border-border cursor-zoom-in transition ${
            expanded ? 'max-w-full' : 'max-w-xs max-h-48 object-cover'
          }`}
          onClick={() => setExpanded((v) => !v)}
        />
        <div className="text-[10px] text-muted-foreground flex gap-2 mt-0.5">
          <ImageIcon className="w-3 h-3" />
          <span className="truncate flex-1">{displayName}</span>
          {sizeKB && <span>{sizeKB}KB</span>}
          <a href={artifact.url} download className="underline">{t('chat.download')}</a>
        </div>
      </div>
    );
  }

  if (kind === 'pdf') {
    return (
      <div className="my-2 border border-border rounded overflow-hidden max-w-3xl">
        <div className="bg-muted px-2 py-1 text-xs flex items-center gap-2">
          <FileText className="w-3.5 h-3.5" />
          <span className="flex-1 truncate">{displayName}</span>
          {sizeKB && <span className="text-muted-foreground">{sizeKB}KB</span>}
          <a href={artifact.url} target="_blank" rel="noreferrer" className="text-primary underline">
            {t('chat.open')}
          </a>
        </div>
        <iframe src={artifact.url} className="w-full h-96" title={displayName} />
      </div>
    );
  }

  if (kind === 'video') {
    return (
      <div className="my-2 max-w-md">
        <video controls src={artifact.url} className="w-full rounded border border-border" />
        <div className="text-[10px] text-muted-foreground mt-0.5">{displayName}</div>
      </div>
    );
  }

  if (kind === 'audio') {
    return (
      <div className="my-2 max-w-md">
        <audio controls src={artifact.url} className="w-full" />
        <div className="text-[10px] text-muted-foreground mt-0.5">{displayName}</div>
      </div>
    );
  }

  if (kind === 'json' || kind === 'markdown') {
    return (
      <div className="my-2 max-w-3xl">
        <div className="text-xs flex items-center gap-2 mb-1">
          <CodeIcon className="w-3.5 h-3.5" />
          <span className="font-mono truncate flex-1">{displayName}</span>
          <Button
            size="sm"
            variant="ghost"
            onClick={() => setExpanded((v) => !v)}
            className="h-5 px-1.5 text-[10px]"
          >
            {expanded ? t('chat.collapse') : t('chat.inlinePreview')}
          </Button>
          <a
            href={artifact.url}
            target="_blank"
            rel="noreferrer"
            className="text-primary underline text-[10px]"
          >
            {t('chat.open')}
          </a>
        </div>
        {expanded && (
          <iframe
            src={artifact.url}
            className="w-full h-64 border border-border rounded"
            title={displayName}
          />
        )}
      </div>
    );
  }

  // fallback
  return (
    <a
      href={artifact.url}
      target="_blank"
      rel="noreferrer"
      className="inline-flex items-center gap-1.5 text-xs text-primary hover:underline my-1"
    >
      <Download className="w-3 h-3" />
      <span>{displayName}</span>
      {sizeKB && <span className="text-muted-foreground">({sizeKB}KB)</span>}
      <ExternalLink className="w-3 h-3" />
    </a>
  );
}

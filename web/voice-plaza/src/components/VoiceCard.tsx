import { Skeleton } from '@heroui/react';
import { cn } from '../lib/utils';
import { voiceArt } from '../lib/voiceArt';
import { formatCount, voiceChips } from '../lib/constants';
import type { Voice } from '../lib/types';
import {
  CheckIcon,
  CopyIcon,
  PauseIcon,
  PlayIcon,
  StarIcon,
  XIcon,
} from './icons';

export type CopyState = 'idle' | 'copied' | 'failed';

type VoiceActionProps = {
  voice: Voice;
  copyState: CopyState;
  playing?: boolean;
  previewFailed?: boolean;
  onCopy: (text: string, key: string) => void;
  onTogglePlay?: (voice: Voice) => void;
};

function VoiceAvatar({
  voice,
  size = 36,
  playing = false,
  previewFailed = false,
  onTogglePlay,
}: {
  voice: Voice;
  size?: number;
  playing?: boolean;
  previewFailed?: boolean;
  onTogglePlay?: (voice: Voice) => void;
}) {
  const art = voiceArt(voice.name);
  const label = voice.label || voice.name;

  if (!onTogglePlay) {
    return (
      <span
        aria-hidden="true"
        className="shrink-0 rounded-full"
        style={{ width: size, height: size, background: art.avatar }}
      />
    );
  }

  return (
    <button
      aria-label={
        playing
          ? `停止试听 ${label}`
          : previewFailed
            ? `重新试听 ${label}`
            : `试听 ${label}`
      }
      aria-pressed={playing}
      className="group/avatar relative shrink-0 rounded-full outline-none focus-visible:ring-2 focus-visible:ring-accent/40 focus-visible:ring-offset-2 focus-visible:ring-offset-background"
      onClick={() => onTogglePlay(voice)}
      style={{ width: size, height: size }}
      type="button"
    >
      <span
        aria-hidden="true"
        className="block size-full rounded-full"
        style={{ background: art.avatar }}
      />
      <span
        aria-hidden="true"
        className={cn(
          'absolute inset-0 grid place-items-center rounded-full bg-black/40 text-white transition-opacity',
          playing
            ? 'opacity-100'
            : 'opacity-0 group-hover/avatar:opacity-100 max-sm:opacity-100',
        )}
      >
        {playing ? (
          <PauseIcon className="size-4" />
        ) : (
          <PlayIcon className="size-4 translate-x-px" />
        )}
      </span>
      {playing && (
        <span
          aria-hidden="true"
          className="absolute inset-0 rounded-full ring-2 ring-accent ring-offset-2 ring-offset-background"
        />
      )}
    </button>
  );
}

function Chips({ voice, limit = 3 }: { voice: Voice; limit?: number }) {
  const chips = voiceChips(voice, limit);
  if (chips.length === 0) return null;

  return (
    <div className="flex min-w-0 items-center gap-1.5 overflow-hidden">
      {chips.map((chip) => (
        <span
          className="inline-flex shrink-0 items-center gap-1.5 rounded-full border border-border px-2 py-1 text-[11px] leading-4 font-medium text-muted"
          key={`${chip.label}-${chip.dot ?? ''}`}
        >
          {chip.dot && (
            <span
              aria-hidden="true"
              className="size-2 rounded-full"
              style={{ background: chip.dot }}
            />
          )}
          {chip.label}
        </span>
      ))}
    </div>
  );
}

function Stats({ voice, className }: { voice: Voice; className?: string }) {
  const uses = Number(voice.uses) || 0;
  const favorites = Number(voice.favorites) || 0;
  if (uses === 0 && favorites === 0) return null;

  return (
    <div
      className={cn(
        'shrink-0 items-center gap-2.5 text-[11px] text-muted tabular-nums',
        className,
      )}
    >
      {uses > 0 && (
        <span
          className="inline-flex items-center gap-1"
          title={`被点歌 ${formatCount(uses)} 次`}
        >
          <PlayIcon className="size-2.5" />
          {formatCount(uses)}
        </span>
      )}
      {favorites > 0 && (
        <span
          className="inline-flex items-center gap-1"
          title={`上游收藏 ${formatCount(favorites)}`}
        >
          <StarIcon className="size-2.5" />
          {formatCount(favorites)}
        </span>
      )}
    </div>
  );
}

function CopyAction({
  voice,
  copyState,
  onCopy,
}: {
  voice: Voice;
  copyState: CopyState;
  onCopy: (text: string, key: string) => void;
}) {
  return (
    <button
      aria-label={
        copyState === 'copied'
          ? `已复制音色名 ${voice.name}`
          : `复制音色名 ${voice.name}`
      }
      className={cn(
        'inline-flex h-7 shrink-0 items-center gap-1 rounded-full px-3 text-[11.5px] font-medium transition-colors',
        copyState === 'copied'
          ? 'bg-success/15 text-success hover:bg-success/20'
          : copyState === 'failed'
            ? 'bg-danger/10 text-danger hover:bg-danger/15'
            : 'bg-foreground text-background hover:bg-foreground/85',
      )}
      onClick={() => onCopy(voice.name, voice.name)}
      type="button"
    >
      {copyState === 'copied' ? (
        <CheckIcon className="size-3" />
      ) : copyState === 'failed' ? (
        <XIcon className="size-3" />
      ) : (
        <CopyIcon className="size-3" />
      )}
      {copyState === 'copied' ? '已复制' : copyState === 'failed' ? '失败' : '复制'}
    </button>
  );
}

/** Compact recommendation card (three-up on desktop). */
export function VoiceTile({
  voice,
  copyState,
  playing = false,
  previewFailed = false,
  onCopy,
  onTogglePlay,
}: VoiceActionProps) {
  const title = voice.label || voice.name;

  return (
    <article className="group flex min-h-[108px] min-w-0 flex-col justify-between gap-3 rounded-xl border border-border bg-background px-4 py-3 transition-colors hover:bg-surface-secondary/70 sm:px-5">
      <div className="flex min-w-0 items-center gap-3">
        <VoiceAvatar
          onTogglePlay={onTogglePlay}
          playing={playing}
          previewFailed={previewFailed}
          voice={voice}
        />
        <div className="min-w-0 flex-1">
          <p
            className="truncate text-[13.5px] leading-5 font-medium text-foreground"
            title={title}
          >
            {title}
          </p>
          <p
            className="truncate font-mono text-[11.5px] leading-5 text-muted"
            title={voice.name}
          >
            {voice.name}
          </p>
        </div>
        <Stats className="hidden sm:flex" voice={voice} />
      </div>

      <div className="flex min-w-0 items-center gap-2">
        <div className="min-w-0 flex-1">
          <Chips voice={voice} />
        </div>
        <CopyAction copyState={copyState} onCopy={onCopy} voice={voice} />
      </div>
    </article>
  );
}

/** Dense one-line result row for the full catalog. */
export function VoiceRow({
  voice,
  copyState,
  playing = false,
  previewFailed = false,
  onCopy,
  onTogglePlay,
}: VoiceActionProps) {
  const title = voice.label || voice.name;

  return (
    <article className="group flex min-h-[66px] min-w-0 items-center gap-3 rounded-xl px-3 py-2.5 transition-colors hover:bg-surface-secondary/70">
      <VoiceAvatar
        onTogglePlay={onTogglePlay}
        playing={playing}
        previewFailed={previewFailed}
        voice={voice}
      />

      <div className="min-w-0 flex-1">
        <p
          className="truncate text-[13.5px] leading-5 font-medium text-foreground"
          title={title}
        >
          {title}
        </p>
        <div className="mt-0.5 flex min-w-0 items-center gap-2">
          <p
            className="truncate font-mono text-[11px] leading-4 text-muted"
            title={voice.name}
          >
            {voice.name}
          </p>
          <span className="md:hidden">
            <Chips limit={2} voice={voice} />
          </span>
        </div>
      </div>

      <div className="hidden shrink-0 md:block">
        <Chips voice={voice} />
      </div>
      <Stats className="hidden lg:flex" voice={voice} />
      <CopyAction copyState={copyState} onCopy={onCopy} voice={voice} />
    </article>
  );
}

/** Tall gradient tile for the horizontal "featured" strip. */
export function FeatureTile({
  voice,
  playing = false,
  onTogglePlay,
  onCopy,
}: {
  voice: Voice;
  playing?: boolean;
  onTogglePlay?: (voice: Voice) => void;
  onCopy: (text: string, key: string) => void;
}) {
  const title = voice.label || voice.name;
  const art = voiceArt(voice.name);
  const initial = title.trim().charAt(0).toUpperCase();

  return (
    <button
      aria-label={
        onTogglePlay && voice.preview_url
          ? playing
            ? `停止试听 ${title}`
            : `试听 ${title}`
          : `复制音色名 ${voice.name}`
      }
      className="group relative aspect-[3/4] w-[168px] shrink-0 snap-start overflow-hidden rounded-xl text-left outline-none focus-visible:ring-2 focus-visible:ring-accent/40 max-sm:w-[148px]"
      onClick={() =>
        onTogglePlay && voice.preview_url
          ? onTogglePlay(voice)
          : onCopy(voice.name, voice.name)
      }
      type="button"
    >
      <span
        aria-hidden="true"
        className="absolute inset-0"
        style={{ background: art.tile }}
      />
      <span
        aria-hidden="true"
        className="absolute -top-4 -right-3 text-[96px] leading-none font-black text-white/10 select-none"
      >
        {initial}
      </span>
      <span
        aria-hidden="true"
        className="absolute inset-0 bg-gradient-to-t from-black/60 via-black/5 to-transparent"
      />
      <span className="absolute inset-x-0 bottom-0 p-3">
        <span className="line-clamp-2 text-[13px] leading-5 font-semibold text-white">
          {title}
        </span>
        <span className="mt-1 block truncate font-mono text-[10px] text-white/60">
          {voice.name}
        </span>
      </span>
      <span
        aria-hidden="true"
        className={cn(
          'absolute top-2.5 right-2.5 grid size-8 place-items-center rounded-full bg-black/30 text-white backdrop-blur transition-opacity',
          playing ? 'opacity-100' : 'opacity-0 group-hover:opacity-100',
        )}
      >
        {playing ? (
          <PauseIcon className="size-4" />
        ) : (
          <PlayIcon className="size-4 translate-x-px" />
        )}
      </span>
    </button>
  );
}

export function VoiceTileSkeleton() {
  return (
    <div className="flex min-h-[108px] flex-col justify-between gap-3 rounded-xl border border-border bg-background px-4 py-3 sm:px-5">
      <div className="flex items-center gap-3">
        <Skeleton className="size-9 shrink-0 rounded-full" />
        <div className="min-w-0 flex-1 space-y-1.5">
          <Skeleton className="h-3.5 w-4/5 rounded" />
          <Skeleton className="h-3 w-3/5 rounded" />
        </div>
      </div>
      <div className="flex items-center justify-between gap-2">
        <div className="flex gap-1.5">
          <Skeleton className="h-[24px] w-12 rounded-full" />
          <Skeleton className="h-[24px] w-10 rounded-full" />
        </div>
        <Skeleton className="h-7 w-16 rounded-full" />
      </div>
    </div>
  );
}

export function VoiceRowSkeleton() {
  return (
    <div className="flex min-h-[66px] items-center gap-3 px-3 py-2.5">
      <Skeleton className="size-9 shrink-0 rounded-full" />
      <div className="min-w-0 flex-1 space-y-1.5">
        <Skeleton className="h-3.5 w-1/3 rounded" />
        <Skeleton className="h-3 w-1/2 rounded" />
      </div>
      <Skeleton className="hidden h-6 w-24 rounded-full md:block" />
      <Skeleton className="h-7 w-16 rounded-full" />
    </div>
  );
}

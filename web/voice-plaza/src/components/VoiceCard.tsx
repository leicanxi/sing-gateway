import { Button, Card, Chip, Skeleton } from '@heroui/react';
import { formatCount, voiceChips } from '../lib/constants';
import type { Voice } from '../lib/types';
import { CheckIcon, PlayIcon, StarIcon, XIcon } from './icons';

export type CopyState = 'idle' | 'copied' | 'failed';

type VoiceCardProps = {
  voice: Voice;
  copyState: CopyState;
  playing?: boolean;
  previewFailed?: boolean;
  onCopy: (text: string, key: string) => void;
  onTogglePlay?: (voice: Voice) => void;
};

const NEUTRAL_CHIP = 'border-border bg-surface-secondary text-muted';
const ACCENT_CHIP = 'border-accent/20 bg-accent-soft text-accent-soft-foreground';

export function VoiceCard({
  voice,
  copyState,
  playing = false,
  previewFailed = false,
  onCopy,
  onTogglePlay,
}: VoiceCardProps) {
  const title = voice.label || voice.name;
  const chips = voiceChips(voice, 4);
  const uses = Number(voice.uses) || 0;
  const favorites = Number(voice.favorites) || 0;
  const canPlay = Boolean(voice.preview_url && onTogglePlay);

  return (
    <Card
      className={['card-hover h-full', playing ? 'ring-2 ring-accent/35' : ''].join(' ')}
    >
      <Card.Header className="gap-3">
        <div className="flex items-start gap-3">
          <Card.Title
            className="line-clamp-2 min-h-[2.9em] min-w-0 flex-1 text-[14.5px] leading-[1.45] font-semibold tracking-[-0.01em]"
            title={title}
          >
            {title}
          </Card.Title>
          {(uses > 0 || favorites > 0) && (
            <div className="mt-0.5 flex shrink-0 items-center gap-2.5 text-[11px] text-muted tabular-nums">
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
          )}
        </div>

        <div className="flex flex-wrap gap-1.5">
          {chips.map((chip) => (
            <Chip
              className={`h-[22px] border px-2 text-[11px] leading-[20px] ${
                chip.accent ? ACCENT_CHIP : NEUTRAL_CHIP
              }`}
              color="default"
              key={chip.label}
              size="sm"
              variant="soft"
            >
              {chip.label}
            </Chip>
          ))}
        </div>
      </Card.Header>

      <Card.Content className="flex-none gap-2.5">
        {voice.author && (
          <p className="text-[11.5px] text-muted">by {voice.author}</p>
        )}

        <code className="slug w-full" title={voice.name}>
          {voice.name}
        </code>

        <div className="flex items-center justify-between gap-2">
          {canPlay ? (
            <Button
              aria-label={playing ? `停止试听 ${title}` : `试听 ${title}`}
              aria-pressed={playing}
              className={[
                'h-7 gap-1.5 rounded-full border px-3 text-[12px]',
                playing
                  ? 'border-accent bg-accent text-accent-foreground'
                  : 'border-border bg-surface text-foreground/75 hover:bg-surface-secondary',
              ].join(' ')}
              onPress={() => onTogglePlay?.(voice)}
              size="sm"
              variant="ghost"
            >
              {playing ? (
                <span className="eq text-accent-foreground">
                  <i />
                  <i />
                  <i />
                </span>
              ) : (
                <PlayIcon className="size-3" />
              )}
              <span className={previewFailed && !playing ? 'text-danger' : undefined}>
                {playing ? '播放中' : previewFailed ? '试听失败' : '试听'}
              </span>
            </Button>
          ) : (
            <span />
          )}

          <Button
            aria-label={
              copyState === 'copied'
                ? `已复制音色名 ${voice.name}`
                : `复制音色名 ${voice.name}`
            }
            className={[
              'h-7 shrink-0 gap-1 rounded-full px-3 text-[12px] font-medium',
              copyState === 'copied'
                ? 'bg-accent text-accent-foreground hover:bg-accent-hover'
                : 'bg-accent-soft text-accent hover:bg-accent/15',
            ].join(' ')}
            onPress={() => onCopy(voice.name, voice.name)}
            size="sm"
            variant="ghost"
          >
            {copyState === 'copied' ? (
              <>
                <CheckIcon className="size-3" />
                已复制
              </>
            ) : copyState === 'failed' ? (
              <>
                <XIcon className="size-3" />
                失败
              </>
            ) : (
              '复制'
            )}
          </Button>
        </div>
      </Card.Content>
    </Card>
  );
}

export function VoiceCardSkeleton() {
  return (
    <Card className="h-full">
      <Card.Header className="gap-3">
        <div className="space-y-2">
          <Skeleton className="h-4 w-4/5 rounded" />
          <Skeleton className="h-4 w-2/5 rounded" />
        </div>
        <div className="flex gap-1.5">
          <Skeleton className="h-[22px] w-12 rounded-full" />
          <Skeleton className="h-[22px] w-12 rounded-full" />
          <Skeleton className="h-[22px] w-16 rounded-full" />
        </div>
      </Card.Header>
      <Card.Content className="flex-none gap-2.5">
        <Skeleton className="h-7 w-full rounded-lg" />
        <div className="flex justify-between">
          <Skeleton className="h-7 w-20 rounded-full" />
          <Skeleton className="h-7 w-16 rounded-full" />
        </div>
      </Card.Content>
    </Card>
  );
}

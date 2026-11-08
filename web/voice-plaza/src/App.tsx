import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { Button } from '@heroui/react';
import { BrowseToolbar } from './components/BrowseToolbar';
import { MobileNav } from './components/MobileNav';
import { PassCard } from './components/PassCard';
import { Sidebar } from './components/Sidebar';
import { Topbar } from './components/Topbar';
import { UploadDrawer } from './components/UploadDrawer';
import {
  FeatureTile,
  VoiceRow,
  VoiceRowSkeleton,
  VoiceTile,
  VoiceTileSkeleton,
  type CopyState,
} from './components/VoiceCard';
import {
  ChevronLeftIcon,
  ChevronRightIcon,
  PlusIcon,
  SparkIcon,
} from './components/icons';
import { useCopyFeedback } from './hooks/useCopyFeedback';
import { useDebouncedValue } from './hooks/useDebouncedValue';
import { fetchCatalog, fetchCommunity } from './lib/api';
import {
  COMMUNITY_SORT_OPTIONS,
  GENDER_OPTIONS,
  GENDER_VALUES,
  LANGUAGE_OPTIONS,
  LANGUAGE_VALUES,
  SORT_OPTIONS,
  SORT_VALUES,
  formatCount,
} from './lib/constants';
import type { Account, TabKey, Voice } from './lib/types';

type CommunitySort = 'new' | 'hot';

function pick<T extends string>(value: string | null, allowed: readonly T[], fallback: T): T {
  return value && (allowed as readonly string[]).includes(value) ? (value as T) : fallback;
}

function readInitialState() {
  const params = new URLSearchParams(window.location.search);
  return {
    tab: params.get('tab') === 'community' ? ('community' as const) : ('catalog' as const),
    search: params.get('q') ?? '',
    sort: pick(params.get('sort'), SORT_VALUES, 'hot'),
    language: pick(params.get('lang'), LANGUAGE_VALUES, ''),
    gender: pick(params.get('gender'), GENDER_VALUES, ''),
  };
}

function prefersReducedMotion() {
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

function SectionHeader({
  title,
  hint,
  right,
  actions,
}: {
  title: string;
  hint?: string;
  right?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <div className="mb-3 flex min-h-8 items-center justify-between gap-3">
      <div className="flex min-w-0 items-center gap-2">
        <h2 className="truncate text-[16px] font-semibold tracking-[-0.01em]">
          {title}
        </h2>
        {hint && <span className="shrink-0 text-[11.5px] text-muted">{hint}</span>}
      </div>
      <div className="flex shrink-0 items-center gap-2">
        {right}
        {actions}
      </div>
    </div>
  );
}

export default function App() {
  const initial = useMemo(readInitialState, []);

  const [tab, setTab] = useState<TabKey>(initial.tab);
  const [search, setSearch] = useState(initial.search);
  const [sort, setSort] = useState<string>(initial.sort);
  const [language, setLanguage] = useState(initial.language);
  const [gender, setGender] = useState(initial.gender);
  const [uploadOpen, setUploadOpen] = useState(false);
  const [account, setAccount] = useState<Account | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);

  const debouncedSearch = useDebouncedValue(search, 220);

  const [items, setItems] = useState<Voice[]>([]);
  const [total, setTotal] = useState(0);
  const [nextOffset, setNextOffset] = useState<number | null>(null);
  const [status, setStatus] = useState<'loading' | 'ready' | 'error'>('loading');
  const [loadingMore, setLoadingMore] = useState(false);
  const [loadMoreFailed, setLoadMoreFailed] = useState(false);

  const [communitySort, setCommunitySort] = useState<CommunitySort>('new');
  const [community, setCommunity] = useState<Voice[]>([]);
  const [communityStatus, setCommunityStatus] = useState<
    'idle' | 'loading' | 'ready' | 'error'
  >('idle');

  const [playing, setPlaying] = useState<string | null>(null);
  const [previewFailed, setPreviewFailed] = useState<string | null>(null);

  const sentinelRef = useRef<HTMLDivElement>(null);
  const railRef = useRef<HTMLDivElement>(null);
  const searchInputRef = useRef<HTMLInputElement>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const playingRef = useRef<string | null>(null);
  const loadingMoreRef = useRef(false);
  const catalogRef = useRef({ items, total, nextOffset });
  const queryKey = `${debouncedSearch}\u0000${sort}\u0000${language}\u0000${gender}`;
  const queryKeyRef = useRef(queryKey);
  const { feedback: copyFeedback, copy } = useCopyFeedback();

  catalogRef.current = { items, total, nextOffset };
  queryKeyRef.current = queryKey;

  const stopPreview = useCallback(() => {
    const audio = audioRef.current;
    if (audio) {
      audio.pause();
      audio.removeAttribute('src');
      audio.load();
    }
    playingRef.current = null;
    setPlaying(null);
  }, []);

  const togglePreview = useCallback(
    (voice: Voice) => {
      if (!voice.preview_url) return;
      if (playingRef.current === voice.name) {
        stopPreview();
        return;
      }

      let audio = audioRef.current;
      if (!audio) {
        audio = new Audio();
        audio.preload = 'none';
        audio.addEventListener('ended', () => {
          playingRef.current = null;
          setPlaying(null);
        });
        audio.addEventListener('error', () => {
          const failed = playingRef.current;
          playingRef.current = null;
          setPlaying(null);
          if (failed) setPreviewFailed(failed);
        });
        audioRef.current = audio;
      }

      stopPreview();
      setPreviewFailed(null);
      playingRef.current = voice.name;
      setPlaying(voice.name);
      audio.src = voice.preview_url;
      audio.play().catch(() => {
        if (playingRef.current !== voice.name) return;
        playingRef.current = null;
        setPlaying(null);
        setPreviewFailed(voice.name);
      });
    },
    [stopPreview],
  );

  useEffect(() => () => stopPreview(), [stopPreview]);

  // `/` focuses the catalog search field from anywhere on the page.
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== '/' || event.metaKey || event.ctrlKey || event.altKey) return;
      const target = event.target as HTMLElement | null;
      if (
        target &&
        (target.tagName === 'INPUT' ||
          target.tagName === 'TEXTAREA' ||
          target.isContentEditable)
      ) {
        return;
      }
      event.preventDefault();
      searchInputRef.current?.focus();
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, []);

  // Catalog page 0: driven by the debounced query and the three filters.
  useEffect(() => {
    if (tab !== 'catalog') return;
    const controller = new AbortController();
    stopPreview();
    setStatus('loading');
    setLoadMoreFailed(false);

    fetchCatalog(
      { q: debouncedSearch.trim(), sort, lang: language, gender, offset: 0 },
      controller.signal,
    )
      .then((page) => {
        if (controller.signal.aborted) return;
        setItems(page.items);
        setTotal(page.total);
        setNextOffset(page.nextOffset);
        setStatus('ready');
      })
      .catch((error) => {
        if (controller.signal.aborted) return;
        console.error('加载音色目录失败：', error);
        setItems([]);
        setTotal(0);
        setNextOffset(null);
        setStatus('error');
      });

    return () => controller.abort();
  }, [tab, debouncedSearch, sort, language, gender, refreshKey, stopPreview]);

  const loadMore = useCallback(async () => {
    const page = catalogRef.current;
    if (loadingMoreRef.current || page.nextOffset === null) return;
    const expectedKey = queryKeyRef.current;
    loadingMoreRef.current = true;
    setLoadingMore(true);
    setLoadMoreFailed(false);

    try {
      const next = await fetchCatalog({
        q: debouncedSearch.trim(),
        sort,
        lang: language,
        gender,
        offset: page.nextOffset,
      });
      if (queryKeyRef.current !== expectedKey) return;
      setItems((current) => [...current, ...next.items]);
      setTotal(next.total);
      setNextOffset(next.nextOffset);
    } catch (error) {
      if (queryKeyRef.current === expectedKey) {
        console.error('加载更多音色失败：', error);
        setLoadMoreFailed(true);
      }
    } finally {
      loadingMoreRef.current = false;
      setLoadingMore(false);
    }
  }, [debouncedSearch, sort, language, gender]);

  useEffect(() => {
    const sentinel = sentinelRef.current;
    if (!sentinel || tab !== 'catalog' || status !== 'ready' || nextOffset === null) return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) void loadMore();
      },
      { rootMargin: '600px 0px' },
    );
    observer.observe(sentinel);
    return () => observer.disconnect();
  }, [tab, status, nextOffset, loadMore]);

  useEffect(() => {
    if (tab !== 'community') return;
    const controller = new AbortController();
    setCommunityStatus('loading');
    fetchCommunity(communitySort, controller.signal)
      .then((voices) => {
        if (controller.signal.aborted) return;
        setCommunity(voices);
        setCommunityStatus('ready');
      })
      .catch((error) => {
        if (controller.signal.aborted) return;
        console.error('加载社区公开音色失败：', error);
        setCommunityStatus('error');
      });
    return () => controller.abort();
  }, [tab, communitySort]);

  // Who is signed in (the avatar menu and the upload dialog depend on it).
  useEffect(() => {
    fetch('/v1/auth/me', { cache: 'no-store' })
      .then((response) => (response.ok ? response.json() : null))
      .then((payload: Account | null) => setAccount(payload ?? null))
      .catch(() => setAccount(null));
  }, []);

  // `/?upload=1` (and the legacy /upload.html redirect) opens the dialog once.
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (params.get('upload') !== '1') return;
    setUploadOpen(true);
    params.delete('upload');
    const query = params.toString();
    window.history.replaceState(
      null,
      '',
      `${window.location.pathname}${query ? `?${query}` : ''}${window.location.hash}`,
    );
  }, []);

  // Keep the address bar shareable: filters and the active tab survive a reload.
  useEffect(() => {
    const params = new URLSearchParams();
    if (tab === 'community') params.set('tab', 'community');
    const trimmed = search.trim();
    if (trimmed) params.set('q', trimmed);
    if (tab === 'catalog' && sort !== 'hot') params.set('sort', sort);
    if (language) params.set('lang', language);
    if (gender) params.set('gender', gender);
    const query = params.toString();
    window.history.replaceState(
      null,
      '',
      `${window.location.pathname}${query ? `?${query}` : ''}${window.location.hash}`,
    );
  }, [tab, search, sort, language, gender]);

  useEffect(() => {
    const onPopState = () => {
      const next = readInitialState();
      setTab(next.tab);
      setSearch(next.search);
      setSort(next.sort);
      setLanguage(next.language);
      setGender(next.gender);
    };
    window.addEventListener('popstate', onPopState);
    return () => window.removeEventListener('popstate', onPopState);
  }, []);

  const changeTab = (next: TabKey) => {
    if (next === tab) return;
    stopPreview();
    setTab(next);
    window.scrollTo({ top: 0, behavior: 'auto' });
  };

  const clearFilters = () => {
    setSearch('');
    setLanguage('');
    setGender('');
  };

  const scrollRail = (direction: number) => {
    railRef.current?.scrollBy({
      left: direction * 360,
      behavior: prefersReducedMotion() ? 'auto' : 'smooth',
    });
  };

  const hasFilters = Boolean(search.trim() || language || gender);
  const showSkeleton = status === 'loading' && items.length === 0;
  const isRefreshing = status === 'loading' && items.length > 0;
  const showCurated =
    tab === 'catalog' &&
    !hasFilters &&
    sort === 'hot' &&
    status === 'ready' &&
    items.length > 0;

  const countLabel =
    status === 'error'
      ? '加载失败'
      : showSkeleton
        ? '正在加载…'
        : `${hasFilters ? '找到 ' : '共 '}${formatCount(total)} 个音色`;

  const communityQuery = search.trim().toLowerCase();
  const filteredCommunity = useMemo(() => {
    if (!communityQuery) return community;
    return community.filter((voice) => {
      const haystack = [voice.label, voice.name, voice.author, ...(voice.tags ?? [])]
        .filter(Boolean)
        .join(' ')
        .toLowerCase();
      return haystack.includes(communityQuery);
    });
  }, [community, communityQuery]);

  const communityCountLabel =
    communityStatus === 'loading'
      ? '正在加载…'
      : communityStatus === 'error'
        ? '加载失败'
        : `${formatCount(filteredCommunity.length)} 个公开音色`;

  const copyStateFor = (name: string): CopyState => {
    if (!copyFeedback || copyFeedback.key !== name) return 'idle';
    return copyFeedback.ok ? 'copied' : 'failed';
  };

  const cardProps = (voice: Voice) => ({
    copyState: copyStateFor(voice.name),
    onCopy: copy,
    onTogglePlay: voice.preview_url ? togglePreview : undefined,
    playing: playing === voice.name,
    previewFailed: previewFailed === voice.name,
    voice,
  });

  const emptyState = (
    <div className="rounded-xl border border-dashed border-border bg-surface px-6 py-16 text-center">
      <SparkIcon className="mx-auto size-6 text-muted/70" />
      <p className="mt-3 text-sm font-semibold">
        {hasFilters ? '没有找到匹配的音色' : '音色目录暂无内容'}
      </p>
      <p className="mx-auto mt-1.5 max-w-md text-[13px] leading-relaxed text-muted">
        {hasFilters
          ? '试试更短的关键词、英文名或罗马音，也可以清除筛选浏览全部目录。'
          : '目录还在同步中，稍后刷新试试。'}
      </p>
      {hasFilters && (
        <Button className="mt-4" onPress={clearFilters} size="sm" variant="secondary">
          清除筛选
        </Button>
      )}
    </div>
  );

  const listSection = (
    <section className={showCurated ? 'mt-8' : ''}>
      <SectionHeader
        right={
          <span className="text-[13px] font-medium text-muted tabular-nums">
            {countLabel}
          </span>
        }
        title={hasFilters ? '搜索结果' : '全部音色'}
      />

      {status === 'error' ? (
        <div className="flex flex-wrap items-center gap-3 rounded-xl border border-danger/25 bg-danger-soft p-4">
          <p className="text-[13px] text-danger">音色目录加载失败，请检查网络后重试。</p>
          <Button
            className="ml-auto"
            onPress={() => setRefreshKey((key) => key + 1)}
            size="sm"
            variant="secondary"
          >
            重新加载
          </Button>
        </div>
      ) : showSkeleton ? (
        <div className="flex flex-col gap-0.5">
          {Array.from({ length: 8 }, (_, index) => (
            <VoiceRowSkeleton key={index} />
          ))}
        </div>
      ) : items.length === 0 ? (
        emptyState
      ) : (
        <>
          <div
            className={[
              'flex flex-col gap-0.5',
              isRefreshing ? 'opacity-55' : '',
            ].join(' ')}
          >
            {items.map((voice) => (
              <VoiceRow key={voice.name} {...cardProps(voice)} />
            ))}
          </div>

          <div aria-hidden="true" className="h-px w-full" ref={sentinelRef} />

          <div className="mt-6 flex flex-col items-center gap-2">
            {loadingMore && <span className="text-xs text-muted">正在加载更多…</span>}
            {loadMoreFailed && (
              <button
                className="text-xs text-danger hover:underline"
                onClick={() => void loadMore()}
                type="button"
              >
                这一页没加载出来，点这里重试
              </button>
            )}
            {nextOffset !== null && (
              <Button
                isDisabled={loadingMore || status !== 'ready'}
                onPress={() => void loadMore()}
                size="sm"
                variant="secondary"
              >
                {loadingMore ? '加载中…' : '加载更多'}
              </Button>
            )}
            {nextOffset === null && items.length > 0 && (
              <p className="text-xs text-muted">已经到底了</p>
            )}
          </div>
        </>
      )}
    </section>
  );

  const catalogContent = (
    <>
      {showCurated && (
        <>
          <section>
            <SectionHeader hint="按点歌热度" title="为你推荐" />
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
              {items.slice(0, 6).map((voice) => (
                <VoiceTile key={voice.name} {...cardProps(voice)} />
              ))}
            </div>
          </section>

          <section className="mt-8">
            <SectionHeader
              actions={
                <div className="hidden items-center gap-1 sm:flex">
                  <button
                    aria-label="向左浏览精选音色"
                    className="grid size-8 place-items-center rounded-full border border-border bg-surface text-muted transition-colors hover:bg-surface-secondary hover:text-foreground"
                    onClick={() => scrollRail(-1)}
                    type="button"
                  >
                    <ChevronLeftIcon className="size-4" />
                  </button>
                  <button
                    aria-label="向右浏览精选音色"
                    className="grid size-8 place-items-center rounded-full border border-border bg-surface text-muted transition-colors hover:bg-surface-secondary hover:text-foreground"
                    onClick={() => scrollRail(1)}
                    type="button"
                  >
                    <ChevronRightIcon className="size-4" />
                  </button>
                </div>
              }
              title="精选音色"
            />
            <div
              className="no-scrollbar -mx-4 flex snap-x snap-mandatory gap-3 overflow-x-auto px-4 pb-1 sm:mx-0 sm:px-0"
              ref={railRef}
            >
              {items.slice(6, 20).map((voice) => (
                <FeatureTile
                  key={voice.name}
                  onCopy={copy}
                  onTogglePlay={voice.preview_url ? togglePreview : undefined}
                  playing={playing === voice.name}
                  voice={voice}
                />
              ))}
            </div>
          </section>
        </>
      )}

      {listSection}
    </>
  );

  const communityContent =
    communityStatus === 'error' ? (
      <div className="rounded-xl border border-danger/25 bg-danger-soft p-4">
        <p className="text-[13px] text-danger">社区分享音色加载失败，请稍后重试。</p>
      </div>
    ) : communityStatus === 'loading' && community.length === 0 ? (
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {Array.from({ length: 6 }, (_, index) => (
          <VoiceTileSkeleton key={index} />
        ))}
      </div>
    ) : community.length === 0 ? (
      <div className="rounded-xl border border-dashed border-border bg-surface px-6 py-16 text-center">
        <SparkIcon className="mx-auto size-6 text-muted/70" />
        <p className="mt-3 text-sm font-semibold">还没有公开的音色</p>
        <p className="mx-auto mt-1.5 max-w-md text-[13px] leading-relaxed text-muted">
          上传自己的 RVC 模型，审核通过后选择公开，就会出现在这里。
        </p>
        <Button
          className="mt-4 !bg-foreground !text-background hover:!bg-foreground/85"
          onPress={() => setUploadOpen(true)}
          size="sm"
        >
          上传音色
        </Button>
      </div>
    ) : filteredCommunity.length === 0 ? (
      <div className="rounded-xl border border-dashed border-border bg-surface px-6 py-16 text-center">
        <SparkIcon className="mx-auto size-6 text-muted/70" />
        <p className="mt-3 text-sm font-semibold">没有找到匹配的音色</p>
        <p className="mx-auto mt-1.5 max-w-md text-[13px] leading-relaxed text-muted">
          试试更短的关键词，或清除搜索看看全部公开音色。
        </p>
        <Button
          className="mt-4"
          onPress={() => setSearch('')}
          size="sm"
          variant="secondary"
        >
          清除搜索
        </Button>
      </div>
    ) : (
      <>
        <SectionHeader
          hint={communitySort === 'hot' ? '按使用次数' : '按公开时间'}
          right={
            <span className="text-[13px] font-medium text-muted tabular-nums">
              {communityCountLabel}
            </span>
          }
          title="社区公开音色"
        />
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {filteredCommunity.map((voice) => (
            <VoiceTile key={voice.name} {...cardProps(voice)} />
          ))}
        </div>
        {community.length >= 100 && (
          <p className="mt-6 text-center text-xs text-muted">
            只显示最近 100 个公开音色
          </p>
        )}
      </>
    );

  return (
    <div className="min-h-dvh bg-background">
      <a className="skip-link" href="#main">
        跳到主要内容
      </a>

      <Sidebar active={tab} onOpenUpload={() => setUploadOpen(true)} onSelect={changeTab} />

      <div className="flex min-h-dvh flex-col lg:pl-[220px]">
        <Topbar account={account} onOpenUpload={() => setUploadOpen(true)} />

        <main className="flex-1" id="main" tabIndex={-1}>
          <div className="mx-auto w-full max-w-[1228px] px-4 pt-6 pb-28 sm:px-6 lg:px-8 lg:pb-16">
            <header className="flex flex-wrap items-end justify-between gap-3">
              <div>
                <h1 className="text-2xl font-semibold tracking-[-0.02em]">
                  音色广场
                </h1>
                <p className="mt-1 text-[13px] text-muted">
                  挑一个音色名字，去聊天里点歌。
                </p>
              </div>
              <button
                className="inline-flex h-10 shrink-0 items-center gap-1.5 rounded-full bg-foreground px-4 text-[13px] font-medium text-background transition-colors hover:bg-foreground/85 focus-visible:ring-2 focus-visible:ring-accent/40 focus-visible:outline-none"
                onClick={() => setUploadOpen(true)}
                type="button"
              >
                <PlusIcon className="size-4" />
                上传音色
              </button>
            </header>

            <div className="mt-5">
              <BrowseToolbar
                communitySort={communitySort}
                communitySortOptions={COMMUNITY_SORT_OPTIONS}
                gender={gender}
                genderOptions={GENDER_OPTIONS}
                language={language}
                languageOptions={LANGUAGE_OPTIONS}
                onCommunitySortChange={(value) => {
                  stopPreview();
                  setCommunitySort(value === 'hot' ? 'hot' : 'new');
                }}
                onGenderChange={setGender}
                onLanguageChange={setLanguage}
                onSearchChange={setSearch}
                onSortChange={setSort}
                onTabChange={changeTab}
                search={search}
                searchInputRef={searchInputRef}
                sort={sort}
                sortOptions={SORT_OPTIONS}
                tab={tab}
              />
            </div>

            <div className="mt-6">
              {tab === 'catalog' ? catalogContent : communityContent}
            </div>
          </div>
        </main>

        <footer className="border-t border-border">
          <div className="mx-auto w-full max-w-[1228px] px-4 py-8 sm:px-6 lg:px-8">
            <div className="flex flex-wrap items-start justify-between gap-6">
              <div>
                <p className="text-[13px] font-semibold">音色广场</p>
                <p className="mt-1 text-xs text-muted">
                  社区分享的 RVC 音色目录 · 网关源码{' '}
                  <a
                    className="text-accent hover:underline"
                    href="https://github.com/leicanxi/sing-gateway"
                    rel="noopener noreferrer"
                    target="_blank"
                  >
                    sing-gateway
                  </a>
                </p>
              </div>
              <div className="text-xs leading-relaxed text-muted">
                <p>
                  插件：
                  <a
                    className="text-accent hover:underline"
                    href="https://github.com/leicanxi/astrbot_plugin_deepseek_sing"
                    rel="noopener noreferrer"
                    target="_blank"
                  >
                    AstrBot
                  </a>
                  <span className="mx-1.5 text-muted/40">·</span>
                  <a
                    className="text-accent hover:underline"
                    href="https://github.com/leicanxi/dsh-sing"
                    rel="noopener noreferrer"
                    target="_blank"
                  >
                    DSH
                  </a>
                </p>
                <p className="mt-1">
                  <button
                    className="text-accent hover:underline"
                    onClick={() => setUploadOpen(true)}
                    type="button"
                  >
                    上传音色
                  </button>
                  <span className="mx-1.5 text-muted/40">·</span>
                  <a className="text-accent hover:underline" href="./account.html">
                    我的音色
                  </a>
                </p>
              </div>
            </div>
            <p className="mt-6 border-t border-border pt-4 text-[11.5px] leading-relaxed text-muted/80">
              音色模型来自社区公开分享，版权归原作者所有；如有侵权请联系删除。本站以
              AGPL-3.0-or-later 发布。
            </p>
          </div>
        </footer>
      </div>

      <MobileNav
        active={tab}
        onOpenUpload={() => setUploadOpen(true)}
        onSelect={changeTab}
      />

      <PassCard />

      <UploadDrawer account={account} onOpenChange={setUploadOpen} open={uploadOpen} />
    </div>
  );
}

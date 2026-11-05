import { useCallback, useEffect, useState } from 'react';
import { Button, Card, Chip, Skeleton } from '@heroui/react';
import { useCopyFeedback } from '../hooks/useCopyFeedback';
import { GENDER_LABEL, LANGUAGE_LABEL } from '../lib/constants';
import type { Account } from '../lib/types';
import { CheckIcon, CopyIcon, LogInIcon, UploadIcon } from '../components/icons';

type Submission = {
  id: string;
  name?: string;
  label?: string;
  status?: string;
  created_at?: number;
  language?: string;
  gender?: string;
  tags?: string[];
  reason?: string;
  visibility?: string;
};

type Phase = 'loading' | 'gate' | 'ready' | 'error';

const STATUS_LABEL: Record<string, string> = {
  approved: '已通过',
  rejected: '未通过',
  deleted: '已删除',
};

function statusColor(status: string): 'success' | 'danger' | 'default' {
  if (status === 'approved') return 'success';
  if (status === 'rejected') return 'danger';
  return 'default';
}

function chipsFor(item: Submission): string[] {
  const chips: string[] = [];
  const language = item.language ? LANGUAGE_LABEL[item.language] : '';
  if (language) chips.push(language);
  const gender = item.gender ? GENDER_LABEL[item.gender] : '';
  if (gender) chips.push(gender);
  for (const raw of item.tags ?? []) {
    const tag = String(raw ?? '').trim();
    if (tag && !chips.includes(tag)) chips.push(tag);
  }
  return chips.slice(0, 5);
}

function formatTime(seconds?: number): string {
  if (!seconds) return '';
  try {
    return new Date(seconds * 1000).toLocaleString('zh-CN', { hour12: false });
  } catch {
    return '';
  }
}

function shareText(name: string): string {
  return `用音色 ${name} 唱一首《歌名》试试：/点歌 歌名 ${name}`;
}

export function AccountPage() {
  const [phase, setPhase] = useState<Phase>('loading');
  const [me, setMe] = useState<Account | null>(null);
  const [submissions, setSubmissions] = useState<Submission[]>([]);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [notice, setNotice] = useState('');
  const { feedback, copy } = useCopyFeedback();

  const load = useCallback(async () => {
    setPhase('loading');
    try {
      const meResponse = await fetch('/v1/auth/me', { cache: 'no-store' });
      if (meResponse.status === 401) {
        setPhase('gate');
        return;
      }
      if (!meResponse.ok) throw new Error(`HTTP ${meResponse.status}`);
      const profile = (await meResponse.json()) as Account;

      const response = await fetch('/v1/voice-requests/mine', { cache: 'no-store' });
      if (response.status === 401) {
        setPhase('gate');
        return;
      }
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const payload = (await response.json()) as { submissions?: Submission[] };

      setMe(profile);
      setSubmissions(Array.isArray(payload.submissions) ? payload.submissions : []);
      setPhase('ready');
    } catch (error) {
      console.error('加载我的音色失败：', error);
      setPhase('error');
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  // A failed login redirect comes back with ?login=failed.
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (params.get('login') === 'failed') {
      const reason = params.get('reason');
      setNotice(reason ? `登录失败：${reason}` : '登录失败，请重试。');
    }
  }, []);

  const toggleVisibility = async (item: Submission) => {
    const isPublic = item.visibility === 'public';
    setBusyId(item.id);
    setNotice('');
    try {
      const response = await fetch(
        `/v1/voice-requests/${encodeURIComponent(item.id)}/${isPublic ? 'unpublish' : 'publish'}`,
        { method: 'POST' },
      );
      if (response.status === 401) {
        setPhase('gate');
        return;
      }
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      await load();
    } catch (error) {
      console.error('切换公开状态失败：', error);
      setNotice('操作失败，请稍后重试。');
    } finally {
      setBusyId(null);
    }
  };

  const remove = async (item: Submission) => {
    const label = item.label || item.name || '';
    const confirmed = window.confirm(
      `确定删除「${label}」吗？删除后该音色名将无法再用于点歌，已上传的模型文件也会一并删除。`,
    );
    if (!confirmed) return;
    setBusyId(item.id);
    setNotice('');
    try {
      const response = await fetch(
        `/v1/voice-requests/${encodeURIComponent(item.id)}`,
        { method: 'DELETE' },
      );
      if (response.status === 401) {
        setPhase('gate');
        return;
      }
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      await load();
    } catch (error) {
      console.error('删除失败：', error);
      setNotice('删除失败，请稍后重试。');
    } finally {
      setBusyId(null);
    }
  };

  const logout = async () => {
    try {
      await fetch('/v1/auth/logout', { method: 'POST' });
    } catch {
      // ignore; the gate shows either way
    }
    setMe(null);
    setSubmissions([]);
    setPhase('gate');
  };

  return (
    <div className="flex min-h-dvh flex-col bg-background">
      <header className="sticky top-0 z-40 border-b border-border bg-background/85 backdrop-blur-xl">
        <div className="mx-auto flex h-16 w-full max-w-[880px] items-center gap-2 px-4 sm:px-6">
          <a className="flex items-center gap-2.5" href="./">
            <img
              alt="音色广场"
              className="h-8 w-auto"
              height="32"
              src="./logo-wordmark.png"
              width="79"
            />
          </a>
          <span className="text-muted">/</span>
          <span className="text-[13px] text-muted">我的音色</span>
          <div className="ml-auto flex items-center gap-2">
            <Button
              className="h-9 gap-1.5 rounded-full"
              onPress={() => {
                window.location.href = './?upload=1';
              }}
              size="sm"
            >
              <UploadIcon className="size-3.5" />
              上传音色
            </Button>
          </div>
        </div>
      </header>

      <main className="mx-auto w-full max-w-[880px] flex-1 px-4 py-6 sm:px-6">
        <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
          <div>
            <h1 className="text-[22px] font-semibold tracking-[-0.02em]">我的音色</h1>
            <p className="mt-1 text-[12.5px] text-muted">
              审核通过的音色可以用名字点歌，也可以公开到广场。
            </p>
          </div>
          {me && (
            <p className="text-[12px] text-muted">
              {me.name || me.username}
              <span className="mx-1.5 text-muted/40">·</span>
              <button
                className="text-accent hover:underline"
                onClick={() => void logout()}
                type="button"
              >
                退出登录
              </button>
            </p>
          )}
        </div>

        {notice && (
          <p className="mb-4 rounded-xl border border-danger/25 bg-danger-soft px-3 py-2 text-[12.5px] text-danger">
            {notice}
          </p>
        )}

        {phase === 'gate' && (
          <Card className="max-w-[560px]">
            <Card.Header className="gap-1">
              <Card.Title className="text-[15px]">需要先登录 FlowBee 账号</Card.Title>
              <Card.Description>
                登录后可以查看你提交的音色、复制音色名，或公开到广场。
              </Card.Description>
            </Card.Header>
            <Card.Footer>
              <Button
                className="gap-1.5"
                onPress={() => {
                  window.location.href = '/v1/auth/login?next=/account.html';
                }}
              >
                <LogInIcon className="size-4" />
                使用 FlowBee 账号登录
              </Button>
            </Card.Footer>
          </Card>
        )}

        {phase === 'loading' && (
          <div className="space-y-3">
            {Array.from({ length: 3 }, (_, index) => (
              <Card key={index}>
                <Card.Header className="gap-2">
                  <Skeleton className="h-5 w-2/5 rounded" />
                  <Skeleton className="h-4 w-3/5 rounded" />
                </Card.Header>
                <Card.Content>
                  <Skeleton className="h-8 w-full rounded-lg" />
                </Card.Content>
              </Card>
            ))}
          </div>
        )}

        {phase === 'error' && (
          <Card className="max-w-[560px]">
            <Card.Header className="gap-1">
              <Card.Title className="text-[15px]">加载失败</Card.Title>
              <Card.Description>请检查网络后重试。</Card.Description>
            </Card.Header>
            <Card.Footer>
              <Button onPress={() => void load()} variant="secondary">
                重新加载
              </Button>
            </Card.Footer>
          </Card>
        )}

        {phase === 'ready' && submissions.length === 0 && (
          <div className="rounded-2xl border border-dashed border-border bg-surface px-6 py-14 text-center">
            <p className="text-[14px] font-semibold">还没有提交过音色</p>
            <p className="mx-auto mt-1.5 max-w-sm text-[12.5px] leading-relaxed text-muted">
              上传自己的 RVC 模型，审核通过后会生成一个专属音色名。
            </p>
            <Button
              className="mt-4 gap-1.5"
              onPress={() => {
                window.location.href = './?upload=1';
              }}
              size="sm"
            >
              <UploadIcon className="size-3.5" />
              上传音色
            </Button>
          </div>
        )}

        {phase === 'ready' && submissions.length > 0 && (
          <ul className="space-y-3">
            {submissions.map((item) => {
              const approved = item.status === 'approved' && Boolean(item.name);
              const isPublic = item.visibility === 'public';
              const chips = chipsFor(item);
              const created = formatTime(item.created_at);
              const busy = busyId === item.id;

              return (
                <li key={item.id}>
                  <Card>
                    <Card.Header className="gap-2">
                      <div className="flex flex-wrap items-center gap-2">
                        <Card.Title className="text-[15px]">
                          {item.label || item.name || '未命名音色'}
                        </Card.Title>
                        <Chip
                          color={statusColor(item.status ?? '')}
                          size="sm"
                          variant="soft"
                        >
                          {STATUS_LABEL[item.status ?? ''] || item.status}
                        </Chip>
                        {approved && (
                          <Chip
                            color={isPublic ? 'accent' : 'default'}
                            size="sm"
                            variant="soft"
                          >
                            {isPublic ? '已公开' : '未公开'}
                          </Chip>
                        )}
                        {created && (
                          <span className="ml-auto text-[11.5px] text-muted tabular-nums">
                            {created}
                          </span>
                        )}
                      </div>

                      {chips.length > 0 && (
                        <div className="flex flex-wrap gap-1.5">
                          {chips.map((chip) => (
                            <Chip
                              className="h-[22px] border border-border bg-surface-secondary px-2 text-[11px] leading-[20px] text-muted"
                              color="default"
                              key={chip}
                              size="sm"
                              variant="soft"
                            >
                              {chip}
                            </Chip>
                          ))}
                        </div>
                      )}
                    </Card.Header>

                    {(approved || item.reason) && (
                      <Card.Content className="gap-2.5">
                        {approved && (
                          <div className="flex items-center gap-2">
                            <code className="slug">{item.name}</code>
                            <Button
                              aria-label={`复制音色名 ${item.name}`}
                              className="h-8 shrink-0 gap-1 whitespace-nowrap rounded-lg bg-accent-soft px-2.5 text-[12px] font-medium text-accent hover:bg-accent/15"
                              onPress={() => void copy(item.name ?? '', `name-${item.id}`)}
                              size="sm"
                              variant="ghost"
                            >
                              {feedback?.key === `name-${item.id}` && feedback.ok ? (
                                <>
                                  <CheckIcon className="size-3" />
                                  已复制
                                </>
                              ) : (
                                <>
                                  <CopyIcon className="size-3" />
                                  复制
                                </>
                              )}
                            </Button>
                          </div>
                        )}
                        {approved && (
                          <p className="text-[11.5px] text-muted">
                            用法：聊天里发「/点歌 歌名 音色名」。
                          </p>
                        )}
                        {item.reason && (
                          <p className="text-[12px] text-danger">原因：{item.reason}</p>
                        )}
                      </Card.Content>
                    )}

                    <Card.Footer className="flex-wrap justify-between gap-2">
                      <div>
                        {approved && (
                          <Button
                            isDisabled={busy}
                            onPress={() => void toggleVisibility(item)}
                            size="sm"
                            variant="secondary"
                          >
                            {isPublic ? '取消公开' : '公开到广场'}
                          </Button>
                        )}
                      </div>
                      <div className="flex items-center gap-2">
                        {approved && (
                          <Button
                            className="gap-1"
                            onPress={() =>
                              void copy(shareText(item.name ?? ''), `share-${item.id}`)
                            }
                            size="sm"
                            variant="tertiary"
                          >
                            {feedback?.key === `share-${item.id}` && feedback.ok ? (
                              <>
                                <CheckIcon className="size-3" />
                                已复制
                              </>
                            ) : (
                              '复制分享文案'
                            )}
                          </Button>
                        )}
                        <Button
                          isDisabled={busy}
                          onPress={() => void remove(item)}
                          size="sm"
                          variant="danger-soft"
                        >
                          删除
                        </Button>
                      </div>
                    </Card.Footer>
                  </Card>
                </li>
              );
            })}
          </ul>
        )}
      </main>

      <footer className="border-t border-border">
        <div className="mx-auto w-full max-w-[880px] px-4 py-6 text-[11.5px] leading-relaxed text-muted/80 sm:px-6">
          音色模型来自社区公开分享，版权归原作者所有；如有侵权请联系删除。本站以
          AGPL-3.0-or-later 发布。
        </div>
      </footer>
    </div>
  );
}

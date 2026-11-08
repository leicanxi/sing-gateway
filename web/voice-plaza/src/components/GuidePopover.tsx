import type { ReactNode } from 'react';
import { Button, Chip, Popover } from '@heroui/react';
import { useCopyFeedback } from '../hooks/useCopyFeedback';
import { CheckIcon, CopyIcon, ExternalIcon, GithubIcon } from './icons';

const STEPS: { title: string; text: ReactNode }[] = [
  {
    title: '挑一个音色',
    text: '按语言或声音快速筛选，点头像上的播放键可以先听一段。',
  },
  {
    title: '复制音色名',
    text: '点卡片上的「复制」，音色名就进了剪贴板。',
  },
  {
    title: '去聊天里点歌',
    text: (
      <>
        发{' '}
        <code className="rounded border border-border bg-surface-secondary px-1 py-px font-mono text-[11px] text-foreground">
          /点歌 歌名 音色名
        </code>
        ，或对机器人说「用 &lt;音色名&gt; 唱一首 &lt;歌名&gt;」。
      </>
    ),
  },
];

const PLUGINS = [
  {
    id: 'astrbot',
    name: 'AstrBot 插件',
    status: 'ready' as const,
    repo: 'https://github.com/leicanxi/astrbot_plugin_deepseek_sing',
    install: '在插件市场搜索 deepseek_sing，或把仓库放进 data/plugins/。',
  },
  {
    id: 'dsh',
    name: 'DSH 插件',
    status: 'ready' as const,
    repo: 'https://github.com/leicanxi/dsh-sing',
    install: '安装 dsh-sing，在 $DSH_HOME/sing.json 里填好网关地址即可。',
  },
];

const ENDPOINT = { base: 'https://flowbee.top/v1', model: 'sing-song' };

export function GuidePopover({ trigger }: { trigger: ReactNode }) {
  const { feedback, copy } = useCopyFeedback();

  return (
    <Popover>
      {trigger}
      <Popover.Content className="w-[340px]" placement="bottom end">
        <Popover.Dialog className="max-h-[70vh] space-y-4 overflow-y-auto">
          <ol className="space-y-2.5">
            {STEPS.map((step, index) => (
              <li className="flex gap-2.5" key={step.title}>
                <span className="step-num" aria-hidden="true">
                  {String(index + 1).padStart(2, '0')}
                </span>
                <div className="min-w-0">
                  <p className="text-[12.5px] font-semibold">{step.title}</p>
                  <p className="mt-0.5 text-[12px] leading-relaxed text-muted">
                    {step.text}
                  </p>
                </div>
              </li>
            ))}
          </ol>

          <div className="border-t border-border pt-3">
            <p className="text-[10.5px] font-semibold tracking-[0.12em] text-muted uppercase">
              接入插件
            </p>

            <div className="mt-2 space-y-2">
              {PLUGINS.map((plugin) => {
                const copied =
                  feedback !== null && feedback.key === plugin.id && feedback.ok;
                return (
                  <div
                    className="rounded-xl border border-border bg-surface-secondary/50 p-2.5"
                    key={plugin.id}
                  >
                    <div className="flex items-center gap-2">
                      <span className="grid size-5 shrink-0 place-items-center rounded-md bg-accent/10 text-[10px] font-semibold text-accent">
                        {plugin.name.charAt(0)}
                      </span>
                      <p className="text-[12px] font-semibold">{plugin.name}</p>
                      <Chip
                        className="ml-auto h-4.5 px-1.5 text-[10px]"
                        color={plugin.status === 'ready' ? 'accent' : 'default'}
                        size="sm"
                        variant="soft"
                      >
                        {plugin.status === 'ready' ? '可用' : '即将支持'}
                      </Chip>
                    </div>
                    <p className="mt-1 text-[11.5px] leading-relaxed text-muted">
                      {plugin.install}
                    </p>
                    {plugin.repo && (
                      <>
                        <code
                          className="mt-2 block min-w-0 truncate rounded border border-border bg-surface px-1.5 py-0.5 font-mono text-[10px] text-muted"
                          title={plugin.repo}
                        >
                          {plugin.repo.replace('https://', '')}
                        </code>
                        <div className="mt-1 flex items-center gap-1">
                          <a
                            className="card-link"
                            href={plugin.repo}
                            rel="noopener noreferrer"
                            target="_blank"
                          >
                            <GithubIcon className="size-3" />
                            GitHub
                            <ExternalIcon className="size-2.5" />
                          </a>
                          <Button
                            className="ml-auto gap-1 text-muted"
                            onPress={() => copy(plugin.repo, plugin.id)}
                            size="sm"
                            variant="ghost"
                          >
                            {copied ? (
                              <CheckIcon className="size-3 text-accent" />
                            ) : (
                              <CopyIcon className="size-3" />
                            )}
                            {copied ? '已复制' : '复制'}
                          </Button>
                        </div>
                      </>
                    )}
                  </div>
                );
              })}
            </div>

            <div className="mt-2 rounded-xl border border-border bg-surface-secondary/50 p-2.5">
              <div className="flex items-center gap-2">
                <span className="grid size-5 shrink-0 place-items-center rounded-md bg-accent/10 text-[10px] font-semibold text-accent">
                  API
                </span>
                <p className="text-[12px] font-semibold">OpenAI 兼容客户端</p>
              </div>
              <p className="mt-1 text-[11.5px] leading-relaxed text-muted">
                不用装插件，把模型配成 sing-song 就能点歌。
              </p>
              <div className="mt-2 space-y-1">
                {(
                  [
                    ['Base URL', ENDPOINT.base, 'base'],
                    ['模型', ENDPOINT.model, 'model'],
                  ] as const
                ).map(([label, value, key]) => {
                  const copied =
                    feedback !== null && feedback.key === key && feedback.ok;
                  return (
                    <div className="flex items-center gap-1" key={key}>
                      <span className="w-12 shrink-0 text-[10px] text-muted">
                        {label}
                      </span>
                      <code className="min-w-0 flex-1 truncate font-mono text-[10px] text-foreground">
                        {value}
                      </code>
                      <Button
                        aria-label={`复制 ${label}`}
                        isIconOnly
                        onPress={() => copy(value, key)}
                        size="sm"
                        variant="ghost"
                      >
                        {copied ? (
                          <CheckIcon className="size-3 text-accent" />
                        ) : (
                          <CopyIcon className="size-3 text-muted" />
                        )}
                      </Button>
                    </div>
                  );
                })}
              </div>
            </div>
          </div>
        </Popover.Dialog>
      </Popover.Content>
    </Popover>
  );
}


import type { ReactNode } from 'react';
import { Button } from '@heroui/react';
import { GuidePopover } from './GuidePopover';
import {
  BookIcon,
  GithubIcon,
  GridIcon,
  UploadIcon,
  UserIcon,
  UsersIcon,
} from './icons';
import type { SidebarPage, TabKey } from '../lib/types';

type SidebarProps = {
  active: SidebarPage;
  onSelect: (tab: TabKey) => void;
  onOpenUpload: () => void;
};

function NavItem({
  active = false,
  icon,
  children,
  onClick,
  href,
}: {
  active?: boolean;
  icon: ReactNode;
  children: ReactNode;
  onClick?: () => void;
  href?: string;
}) {
  const className = 'nav-item';
  const content = (
    <>
      <span className={active ? 'shrink-0 text-foreground' : 'shrink-0 text-muted'}>
        {icon}
      </span>
      <span className="truncate">{children}</span>
    </>
  );

  if (href) {
    return (
      <a className={className} data-active={active} href={href}>
        {content}
      </a>
    );
  }

  return (
    <button
      className={className}
      data-active={active}
      onClick={onClick}
      type="button"
    >
      {content}
    </button>
  );
}

export function Sidebar({ active, onSelect, onOpenUpload }: SidebarProps) {
  return (
    <aside className="fixed inset-y-0 left-0 z-40 hidden w-[220px] flex-col border-r border-border bg-background lg:flex">
      <div className="flex h-14 shrink-0 items-center border-b border-border px-4">
        <a className="flex items-center" href="./">
          <img
            alt="音色广场"
            className="h-8 w-auto"
            height="32"
            src="./logo-wordmark.png"
            width="79"
          />
        </a>
      </div>

      <nav className="flex min-h-0 flex-1 flex-col gap-5 overflow-y-auto px-2 pt-6 pb-4">
        <div>
          <p className="section-label">发现</p>
          <NavItem
            active={active === 'catalog'}
            icon={<GridIcon className="size-[18px]" />}
            onClick={() => onSelect('catalog')}
          >
            音色目录
          </NavItem>
          <NavItem
            active={active === 'community'}
            icon={<UsersIcon className="size-[18px]" />}
            onClick={() => onSelect('community')}
          >
            社区分享
          </NavItem>
        </div>

        <div>
          <p className="section-label">我的</p>
          <NavItem
            icon={<UploadIcon className="size-[18px]" />}
            onClick={onOpenUpload}
          >
            上传音色
          </NavItem>
          <NavItem
            active={active === 'account'}
            href="./account.html"
            icon={<UserIcon className="size-[18px]" />}
          >
            我的音色
          </NavItem>
        </div>

        <div>
          <p className="section-label">帮助</p>
          <GuidePopover
            trigger={
              <Button
                className="h-10 w-full justify-start gap-2.5 rounded-lg px-2 text-[13.5px] font-medium text-muted hover:bg-surface-secondary hover:text-foreground"
                variant="ghost"
              >
                <BookIcon className="size-[18px] shrink-0" />
                <span className="truncate">使用说明</span>
              </Button>
            }
          />
        </div>
      </nav>

      <div className="shrink-0 px-2 pb-3">
        <div className="rounded-xl border border-border bg-surface p-3">
          <div className="flex items-center gap-2">
            <span className="grid size-6 shrink-0 place-items-center rounded-md bg-accent/12 text-[11px] font-semibold text-accent">
              A
            </span>
            <p className="text-[12px] font-semibold">接入聊天插件</p>
          </div>
          <p className="mt-1.5 text-[11px] leading-relaxed text-muted">
            AstrBot、DSH 或任意 OpenAI 兼容客户端都能点歌。
          </p>
          <GuidePopover
            trigger={
              <Button
                className="mt-2.5 h-8 w-full rounded-full border border-border bg-surface text-[11.5px] font-medium text-foreground/80 hover:bg-surface-secondary hover:text-foreground"
                variant="ghost"
              >
                查看使用说明
              </Button>
            }
          />
        </div>

        <a
          className="mt-2 flex h-9 items-center gap-2 rounded-lg px-2 text-[12px] text-muted transition-colors hover:bg-surface-secondary hover:text-foreground"
          href="https://github.com/leicanxi/sing-gateway"
          rel="noopener noreferrer"
          target="_blank"
        >
          <GithubIcon className="size-4" />
          源码 · sing-gateway
        </a>
      </div>
    </aside>
  );
}

import { Avatar, Button, Dropdown, Label } from '@heroui/react';
import { LogIn } from 'lucide-react';
import type { Account } from '../lib/types';
import { GuidePopover } from './GuidePopover';
import {
  FolderIcon,
  GithubIcon,
  HelpIcon,
  UploadIcon,
  UserIcon,
} from './icons';

type TopbarProps = {
  account: Account | null;
  onOpenUpload: () => void;
  label?: string;
};

type MenuAction = 'account' | 'upload' | 'login';

export function Topbar({ account, onOpenUpload, label = '音色广场' }: TopbarProps) {
  const displayName = account?.name || account?.username || '';
  const initial = displayName.trim().charAt(0).toUpperCase();

  const onMenuAction = (key: MenuAction) => {
    if (key === 'upload') onOpenUpload();
    else if (key === 'account') window.location.href = './account.html';
    else if (key === 'login') {
      window.location.href = '/v1/auth/login?next=/upload.html';
    }
  };

  return (
    <header className="sticky top-0 z-30 border-b border-border bg-background/85 backdrop-blur-xl">
      <div className="flex h-14 items-center gap-3 px-4 sm:px-6 lg:px-8">
        <a className="flex items-center lg:hidden" href="./">
          <img
            alt="音色广场"
            className="h-7 w-auto"
            height="28"
            src="./logo-wordmark.png"
            width="69"
          />
        </a>

        <nav
          aria-label="面包屑"
          className="hidden items-center gap-1.5 text-[13px] lg:flex"
        >
          <FolderIcon className="size-4 text-muted" />
          <a className="text-muted transition-colors hover:text-foreground" href="./">
            应用
          </a>
          <span aria-hidden="true" className="text-muted/40">
            /
          </span>
          <span className="font-medium text-foreground">{label}</span>
        </nav>

        <div className="ml-auto flex items-center gap-1">
          <a
            aria-label="GitHub 源码"
            className="hidden size-9 place-items-center rounded-full text-muted transition-colors hover:bg-surface-secondary hover:text-foreground sm:grid"
            href="https://github.com/leicanxi/sing-gateway"
            rel="noopener noreferrer"
            target="_blank"
          >
            <GithubIcon className="size-4" />
          </a>

          <GuidePopover
            trigger={
              <Button
                aria-label="使用说明"
                className="h-9 gap-1.5 rounded-full px-2.5 text-[13px] text-muted hover:bg-surface-secondary hover:text-foreground"
                variant="ghost"
              >
                <HelpIcon className="size-4" />
                <span className="hidden lg:inline">使用说明</span>
              </Button>
            }
          />

          <Dropdown>
            <Button
              aria-label="账号菜单"
              className="ml-1 h-9 min-w-0 rounded-full border border-border bg-surface p-0.5"
              variant="ghost"
            >
              <Avatar className="size-8">
                {initial ? (
                  <Avatar.Fallback className="bg-accent text-[13px] font-semibold text-accent-foreground">
                    {initial}
                  </Avatar.Fallback>
                ) : (
                  <Avatar.Fallback className="bg-surface-secondary text-muted">
                    <UserIcon className="size-4" />
                  </Avatar.Fallback>
                )}
              </Avatar>
            </Button>
            <Dropdown.Popover>
              <Dropdown.Menu onAction={(key) => onMenuAction(key as MenuAction)}>
                {account ? (
                  <Dropdown.Item id="account" textValue="我的音色">
                    <UserIcon className="size-4 text-muted" />
                    <Label>我的音色</Label>
                  </Dropdown.Item>
                ) : (
                  <Dropdown.Item id="login" textValue="登录 FlowBee">
                    <LogIn className="size-4 text-muted" strokeWidth={1.75} />
                    <Label>登录 FlowBee</Label>
                  </Dropdown.Item>
                )}
                <Dropdown.Item id="upload" textValue="上传音色">
                  <UploadIcon className="size-4 text-muted" />
                  <Label>上传音色</Label>
                </Dropdown.Item>
              </Dropdown.Menu>
            </Dropdown.Popover>
          </Dropdown>
        </div>
      </div>
    </header>
  );
}

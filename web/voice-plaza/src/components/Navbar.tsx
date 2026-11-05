import { Avatar, Button, Dropdown, Label } from '@heroui/react';
import type { Account } from '../lib/types';
import { GuidePopover } from './GuidePopover';
import { HelpIcon, LogInIcon, UploadIcon, UserIcon } from './icons';

export type TabKey = 'catalog' | 'community';

type NavbarProps = {
  account: Account | null;
  onOpenUpload: () => void;
};

type MenuAction = 'account' | 'upload' | 'login';

export function Navbar({ account, onOpenUpload }: NavbarProps) {
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
    <header className="sticky top-0 z-40 border-b border-border bg-background/70 backdrop-blur-xl">
      <div className="mx-auto flex w-full max-w-[1120px] items-center gap-2 px-4 py-2.5 sm:px-6">
        <div className="flex min-w-0 flex-1 items-center">
          <a className="flex shrink-0 items-center" href="./">
            <img
              alt=""
              className="h-9 w-auto"
              height="36"
              src="./logo-wordmark.png"
              width="89"
            />
            <h1 className="sr-only">音色广场</h1>
          </a>
        </div>

        <div className="flex flex-1 items-center justify-end gap-1.5">
          <GuidePopover
            trigger={
              <Button
                aria-label="使用说明"
                className="h-9 gap-1.5 rounded-full bg-default px-2.5 text-[12.5px] text-foreground/80 hover:bg-default/70 hover:text-foreground md:px-3"
                variant="ghost"
              >
                <HelpIcon className="size-3.5" />
                <span className="hidden md:inline">使用说明</span>
              </Button>
            }
          />

          <Button
            aria-label="上传音色"
            className="h-9 gap-1.5 rounded-full px-3 text-[12.5px]"
            onPress={onOpenUpload}
          >
            <UploadIcon className="size-3.5" />
            <span className="hidden sm:inline">上传音色</span>
          </Button>

          <Dropdown>
            <Button
              aria-label="账号菜单"
              className="h-9 min-w-0 rounded-full border border-border bg-surface p-0.5"
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
                    <UserIcon className="size-3.5 text-muted" />
                    <Label>我的音色</Label>
                  </Dropdown.Item>
                ) : (
                  <Dropdown.Item id="login" textValue="登录 FlowBee">
                    <LogInIcon className="size-3.5 text-muted" />
                    <Label>登录 FlowBee</Label>
                  </Dropdown.Item>
                )}
                <Dropdown.Item id="upload" textValue="上传音色">
                  <UploadIcon className="size-3.5 text-muted" />
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

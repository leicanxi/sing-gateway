import type { ReactNode } from 'react';
import { PlusIcon, GridIcon, UserIcon, UsersIcon } from './icons';
import type { SidebarPage, TabKey } from '../lib/types';

type MobileNavProps = {
  active: SidebarPage;
  onSelect: (tab: TabKey) => void;
  onOpenUpload: () => void;
};

function NavButton({
  active = false,
  icon,
  label,
  onClick,
  href,
  raised = false,
}: {
  active?: boolean;
  icon: ReactNode;
  label: string;
  onClick?: () => void;
  href?: string;
  raised?: boolean;
}) {
  const body = (
    <>
      <span
        className={
          raised
            ? 'grid size-9 place-items-center rounded-full bg-foreground text-background shadow-sm'
            : active
              ? 'text-foreground'
              : 'text-muted'
        }
      >
        {icon}
      </span>
      <span
        className={
          active ? 'text-[10.5px] font-medium text-foreground' : 'text-[10.5px] text-muted'
        }
      >
        {label}
      </span>
    </>
  );

  const className =
    'flex flex-col items-center justify-center gap-1 outline-none transition-colors focus-visible:bg-surface-secondary';

  if (href) {
    return (
      <a
        aria-current={active ? 'page' : undefined}
        className={className}
        href={href}
      >
        {body}
      </a>
    );
  }

  return (
    <button
      aria-current={active ? 'page' : undefined}
      className={className}
      onClick={onClick}
      type="button"
    >
      {body}
    </button>
  );
}

export function MobileNav({ active, onSelect, onOpenUpload }: MobileNavProps) {
  return (
    <nav
      aria-label="主导航"
      className="fixed inset-x-0 bottom-0 z-40 border-t border-border bg-background/92 backdrop-blur-xl lg:hidden"
      style={{ paddingBottom: 'env(safe-area-inset-bottom)' }}
    >
      <div className="mx-auto grid h-16 max-w-lg grid-cols-4">
        <NavButton
          active={active === 'catalog'}
          icon={<GridIcon className="size-5" />}
          label="音色库"
          onClick={() => onSelect('catalog')}
        />
        <NavButton
          active={active === 'community'}
          icon={<UsersIcon className="size-5" />}
          label="社区"
          onClick={() => onSelect('community')}
        />
        <NavButton
          icon={<PlusIcon className="size-5" />}
          label="上传"
          onClick={onOpenUpload}
          raised
        />
        <NavButton
          active={active === 'account'}
          href="./account.html"
          icon={<UserIcon className="size-5" />}
          label="我的"
        />
      </div>
    </nav>
  );
}

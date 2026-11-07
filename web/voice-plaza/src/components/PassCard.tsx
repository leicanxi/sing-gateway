import { useState } from 'react';
import { ChevronRightIcon, XIcon } from './icons';

const STORAGE_KEY = 'flowbee-pass-dismissed';

/**
 * Bottom-right campaign card. Dismissal is session-scoped so it comes back on
 * the next visit without nagging again during the same browsing session.
 */
export function PassCard() {
  const [visible, setVisible] = useState(() => {
    try {
      return window.sessionStorage.getItem(STORAGE_KEY) !== '1';
    } catch {
      return true;
    }
  });

  if (!visible) return null;

  const dismiss = () => {
    setVisible(false);
    try {
      window.sessionStorage.setItem(STORAGE_KEY, '1');
    } catch {
      // ignore storage failures (private mode)
    }
  };

  return (
    <aside
      aria-label="FlowBee 善意通行证"
      className="pass-card fixed right-3 bottom-20 z-40 w-[330px] max-w-[calc(100%-1.5rem)] lg:right-6 lg:bottom-6 lg:w-[340px] lg:max-w-none"
    >
      <div className="relative overflow-hidden rounded-2xl border border-border bg-surface shadow-overlay">
        <a
          aria-label="了解 FlowBee 善意通行证"
          className="group block outline-none focus-visible:ring-2 focus-visible:ring-accent/40 focus-visible:ring-inset"
          href="https://flowbee.top"
          rel="noopener noreferrer"
          target="_blank"
        >
          <div className="relative h-[76px] overflow-hidden lg:h-[108px]">
            <img
              alt=""
              className="size-full object-cover object-[50%_28%]"
              height="108"
              src="./marketing/pass.png"
              width="340"
            />
            <span
              aria-hidden="true"
              className="absolute inset-0 bg-gradient-to-t from-[#3c2a12]/35 via-transparent to-transparent"
            />
          </div>

          <div className="p-3 lg:p-4">
            <p className="text-[14px] font-semibold tracking-[-0.01em] lg:text-[15px]">
              FlowBee 善意通行证
            </p>
            <p className="mt-1.5 text-[11px] leading-relaxed text-muted lg:text-[11.5px]">
              不限时间、不限公益组织、不限金额。
            </p>
            <p className="mt-1 text-[11px] leading-relaxed text-muted lg:text-[11.5px]">
              完成任意一笔公益捐赠，即可获得官方满血原生国模原价
              <span className="mx-0.5 font-semibold text-foreground">30%</span>
              的使用资格。
            </p>
            <span className="mt-2 inline-flex items-center gap-0.5 text-[11px] font-semibold text-[#9a6412]">
              了解详情
              <ChevronRightIcon className="size-3 transition-transform group-hover:translate-x-0.5" />
            </span>
          </div>
        </a>

        <button
          aria-label="关闭善意通行证卡片"
          className="absolute top-2 right-2 z-10 grid size-7 place-items-center rounded-full bg-black/35 text-white backdrop-blur transition-colors hover:bg-black/55 lg:top-2.5 lg:right-2.5"
          onClick={dismiss}
          type="button"
        >
          <XIcon className="size-3.5" />
        </button>
      </div>
    </aside>
  );
}

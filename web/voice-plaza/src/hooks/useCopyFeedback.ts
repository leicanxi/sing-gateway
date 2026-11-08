import { useCallback, useEffect, useRef, useState } from 'react';
import { copyText } from '../lib/clipboard';

type Feedback = { key: string; ok: boolean } | null;

/**
 * Copies text and remembers which control asked for it, so a card can show
 * "已复制" without every card re-rendering its own timer.
 */
export function useCopyFeedback(resetMs = 1800) {
  const [feedback, setFeedback] = useState<Feedback>(null);
  const timer = useRef<number | undefined>(undefined);

  useEffect(() => () => window.clearTimeout(timer.current), []);

  const copy = useCallback(
    async (text: string, key = text) => {
      const ok = await copyText(text);
      setFeedback({ key, ok });
      window.clearTimeout(timer.current);
      timer.current = window.setTimeout(() => {
        setFeedback((current) => (current?.key === key ? null : current));
      }, resetMs);
      return ok;
    },
    [resetMs],
  );

  return { feedback, copy };
}

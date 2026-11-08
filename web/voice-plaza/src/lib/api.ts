import type { CatalogPage, Voice } from './types';

const PAGE_SIZE = 60;

export type CatalogRequest = {
  q: string;
  sort: string;
  lang: string;
  gender: string;
  offset: number;
};

function toVoice(raw: unknown): Voice | null {
  if (!raw || typeof raw !== 'object') return null;
  const item = raw as Record<string, unknown>;
  if (typeof item.name !== 'string' || !item.name) return null;
  return item as unknown as Voice;
}

export async function fetchCatalog(
  request: CatalogRequest,
  signal?: AbortSignal,
): Promise<CatalogPage> {
  const params = new URLSearchParams({
    sort: request.sort,
    limit: String(PAGE_SIZE),
    offset: String(request.offset),
  });
  if (request.q) params.set('q', request.q);
  if (request.lang) params.set('lang', request.lang);
  if (request.gender) params.set('gender', request.gender);

  const response = await fetch(`/v1/voices/catalog?${params.toString()}`, {
    cache: 'no-store',
    signal,
  });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);

  const payload = (await response.json()) as Record<string, unknown>;
  const items = Array.isArray(payload.items)
    ? payload.items.map(toVoice).filter((item): item is Voice => item !== null)
    : [];
  const rawNext = payload.next_offset;
  return {
    items,
    total: Number(payload.total) || 0,
    nextOffset:
      rawNext === null || rawNext === undefined ? null : Number(rawNext),
  };
}

export async function fetchCommunity(
  sort: string,
  signal: AbortSignal,
): Promise<Voice[]> {
  const response = await fetch(
    `/v1/voices/public?limit=100&sort=${encodeURIComponent(sort)}`,
    { cache: 'no-store', signal },
  );
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  const payload = (await response.json()) as Record<string, unknown>;
  return Array.isArray(payload.voices)
    ? payload.voices.map(toVoice).filter((item): item is Voice => item !== null)
    : [];
}

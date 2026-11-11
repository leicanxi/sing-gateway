export type Voice = {
  name: string;
  label: string;
  url?: string | null;
  preview_url?: string | null;
  favorites?: number;
  uses?: number;
  language?: string | null;
  gender?: string | null;
  type?: string | null;
  rvc_version?: string | number | null;
  engine?: string | null;
  tags?: string[] | null;
  description?: string | null;
  author?: string | null;
};

export type CatalogPage = {
  items: Voice[];
  total: number;
  nextOffset: number | null;
};

export type SortKey = 'hot' | 'favorites' | 'new' | 'label';
export type CommunitySortKey = 'new' | 'hot';

export type Account = { name?: string; username?: string };

export type TabKey = 'catalog' | 'community';

export type SidebarPage = TabKey | 'account';

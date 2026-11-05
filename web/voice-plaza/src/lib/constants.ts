import type { Voice } from './types';

export const LANGUAGE_LABEL: Record<string, string> = {
  zh: '中文',
  ja: '日语',
  en: '英语',
  ko: '韩语',
  es: '西班牙语',
  fr: '法语',
  de: '德语',
  ru: '俄语',
  pt: '葡萄牙语',
  it: '意大利语',
  other: '其他',
};

export const GENDER_LABEL: Record<string, string> = {
  female: '女声',
  male: '男声',
  neutral: '中性',
};

export type Option = { value: string; label: string };

export const SORT_OPTIONS: Option[] = [
  { value: 'hot', label: '热度优先' },
  { value: 'favorites', label: '收藏优先' },
  { value: 'new', label: '最新收录' },
  { value: 'label', label: '名称排序' },
];

export const LANGUAGE_OPTIONS: Option[] = [
  { value: 'all', label: '全部语言' },
  { value: 'zh', label: '中文' },
  { value: 'ja', label: '日语' },
  { value: 'en', label: '英语' },
  { value: 'ko', label: '韩语' },
  { value: 'other', label: '其他' },
];

export const GENDER_OPTIONS: Option[] = [
  { value: 'all', label: '全部声音' },
  { value: 'female', label: '女声' },
  { value: 'male', label: '男声' },
  { value: 'neutral', label: '中性' },
];

export const COMMUNITY_SORT_OPTIONS: Option[] = [
  { value: 'new', label: '最新公开' },
  { value: 'hot', label: '使用最多' },
];

export const SORT_VALUES = SORT_OPTIONS.map((option) => option.value);
export const LANGUAGE_VALUES = LANGUAGE_OPTIONS.map((option) => option.value).filter(
  (value) => value !== 'all',
);
export const GENDER_VALUES = GENDER_OPTIONS.map((option) => option.value).filter(
  (value) => value !== 'all',
);

export type VoiceChip = { label: string; accent?: boolean };

/** Chips are ordered so the categorical metadata comes first, then tags. */
export function voiceChips(voice: Voice, limit = 4): VoiceChip[] {
  const chips: VoiceChip[] = [];
  const seen = new Set<string>();
  const push = (label: string, accent = false) => {
    const value = label.trim();
    if (!value || seen.has(value)) return;
    seen.add(value);
    chips.push({ label: value, accent });
  };

  if (voice.language) {
    push(LANGUAGE_LABEL[voice.language] ?? '', true);
  }
  if (voice.gender) push(GENDER_LABEL[voice.gender] ?? '');
  if (voice.type === 'instrumental') push('乐器');
  if (voice.rvc_version) push(String(voice.rvc_version).toUpperCase());
  for (const raw of voice.tags ?? []) push(String(raw ?? ''));

  return chips.slice(0, limit);
}

export function formatCount(value: number): string {
  return new Intl.NumberFormat('zh-CN').format(value);
}

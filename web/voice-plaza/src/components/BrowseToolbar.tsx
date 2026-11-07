import { Button, ListBox, Popover, Select } from '@heroui/react';
import type { ReactNode, RefObject } from 'react';
import type { Option } from '../lib/constants';
import { cn } from '../lib/utils';
import type { TabKey } from '../lib/types';
import {
  GlobeIcon,
  MicIcon,
  SearchIcon,
  SlidersIcon,
  SortIcon,
  XIcon,
} from './icons';

type FilterSelectProps = {
  label: string;
  icon: ReactNode;
  value: string;
  options: Option[];
  onChange: (value: string) => void;
  className?: string;
};

function FilterSelect({
  label,
  icon,
  value,
  options,
  onChange,
  className,
}: FilterSelectProps) {
  return (
    <Select
      aria-label={label}
      className={className}
      onChange={(next) => onChange(String(next ?? ''))}
      value={value}
    >
      <Select.Trigger className="chip-select flex h-11 items-center justify-start gap-1.5 rounded-full border border-border bg-background py-0 pr-8 pl-4 text-[13px] font-medium text-foreground/80 shadow-none transition-colors hover:bg-surface-secondary">
        <span className="text-muted">{icon}</span>
        <Select.Value />
        <Select.Indicator className="text-muted" />
      </Select.Trigger>
      <Select.Popover>
        <ListBox>
          {options.map((option) => (
            <ListBox.Item id={option.value} key={option.value} textValue={option.label}>
              {option.label}
              <ListBox.ItemIndicator />
            </ListBox.Item>
          ))}
        </ListBox>
      </Select.Popover>
    </Select>
  );
}

type BrowseToolbarProps = {
  tab: TabKey;
  onTabChange: (tab: TabKey) => void;
  search: string;
  onSearchChange: (value: string) => void;
  searchInputRef: RefObject<HTMLInputElement | null>;
  sort: string;
  onSortChange: (value: string) => void;
  language: string;
  onLanguageChange: (value: string) => void;
  gender: string;
  onGenderChange: (value: string) => void;
  communitySort: string;
  onCommunitySortChange: (value: string) => void;
  sortOptions: Option[];
  languageOptions: Option[];
  genderOptions: Option[];
  communitySortOptions: Option[];
};

export function BrowseToolbar(props: BrowseToolbarProps) {
  const isCatalog = props.tab === 'catalog';
  const activeFilters = (props.language ? 1 : 0) + (props.gender ? 1 : 0);

  return (
    <div className="space-y-4">
      <div className="flex gap-6 border-b border-border">
        <button
          aria-current={isCatalog ? 'page' : undefined}
          className={cn(
            '-mb-px h-10 border-b-2 px-1 text-[13.5px] font-medium transition-colors',
            isCatalog
              ? 'border-foreground text-foreground'
              : 'border-transparent text-muted hover:text-foreground',
          )}
          onClick={() => props.onTabChange('catalog')}
          type="button"
        >
          探索
        </button>
        <button
          aria-current={!isCatalog ? 'page' : undefined}
          className={cn(
            '-mb-px h-10 border-b-2 px-1 text-[13.5px] font-medium transition-colors',
            !isCatalog
              ? 'border-foreground text-foreground'
              : 'border-transparent text-muted hover:text-foreground',
          )}
          onClick={() => props.onTabChange('community')}
          type="button"
        >
          社区分享
        </button>
      </div>

      <div className="flex flex-col gap-3 lg:flex-row lg:items-center">
        <div className="relative min-w-0 flex-1">
          <SearchIcon className="pointer-events-none absolute top-1/2 left-4 size-[18px] -translate-y-1/2 text-muted" />
          <input
            aria-label="搜索音色"
            autoComplete="off"
            className="h-11 w-full rounded-full border border-border bg-background pr-10 pl-11 text-[13.5px] text-foreground shadow-none outline-none transition-colors placeholder:text-muted focus:border-foreground/30"
            inputMode="search"
            onChange={(event) => props.onSearchChange(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter') event.currentTarget.blur();
              if (event.key === 'Escape') {
                props.onSearchChange('');
                event.currentTarget.blur();
              }
            }}
            placeholder="搜索音色、角色或标签"
            ref={props.searchInputRef}
            spellCheck={false}
            type="text"
            value={props.search}
          />
          {props.search && (
            <button
              aria-label="清空搜索"
              className="absolute top-1/2 right-2.5 grid size-7 -translate-y-1/2 place-items-center rounded-full text-muted transition-colors hover:bg-surface-secondary hover:text-foreground"
              onClick={() => props.onSearchChange('')}
              type="button"
            >
              <XIcon className="size-3.5" />
            </button>
          )}
        </div>

        <div className="flex items-center gap-2">
          <FilterSelect
            className="flex-1 sm:flex-none"
            icon={<SortIcon className="size-4" />}
            label="排序方式"
            onChange={isCatalog ? props.onSortChange : props.onCommunitySortChange}
            options={isCatalog ? props.sortOptions : props.communitySortOptions}
            value={isCatalog ? props.sort : props.communitySort}
          />

          {isCatalog && (
            <Popover>
              <Button
                className="h-11 gap-1.5 rounded-full border border-border bg-background px-4 text-[13px] font-medium text-foreground/80 shadow-none hover:bg-surface-secondary hover:text-foreground"
                variant="ghost"
              >
                <SlidersIcon className="size-4" />
                筛选
                {activeFilters > 0 && (
                  <span className="grid size-[18px] place-items-center rounded-full bg-foreground text-[10px] font-semibold text-background">
                    {activeFilters}
                  </span>
                )}
              </Button>
              <Popover.Content className="w-[280px]" placement="bottom end">
                <Popover.Dialog className="space-y-4">
                  <div className="space-y-1.5">
                    <span className="text-[11.5px] text-muted">语言</span>
                    <FilterSelect
                      className="w-full"
                      icon={<GlobeIcon className="size-3.5" />}
                      label="语言筛选"
                      onChange={(value) =>
                        props.onLanguageChange(value === 'all' ? '' : value)
                      }
                      options={props.languageOptions}
                      value={props.language || 'all'}
                    />
                  </div>
                  <div className="space-y-1.5">
                    <span className="text-[11.5px] text-muted">声音</span>
                    <FilterSelect
                      className="w-full"
                      icon={<MicIcon className="size-3.5" />}
                      label="声音类型筛选"
                      onChange={(value) =>
                        props.onGenderChange(value === 'all' ? '' : value)
                      }
                      options={props.genderOptions}
                      value={props.gender || 'all'}
                    />
                  </div>
                  {(props.language || props.gender) && (
                    <Button
                      className="w-full"
                      onPress={() => {
                        props.onLanguageChange('');
                        props.onGenderChange('');
                      }}
                      size="sm"
                      variant="tertiary"
                    >
                      清除筛选
                    </Button>
                  )}
                </Popover.Dialog>
              </Popover.Content>
            </Popover>
          )}
        </div>
      </div>
    </div>
  );
}

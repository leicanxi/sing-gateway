import { Button, ListBox, Popover, Select, Tabs } from '@heroui/react';
import type { Option } from '../lib/constants';
import { GlobeIcon, MicIcon, SlidersIcon, SortIcon } from './icons';
import type { TabKey } from './Navbar';

type FilterSelectProps = {
  label: string;
  icon: React.ReactNode;
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
      <Select.Trigger className="chip-select h-9 items-center justify-start gap-1.5 rounded-full border border-border bg-surface py-0 pr-7 pl-3 text-[12.5px] text-foreground/80">
        <span className="text-muted">{icon}</span>
        <Select.Value />
        <Select.Indicator className="text-muted" />
      </Select.Trigger>
      <Select.Popover>
        <ListBox>
          {options.map((option) => (
            <ListBox.Item
              id={option.value}
              key={option.value}
              textValue={option.label}
            >
              {option.label}
              <ListBox.ItemIndicator />
            </ListBox.Item>
          ))}
        </ListBox>
      </Select.Popover>
    </Select>
  );
}

type TabsBarProps = {
  tab: TabKey;
  onTabChange: (tab: TabKey) => void;
  countLabel: string;
  hasFilters: boolean;
  onClearFilters: () => void;
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

export function TabsBar(props: TabsBarProps) {
  const activeFilters = (props.language ? 1 : 0) + (props.gender ? 1 : 0);
  const isCatalog = props.tab === 'catalog';

  return (
    <div className="flex flex-wrap items-center gap-2">
      <Tabs
        className="w-fit"
        onSelectionChange={(key) => props.onTabChange(key as TabKey)}
        selectedKey={props.tab}
      >
        <Tabs.ListContainer className="w-fit">
          <Tabs.List aria-label="音色来源">
            <Tabs.Tab id="catalog">
              音色目录
              <Tabs.Indicator />
            </Tabs.Tab>
            <Tabs.Tab id="community">
              社区分享
              <Tabs.Indicator />
            </Tabs.Tab>
          </Tabs.List>
        </Tabs.ListContainer>
      </Tabs>

      <span className="ml-1 hidden text-[12.5px] text-muted tabular-nums sm:block">
        {props.countLabel}
      </span>

      <div className="ml-auto flex items-center gap-2">
        <FilterSelect
          icon={<SortIcon className="size-3.5" />}
          label="排序方式"
          onChange={isCatalog ? props.onSortChange : props.onCommunitySortChange}
          options={isCatalog ? props.sortOptions : props.communitySortOptions}
          value={isCatalog ? props.sort : props.communitySort}
        />

        {isCatalog && (
          <Popover>
            <Button
              className="h-9 gap-1.5 rounded-full border border-border bg-surface px-3 text-[12.5px] text-foreground/80 hover:text-foreground"
              variant="ghost"
            >
              <SlidersIcon className="size-3.5" />
              筛选
              {activeFilters > 0 && (
                <span className="grid size-4 place-items-center rounded-full bg-accent text-[10px] font-medium text-accent-foreground">
                  {activeFilters}
                </span>
              )}
            </Button>
            <Popover.Content className="w-[260px]">
              <Popover.Dialog className="space-y-3">
                <div className="space-y-1.5">
                  <span className="text-[11.5px] text-muted">语言</span>
                  <FilterSelect
                    className="w-full"
                    icon={<GlobeIcon className="size-3.5" />}
                    label="语言筛选"
                    onChange={props.onLanguageChange}
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
                    onChange={props.onGenderChange}
                    options={props.genderOptions}
                    value={props.gender || 'all'}
                  />
                </div>
                {props.hasFilters && (
                  <Button
                    className="w-full"
                    onPress={props.onClearFilters}
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
  );
}

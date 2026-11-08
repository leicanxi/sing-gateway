import type { SVGProps } from 'react';

type IconProps = SVGProps<SVGSVGElement>;

function Icon({ children, ...props }: IconProps) {
  return (
    <svg
      aria-hidden="true"
      fill="none"
      focusable="false"
      height="16"
      stroke="currentColor"
      strokeLinecap="round"
      strokeLinejoin="round"
      strokeWidth="1.4"
      viewBox="0 0 16 16"
      width="16"
      {...props}
    >
      {children}
    </svg>
  );
}

export function PlayIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M5.6 3.4v9.2L12.4 8z" />
    </Icon>
  );
}

export function PauseIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M6.2 3.8v8.4M9.8 3.8v8.4" strokeWidth="1.8" />
    </Icon>
  );
}

export function DownloadIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M8 2.2v7.1m0 0 2.7-2.7M8 9.3 5.3 6.6M3 11.4v1.3c0 .72.58 1.3 1.3 1.3h7.4c.72 0 1.3-.58 1.3-1.3v-1.3" />
    </Icon>
  );
}

export function StarIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M8 1.9l1.77 3.83 4.13.49-3.05 2.86.82 4.11L8 11.11l-3.67 2.08.82-4.11L2.1 6.22l4.13-.49z" />
    </Icon>
  );
}

export function HelpIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <circle cx="8" cy="8" r="5.6" />
      <path d="M6.4 6.2c.15-.85.83-1.45 1.66-1.45.92 0 1.64.63 1.64 1.42 0 1.18-1.62 1.4-1.62 2.55" />
      <path d="M8 11.2h.01" strokeWidth="1.8" />
    </Icon>
  );
}

export function CopyIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <rect height="8.2" rx="1.2" width="7.2" x="5.6" y="5.6" />
      <path d="M10.4 5.6V4.3c0-.66-.54-1.2-1.2-1.2H4.3c-.66 0-1.2.54-1.2 1.2v4.9c0 .66.54 1.2 1.2 1.2h1.3" />
    </Icon>
  );
}

export function CheckIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="m3.4 8.4 3 3 6.2-6.6" />
    </Icon>
  );
}

export function SlidersIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M3 4.6h10M3 8h10M3 11.4h10" />
      <circle cx="6.2" cy="4.6" fill="currentColor" r="1.45" stroke="none" />
      <circle cx="9.8" cy="8" fill="currentColor" r="1.45" stroke="none" />
      <circle cx="5.6" cy="11.4" fill="currentColor" r="1.45" stroke="none" />
    </Icon>
  );
}

export function ArrowUpIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M8 12.8V3.4m0 0L4.4 7M8 3.4 11.6 7" />
    </Icon>
  );
}

export function ExternalIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M9.6 3.2h3.2v3.2M12.8 3.2 7.7 8.3" />
      <path d="M11.2 9.9v2.2c0 .6-.5 1.1-1.1 1.1H4.5c-.6 0-1.1-.5-1.1-1.1V6.5c0-.6.5-1.1 1.1-1.1h2.2" />
    </Icon>
  );
}

export function SortIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M4.9 3.6v8.8m0 0L2.6 10.1M4.9 12.4l2.3-2.3" />
      <path d="M11.1 12.4V3.6m0 0L8.8 5.9M11.1 3.6l2.3 2.3" />
    </Icon>
  );
}

export function GlobeIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <circle cx="8" cy="8" r="5.6" />
      <path d="M2.6 8h10.8M8 2.4c1.5 1.6 2.2 3.5 2.2 5.6S9.5 12 8 13.6C6.5 12 5.8 10.1 5.8 8S6.5 4 8 2.4z" />
    </Icon>
  );
}

export function MicIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <rect height="7.2" rx="2.2" width="4.4" x="5.8" y="2.2" />
      <path d="M3.6 7.6a4.4 4.4 0 0 0 8.8 0M8 12v2.2" />
    </Icon>
  );
}

export function XIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="m4.2 4.2 7.6 7.6M11.8 4.2l-7.6 7.6" />
    </Icon>
  );
}

export function ChevronDownIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="m4.5 6.5 3.5 3.5 3.5-3.5" />
    </Icon>
  );
}

export function ChevronLeftIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="m9.5 4.5-3.5 3.5 3.5 3.5" />
    </Icon>
  );
}

export function ChevronRightIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="m6.5 4.5 3.5 3.5-3.5 3.5" />
    </Icon>
  );
}

export function GridIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <rect height="4.6" rx="1.1" width="4.6" x="2.6" y="2.6" />
      <rect height="4.6" rx="1.1" width="4.6" x="8.8" y="2.6" />
      <rect height="4.6" rx="1.1" width="4.6" x="2.6" y="8.8" />
      <rect height="4.6" rx="1.1" width="4.6" x="8.8" y="8.8" />
    </Icon>
  );
}

export function UsersIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <circle cx="6" cy="5.4" r="2.4" />
      <path d="M1.9 12.8c.55-2 2.2-3.1 4.1-3.1s3.55 1.1 4.1 3.1" />
      <path d="M10.4 3.4a2.3 2.3 0 0 1 0 4.4M12 9.9c1.2.45 2 1.45 2.4 2.9" />
    </Icon>
  );
}

export function FolderIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M2.4 4.6c0-.6.5-1.1 1.1-1.1h2.6l1.4 1.6h4.9c.6 0 1.1.5 1.1 1.1v5.6c0 .6-.5 1.1-1.1 1.1H3.5c-.6 0-1.1-.5-1.1-1.1z" />
    </Icon>
  );
}

export function BookIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M2.6 3.2h3.2c.8 0 1.5.4 2.2 1 .7-.6 1.4-1 2.2-1h3.2v9.6H10c-.8 0-1.5.4-2.2 1-.7-.6-1.4-1-2.2-1H2.6z" />
      <path d="M8 4.2v9.6" />
    </Icon>
  );
}

export function GithubIcon(props: IconProps) {
  return (
    <svg
      aria-hidden="true"
      fill="currentColor"
      focusable="false"
      height="16"
      viewBox="0 0 16 16"
      width="16"
      {...props}
    >
      <path d="M8 .8a7.2 7.2 0 0 0-2.28 14.03c.36.07.49-.16.49-.35v-1.24c-2 .43-2.43-.96-2.43-.96-.33-.83-.8-1.05-.8-1.05-.66-.45.05-.44.05-.44.72.05 1.1.74 1.1.74.64 1.1 1.68.78 2.09.6.06-.47.25-.79.45-.97-1.6-.18-3.28-.8-3.28-3.56 0-.79.28-1.43.74-1.93-.07-.18-.32-.91.07-1.9a2.6 2.6 0 0 1 .97-.05c.37.05.78.19 1.28.44a6.36 6.36 0 0 1 3.44 0c.5-.25.9-.39 1.27-.44.3-.04.7-.03.98.06.39.98.14 1.71.07 1.89.46.5.74 1.14.74 1.93 0 2.77-1.68 3.38-3.29 3.56.26.22.49.66.49 1.32v1.96c0 .2.13.42.5.35A7.2 7.2 0 0 0 8 .8z" />
    </svg>
  );
}

export function SparkIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M8 2.2 9.1 6l3.8 1.1L9.1 8.2 8 12l-1.1-3.8L3.1 7.1 6.9 6z" />
    </Icon>
  );
}

export function LogoMark(props: IconProps) {
  return (
    <Icon viewBox="0 0 16 16" {...props}>
      <path d="M6.2 4.2v7.6L11.6 8z" strokeWidth="1" />
      <path d="M12.2 11.1c.8-.8 1.2-1.9 1.2-3.1s-.45-2.3-1.2-3.1" opacity=".5" />
    </Icon>
  );
}

export function SearchIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <circle cx="7" cy="7" r="4.4" />
      <path d="m10.3 10.3 3.2 3.2" />
    </Icon>
  );
}

export function PlusIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M8 3.2v9.6M3.2 8h9.6" />
    </Icon>
  );
}

export function UserIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <circle cx="8" cy="5.6" r="2.8" />
      <path d="M2.8 13.2c.7-2.2 2.8-3.4 5.2-3.4s4.5 1.2 5.2 3.4" />
    </Icon>
  );
}

export function LogInIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M9.6 3.2h1.8c.6 0 1.1.5 1.1 1.1v7.4c0 .6-.5 1.1-1.1 1.1H9.6M6.2 8h6M6.2 8 3.4 5.2M6.2 8 3.4 10.8" />
    </Icon>
  );
}

export function UploadIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M8 10.8V3.6m0 0L5.3 6.3M8 3.6l2.7 2.7M3 11.6v.9c0 .72.58 1.3 1.3 1.3h7.4c.72 0 1.3-.58 1.3-1.3v-.9" />
    </Icon>
  );
}

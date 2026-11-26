const glyphs = {
  mark: (
    <>
      <path fill="currentColor" stroke="none" d="M2 9.4 8.4 3h6.3l-3.5 3.5H9.8L7 9.4l2.3 2.3L6.1 15 2 10.9V9.4Z" />
      <path fill="currentColor" stroke="none" opacity=".74" d="m18 10.6-6.4 6.4H5.3l3.5-3.5h1.4l2.8-2.9-2.3-2.3L13.9 5 18 9.1v1.5Z" />
    </>
  ),
  journal: (
    <>
      <path fill="currentColor" stroke="none" opacity=".18" d="M3 9h4l1.6 2h2.8L13 9h4v6.3L15.8 17H4.2L3 15.3V9Z" />
      <path d="M3 9V6l2-2h10l2 2v3m0 0v6.4L15.6 17H4.4L3 15.4V9h4l1.5 2h3L13 9h4M7 7h6" />
    </>
  ),
  review: (
    <>
      <path fill="currentColor" stroke="none" opacity=".17" d="M6 3h8l3.5 3.5v7L14 17H6l-3.5-3.5v-7L6 3Z" />
      <path d="M6 3h8l3.5 3.5v7L14 17H6l-3.5-3.5v-7L6 3Z" />
      <path d="M10 6.5v3.7" />
      <circle cx="10" cy="13.1" r="1" fill="currentColor" stroke="none" />
    </>
  ),
  waiting: (
    <>
      <path fill="currentColor" stroke="none" opacity=".19" d="M5.7 3.7h8.6v2.1L10 9.6 5.7 5.8V3.7Zm0 12.6v-2.1l4.3-3.8 4.3 3.8v2.1H5.7Z" />
      <path d="M4 3.5h12M4 16.5h12M5.6 3.5v2.4l4.4 4.1-4.4 4.1v2.4m8.8-13v2.4L10 10l4.4 4.1v2.4" />
    </>
  ),
  resolved: (
    <>
      <path fill="currentColor" stroke="none" opacity=".17" d="M5.5 3h9L17 5.5v9L14.5 17h-9L3 14.5v-9L5.5 3Z" />
      <path d="M5.5 3h9L17 5.5v9L14.5 17h-9L3 14.5v-9L5.5 3Z" />
      <path d="m6.5 10.1 2.3 2.3 4.8-4.8" />
    </>
  ),
  actions: (
    <>
      <path d="M4 5v9.5l2 2h2M9.5 5H17M9.5 10H15M11 15.5h6" />
      <rect x="2.5" y="3.5" width="3" height="3" rx=".5" fill="currentColor" stroke="none" />
      <rect x="2.5" y="8.5" width="3" height="3" rx=".5" fill="currentColor" stroke="none" />
      <rect x="7" y="14" width="3" height="3" rx=".5" fill="currentColor" stroke="none" />
    </>
  ),
  test: (
    <>
      <path fill="currentColor" stroke="none" opacity=".2" d="M7.8 11.1H13l-6.7 6.7a1.84 1.84 0 0 1-2.6-2.6l4.1-4.1Z" />
      <path d="m11.7 3.6 4.7 4.7M13.5 5.4l-9.8 9.8c-.7.7-.7 1.9 0 2.6.7.7 1.9.7 2.6 0l9.8-9.8M8 11.1h4.9" />
      <circle cx="16.6" cy="3.4" r="1.1" fill="currentColor" stroke="none" />
    </>
  ),
  products: (
    <>
      <path fill="currentColor" stroke="none" opacity=".18" d="M3.5 7h10l2 2v7.5h-12V7Z" />
      <path d="M6 4h9.5L17 5.5v8m-2.5 3h-11V7h9l2 2v7.5ZM6.2 11h5.5m-5.5 2.5h3.1" />
    </>
  ),
  sources: (
    <>
      <path fill="currentColor" stroke="none" opacity=".17" d="M5 3.5h7l3 3v10H5v-13Z" />
      <path d="M12 3.5H5v13h10v-10l-3-3Zm0 0v3h3" />
      <path fill="currentColor" stroke="none" d="M7.1 9.2h2.2v2.2l-.9 1.6H7.3l.7-1.6h-.9V9.2Zm3.6 0h2.2v2.2L12 13h-1.1l.7-1.6h-.9V9.2Z" />
    </>
  ),
  agent: (
    <>
      <path fill="currentColor" stroke="none" opacity=".2" d="M6.5 4.5h7l2 2v7l-2 2h-7l-2-2v-7l2-2Z" />
      <path d="M6.5 4.5h7l2 2v7l-2 2h-7l-2-2v-7l2-2Zm1-2v2m5-2v2m-5 11v2m5-2v2M2.5 7.5h2m-2 5h2m11-5h2m-2 5h2" />
      <path strokeWidth="1.5" d="M8 8.5h4M8 11.5h2.5" />
    </>
  ),
  client: (
    <>
      <path fill="currentColor" stroke="none" opacity=".18" d="M10 10a3.3 3.3 0 1 0 0-6.6 3.3 3.3 0 0 0 0 6.6Zm-6.7 6.5v-1L6 12.8h8l2.7 2.7v1H3.3Z" />
      <circle cx="10" cy="6.7" r="3" />
      <path d="M3.8 16.4v-.6l2.6-2.6h7.2l2.6 2.6v.6Z" />
    </>
  ),
  search: (
    <>
      <path d="M5.8 3.5h5.7L14 6v5.5L11.5 14H6l-2.5-2.5V6l2.3-2.5ZM13 13l3.5 3.5" />
      <path opacity=".45" d="M6.5 8.5v-1L7.6 6.4h1.5" />
    </>
  ),
  chart: (
    <>
      <path d="M3.3 16.4h13.4" />
      <path fill="currentColor" stroke="none" opacity=".45" d="M4.3 10h2.8v5.3H4.3zM8.6 6.7h2.8v8.6H8.6z" />
      <path fill="currentColor" stroke="none" d="M12.9 3.8h2.8v11.5h-2.8z" />
    </>
  ),
  filter: <path d="M3.5 4.5h13l-5 5.6v4.1l-3 1.6v-5.7l-5-5.6Z" />,
  comparisonMatch: <path d="m4.5 10 3.4 3.45 7.6-7.15" />,
  comparisonReview: <path d="M10 5.2v5.7m0 3.85v.15" />,
  comparisonMissing: <path d="M7.1 7.55a2.9 2.9 0 0 1 5.8 0c0 2.4-2.9 2.3-2.9 4.6m0 2.6v.15" />,
  external: <path d="M11.5 4H16v4.5m0-4.5-6.2 6.2M8 5H4.5v10.5H15V12" />,
  back: <path d="M16 10H4m0 0 4.5-4.5M4 10l4.5 4.5" />,
  chevron: <path d="m8 5 5 5-5 5" />,
  close: <path d="m5.5 5.5 9 9m0-9-9 9" />,
  send: (
    <>
      <path fill="currentColor" stroke="none" opacity=".22" d="m10 3 6 6-3.8 1.4L10 16l-2.2-5.6L4 9l6-6Z" />
      <path d="M10 15.5v-11m0 0L4.8 9.7M10 4.5l5.2 5.2" />
    </>
  ),
  loading: <path d="M15.7 6.2a6.6 6.6 0 1 1-5.7-2.8" />,
};

export type IconName = keyof typeof glyphs;

export function AppIcon({ name, size = 20, className }: { name: IconName; size?: number; className?: string }) {
  return (
    <svg
      className={className}
      width={size}
      height={size}
      viewBox="0 0 20 20"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      {glyphs[name]}
    </svg>
  );
}

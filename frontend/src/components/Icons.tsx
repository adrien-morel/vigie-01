const base = {
  width: 13,
  height: 13,
  viewBox: "0 0 16 16",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 1.7,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
  "aria-hidden": true,
};

export const SearchIcon = () => (
  <svg {...base} width={14} height={14}>
    <circle cx="7" cy="7" r="4.5" />
    <path d="M10.5 10.5 14 14" />
  </svg>
);

export const CheckIcon = () => (
  <svg {...base}>
    <path d="M3 8.5 6.2 11.5 13 4.5" />
  </svg>
);

export const AlertIcon = () => (
  <svg {...base}>
    <path d="M8 2.2 14.5 13.5h-13z" />
    <path d="M8 6.6v3" />
    <path d="M8 11.7h.01" />
  </svg>
);

export const PinIcon = () => (
  <svg {...base} width={11} height={11}>
    <path d="M8 14.5s5-4.6 5-8a5 5 0 1 0-10 0c0 3.4 5 8 5 8Z" />
    <circle cx="8" cy="6.4" r="1.8" />
  </svg>
);

export const ListIcon = () => (
  <svg {...base} width={14} height={14}>
    <path d="M6 4h8M6 8h8M6 12h8M2.5 4h.01M2.5 8h.01M2.5 12h.01" />
  </svg>
);

export const MapIcon = () => (
  <svg {...base} width={14} height={14}>
    <path d="M1.5 4 6 2.2l4 1.8 4.5-1.8v9.6L10 13.6l-4-1.8-4.5 1.8z" />
    <path d="M6 2.2v9.6M10 4v9.6" />
  </svg>
);

export const SunIcon = () => (
  <svg {...base} width={15} height={15}>
    <circle cx="8" cy="8" r="3.1" />
    <path d="M8 1v1.6M8 13.4V15M15 8h-1.6M2.6 8H1M12.9 3.1l-1.1 1.1M4.2 11.8l-1.1 1.1M12.9 12.9l-1.1-1.1M4.2 4.2 3.1 3.1" />
  </svg>
);

export const ThreadIcon = () => (
  <svg {...base} width={12} height={12}>
    <circle cx="4" cy="4" r="2" />
    <circle cx="4" cy="12" r="2" />
    <circle cx="12" cy="8" r="2" />
    <path d="M5.6 5.1 10.4 7.2M5.6 10.9 10.4 8.8" />
  </svg>
);

export const MoonIcon = () => (
  <svg {...base} width={15} height={15}>
    <path d="M13.5 9.4A5.9 5.9 0 0 1 6.6 2.5a5.9 5.9 0 1 0 6.9 6.9Z" />
  </svg>
);

export const CloseIcon = () => (
  <svg {...base} width={11} height={11}>
    <path d="M4 4l8 8M12 4l-8 8" />
  </svg>
);

export const ArrowUpIcon = () => (
  <svg {...base} width={14} height={14}>
    <path d="M8 13V3.5" />
    <path d="M3.8 7.4 8 3.2l4.2 4.2" />
  </svg>
);

export const FilterIcon = () => (
  <svg {...base} width={14} height={14}>
    <path d="M2 3.5h12l-4.6 5.2v4.4l-2.8 1.4V8.7z" />
  </svg>
);

/** Chevron for a sortable column header. `dir` carries the direction, never colour alone. */
export const SortIcon = ({ dir }: { dir: "asc" | "desc" | null }) => (
  <svg {...base} width={11} height={11} className="sort-icon">
    <path d="M8 3v10" opacity={dir ? 1 : 0.35} />
    {dir === "desc" ? <path d="M4.4 9.4 8 13l3.6-3.6" /> : <path d="M4.4 6.6 8 3l3.6 3.6" opacity={dir ? 1 : 0.35} />}
  </svg>
);

/* Brand marks, filled rather than stroked: the official glyphs are solid shapes, and redrawing them
   as outlines to match the icon set would make them unrecognisable at 13 px — which is the only
   thing a brand mark has to do. */
const brand = { viewBox: "0 0 16 16", fill: "currentColor", "aria-hidden": true };

export const GitHubIcon = () => (
  <svg {...brand} width={14} height={14}>
    <path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27s1.36.09 2 .27c1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.012 8.012 0 0 0 16 8c0-4.42-3.58-8-8-8Z" />
  </svg>
);

export const LinkedInIcon = () => (
  <svg {...brand} width={14} height={14}>
    <path d="M13.63 13.63h-2.37V9.92c0-.89-.02-2.02-1.23-2.02-1.23 0-1.42.96-1.42 1.96v3.77H6.24V6h2.28v1.04h.03c.32-.6 1.09-1.23 2.25-1.23 2.4 0 2.85 1.58 2.85 3.64v4.18ZM3.56 4.96a1.38 1.38 0 1 1 0-2.75 1.38 1.38 0 0 1 0 2.75Zm1.19 8.67H2.37V6h2.38v7.63ZM14.82 0H1.18C.53 0 0 .52 0 1.16v13.68C0 15.48.53 16 1.18 16h13.63c.65 0 1.19-.52 1.19-1.16V1.16C16 .52 15.46 0 14.82 0Z" />
  </svg>
);

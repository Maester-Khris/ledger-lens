interface PagerProps {
  page: number;
  pageCount: number;
  onChange: (page: number) => void;
  label: string;
}

export function Pager({ page, pageCount, onChange, label }: PagerProps) {
  if (pageCount <= 1) return null;
  return (
    <nav className="pager" aria-label={label}>
      <button type="button" className="btn btn-secondary pager__btn" disabled={page <= 1} onClick={() => onChange(page - 1)}>
        ← Previous
      </button>
      <span className="pager__status mono">
        Page {page} of {pageCount}
      </span>
      <button type="button" className="btn btn-secondary pager__btn" disabled={page >= pageCount} onClick={() => onChange(page + 1)}>
        Next →
      </button>
    </nav>
  );
}

import { CopyIcon } from './Icons';

type CopyButtonProps = {
  value: string;
};

export function CopyButton({ value }: CopyButtonProps) {
  return (
    <button
      type="button"
      className="copy-btn"
      aria-label={`Copy ${value}`}
      onClick={(event) => {
        event.stopPropagation();
        // ponytail: clipboard can be unavailable (non-secure origin) — copying is a convenience, fail silently
        navigator.clipboard?.writeText(value).catch(() => {});
      }}
    >
      <CopyIcon size={12} />
    </button>
  );
}

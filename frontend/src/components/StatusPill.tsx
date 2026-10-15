import './StatusPill.css';

export type StatusVariant = 'success' | 'warning' | 'error' | 'neutral' | 'accent' | 'purple';

type StatusPillProps = {
  variant: StatusVariant;
  children: React.ReactNode;
  dot?: boolean;
};

export function StatusPill({ variant, children, dot = false }: StatusPillProps) {
  return (
    <span className={`status-pill status-pill--${variant}`}>
      {dot && <span className="status-pill__dot" />}
      {children}
    </span>
  );
}

interface BrandMarkProps {
  size?: number;
  className?: string;
}

// The ledger mark (a balanced "=" on the accent disc); decorative — the product name is always next to it.
export function BrandMark({ size = 24, className }: BrandMarkProps) {
  return <img src="/favicon.svg" width={size} height={size} alt="" className={className} />;
}

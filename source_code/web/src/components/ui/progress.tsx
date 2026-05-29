import { cn } from "../../lib/cn";

export interface ProgressProps {
  value: number;
  className?: string;
}

export function Progress({ value, className }: ProgressProps) {
  const clamped = Math.min(100, Math.max(0, value));
  return (
    <div
      role="progressbar"
      aria-valuenow={clamped}
      aria-valuemin={0}
      aria-valuemax={100}
      className={cn("h-2 rounded-full bg-elevated overflow-hidden", className)}
    >
      <div
        className="h-full bg-accent rounded-full transition-all"
        style={{ width: `${clamped}%` }}
      />
    </div>
  );
}

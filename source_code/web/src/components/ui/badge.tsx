import { cva, type VariantProps } from "class-variance-authority";
import { HTMLAttributes } from "react";
import { cn } from "../../lib/cn";

export const badgeVariants = cva(
  "inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium",
  {
    variants: {
      variant: {
        queued: "bg-state-queued/15 text-state-queued",
        running: "bg-state-running/15 text-state-running",
        done: "bg-state-done/20 text-state-done",
        failed: "bg-state-failed/15 text-state-failed",
        skipped: "bg-state-skipped/15 text-state-skipped",
        cancelled: "bg-state-cancelled/20 text-muted",
        neutral: "bg-surface text-muted",
        accent: "bg-accent/15 text-accent",
      },
    },
    defaultVariants: {
      variant: "neutral",
    },
  }
);

export type BadgeVariant = NonNullable<VariantProps<typeof badgeVariants>["variant"]>;

export interface BadgeProps
  extends HTMLAttributes<HTMLSpanElement>,
    VariantProps<typeof badgeVariants> {}

export function Badge({ className, variant, ...props }: BadgeProps) {
  return (
    <span className={cn(badgeVariants({ variant }), className)} {...props} />
  );
}

export function jobStateVariant(state: string): BadgeVariant {
  switch (state) {
    case "queued": return "queued";
    case "running": return "running";
    case "done": return "done";
    case "failed": return "failed";
    case "skipped_larger":
    case "skipped": return "skipped";
    case "cancelled": return "cancelled";
    default: return "neutral";
  }
}

export function eligibilityVariant(e: string): BadgeVariant {
  switch (e) {
    case "needs_transcode": return "accent";
    case "already_h265": return "neutral";
    case "below_1080p": return "queued";
    case "excluded": return "skipped";
    default: return "neutral";
  }
}

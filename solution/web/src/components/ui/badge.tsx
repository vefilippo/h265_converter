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
        downloading: "bg-cyan-500/15 text-cyan-400",
        transcoding: "bg-amber-500/15 text-amber-400",
        uploading: "bg-teal-500/15 text-teal-400",
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
    case "downloading": return "downloading";
    case "transcoding": return "transcoding";
    case "uploading": return "uploading";
    default: return "neutral";
  }
}

export function jobStateLabel(job: { state: string; phase: string | null }): string {
  if (job.state === "running" && job.phase) {
    return job.phase.charAt(0).toUpperCase() + job.phase.slice(1);
  }
  return job.state;
}

export function jobTitle(job: { title: string | null; season: number | null; episode: number | null }): string {
  if (job.season != null && job.episode != null) {
    const s = String(job.season).padStart(2, "0");
    const e = String(job.episode).padStart(2, "0");
    return `${job.title ?? "—"} — S${s}E${e}`;
  }
  return job.title ?? "—";
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

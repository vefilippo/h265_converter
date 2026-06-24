import { useEffect, useState } from "react";
import { useVersion } from "../hooks/queries";
import { compareVersions } from "../lib/semver";
import { WhatsNewModal } from "./WhatsNewModal";

const SEEN_KEY = "h265:lastSeenVersion";

export function VersionBadge() {
  const { data } = useVersion();
  const version = data?.version;
  const [open, setOpen] = useState(false);

  useEffect(() => {
    if (!version) return;
    let seen: string | null = null;
    try {
      seen = localStorage.getItem(SEEN_KEY);
    } catch {
      seen = null;
    }
    if (seen === null || compareVersions(seen, version) < 0) {
      setOpen(true);
      try {
        localStorage.setItem(SEEN_KEY, version);
      } catch {
        /* ignore quota/availability errors */
      }
    }
  }, [version]);

  return (
    <>
      <button
        type="button"
        className="text-xs text-muted hover:text-fg transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/50 rounded"
        onClick={() => setOpen(true)}
      >
        v{version ?? "—"}
      </button>
      <WhatsNewModal open={open} onClose={() => setOpen(false)} />
    </>
  );
}

import { Dialog } from "./ui/dialog";
import { getReleases } from "../changelog";

export function WhatsNewModal({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  const releases = getReleases();
  return (
    <Dialog open={open} onClose={onClose} title="What's New">
      <div className="space-y-4 max-h-[60vh] overflow-y-auto">
        {releases.map((r) => (
          <div key={r.version}>
            <div className="flex items-baseline gap-2">
              <span className="font-medium text-fg">v{r.version}</span>
              <span className="text-xs text-muted">{r.date}</span>
            </div>
            <div className="text-sm text-accent">{r.label}</div>
            <ul className="mt-1 list-disc list-inside text-sm text-muted">
              {r.entries.map((e, i) => (
                <li key={i}>{e}</li>
              ))}
            </ul>
          </div>
        ))}
      </div>
    </Dialog>
  );
}

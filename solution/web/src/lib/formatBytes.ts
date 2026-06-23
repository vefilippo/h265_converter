// Human-readable byte formatting using binary (1024) units, matching how disk
// sizes are reported by Sonarr/Radarr and the OS. Picks the largest unit that
// keeps the number readable and trims trailing ".0" for whole values.
const UNITS = ["B", "KB", "MB", "GB", "TB", "PB"];

export function formatBytes(bytes: number | null | undefined): string {
  if (bytes == null || !Number.isFinite(bytes) || bytes <= 0) return "0 B";
  const i = Math.min(UNITS.length - 1, Math.floor(Math.log(bytes) / Math.log(1024)));
  const value = bytes / Math.pow(1024, i);
  // No decimals for bytes; 1 decimal for KB+ unless it's a whole number.
  const text = i === 0 ? String(Math.round(value))
    : value % 1 === 0 ? String(value)
    : value.toFixed(value >= 100 ? 0 : 1);
  return `${text} ${UNITS[i]}`;
}

// Compare two "major.minor.patch" strings numerically. Any suffix (e.g. a
// pre-release tag) is ignored; non-numeric components are treated as 0.
export function compareVersions(a: string, b: string): number {
  const parse = (v: string) =>
    v.split(".").slice(0, 3).map((p) => {
      const n = parseInt(p, 10);
      return Number.isNaN(n) ? 0 : n;
    });
  const pa = parse(a);
  const pb = parse(b);
  for (let i = 0; i < 3; i++) {
    const da = pa[i] ?? 0;
    const db = pb[i] ?? 0;
    if (da !== db) return da < db ? -1 : 1;
  }
  return 0;
}

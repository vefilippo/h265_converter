import { releases, type RawRelease } from "./data";
import { strings, type Locale } from "./strings";

export interface ResolvedRelease {
  version: string;
  date: string;
  label: string;
  entries: string[];
}

export const locales: Locale[] = Object.keys(strings) as Locale[];

function resolve(key: string, locale: Locale): string {
  const value = strings[locale]?.[key];
  if (value === undefined) {
    throw new Error(`Missing i18n key "${key}" for locale "${locale}"`);
  }
  return value;
}

export function getReleases(locale: Locale = "en"): ResolvedRelease[] {
  return releases.map((r: RawRelease) => ({
    version: r.version,
    date: r.date,
    label: resolve(r.labelKey, locale),
    entries: r.entryKeys.map((k) => resolve(k, locale)),
  }));
}

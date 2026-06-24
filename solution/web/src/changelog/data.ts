export interface RawRelease {
  version: string;
  date: string;
  labelKey: string;
  entryKeys: string[];
}

// Newest first. Entries are i18n keys (resolved via ./strings), never literal text.
export const releases: RawRelease[] = [
  {
    version: "1.0.0",
    date: "2026-06-24",
    labelKey: "changelog.1_0_0.label",
    entryKeys: [
      "changelog.1_0_0.entry.initial",
      "changelog.1_0_0.entry.whatsnew",
    ],
  },
];

// The unreleased/draft template. Accumulate entry keys here between releases.
// `cut-release` moves them into data.ts + strings.ts, then resets this file and
// bumps currentVersion/nextVersion.
export const draft = {
  currentVersion: "1.0.1",
  nextVersion: "1.1.0",
  entryKeys: [
    "changelog.1_1_0.entry.restore_restart",
    "changelog.1_1_0.entry.encoder_family",
  ] as string[],
};

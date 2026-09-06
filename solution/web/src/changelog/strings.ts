export type Locale = "en";

export const strings: Record<Locale, Record<string, string>> = {
  en: {
    "changelog.1_1_0.label": "Encoder support and reliable restore",
    "changelog.1_1_0.entry.installer_port":
      "Choose the dashboard port during installation with a live availability check. The tray launcher respects the chosen port and waits for the server before opening the dashboard; fresh-install startup and occupied-port handling are also fixed.",
    "changelog.1_1_0.entry.restore_restart":
      "Backup restore now restarts the server and applies saved jobs, library, exclusions and settings. The dashboard waits for the restart instead of reloading unchanged data.",
    "changelog.1_1_0.entry.encoder_family":
      "The HandBrake encoder is now a detected, selectable setting: AMD VCN, NVIDIA NVENC, Intel QSV, CPU x265 or your own presets, with an Auto mode that picks the best encoder your machine actually reports. Fresh installs on AMD or Intel hardware no longer fail every job on hardcoded NVENC presets.",
    "changelog.1_0_1.label": "Jobs list fixes",
    "changelog.1_0_1.entry.jobs_newest_first":
      "Jobs page now lists the newest jobs first and paginates: recent jobs (including movies) no longer disappear once the table grows past 100 entries.",
    "changelog.1_0_1.entry.jobs_badges":
      "Job filter badges now show accurate whole-table counts instead of counting only the visible page.",
    "changelog.1_0_0.label": "Initial release",
    "changelog.1_0_0.entry.initial":
      "First tagged release of the H.265 Transcoder.",
    "changelog.1_0_0.entry.whatsnew":
      "Added an in-app version badge and a What's New modal.",
  },
};

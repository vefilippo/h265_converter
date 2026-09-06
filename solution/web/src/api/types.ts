export interface MediaItem {
  id: number; source: string; external_id: string; title: string;
  season: number | null; episode: number | null; year: number | null;
  resolution: number; quality: string | null; languages: string | null;
  codec: string | null; is_h265: boolean; eligibility: string;
}
export interface LibraryPage { total: number; items: MediaItem[]; }
export interface StatRow { source: string; eligibility: string; count: number; }
export interface Job {
  id: number; media_item_id: number; state: string; progress: number;
  preset: string | null; original_size: number | null; output_size: number | null;
  reduction_pct: number | null; output_filename: string | null;
  error_message: string | null; title: string | null;
  season: number | null; episode: number | null;
  phase: string | null;
  created_at: string | null; started_at: string | null; finished_at: string | null;
}
export interface JobPage { total: number; items: Job[]; state_counts: Record<string, number>; }
export interface JobLog { log: string; }
export interface Exclusion { id: number; source: string; key: string; reason: string; matched: boolean; }
export interface Savings {
  bytes_saved: number; original_bytes: number; output_bytes: number;
  percent_saved: number; files_done: number;
}
export interface Status {
  worker_alive: boolean; current_job: Job | null; queue_length: number;
  stats: StatRow[]; savings: Savings;
}
export interface ScanStatus {
  state: string; detail: Record<string, unknown>;
  started_at: string | null; finished_at: string | null;
}
export interface LogLine { seq: number; ts: string; level: string; message: string; }
export interface LogPage { lines: LogLine[]; last_seq: number; }

export interface Settings {
  scheduler_cron: string | null;
  scheduler_run_at_startup: string;
  sonarr_url: string;
  sonarr_api_key: string;
  radarr_url: string;
  radarr_api_key: string;
  sftp_host: string;
  sftp_port: string;
  sftp_username: string;
  sftp_password: string;
  handbrake_cli: string;
  handbrake_preset_1080: string;
  handbrake_preset_4k: string;
  encoder_family: EncoderFamilyId;
  encoder_fallback_cpu: string;
  scheduler_next_run: string | null;
  webhook_username: string;
  webhook_password_set: boolean;
}

export interface SettingsUpdate {
  scheduler_cron?: string | null;
  scheduler_run_at_startup?: string;
  sonarr_url?: string;
  sonarr_api_key?: string;
  radarr_url?: string;
  radarr_api_key?: string;
  sftp_host?: string;
  sftp_port?: string;
  sftp_username?: string;
  sftp_password?: string;
  handbrake_cli?: string;
  handbrake_preset_1080?: string;
  handbrake_preset_4k?: string;
  encoder_family?: EncoderFamilyId;
  encoder_fallback_cpu?: string;
  current_password?: string;
  new_password?: string;
  webhook_username?: string;
  webhook_password?: string;
}

export type EncoderFamilyId = "auto" | "vcn" | "nvenc" | "qsv" | "cpu" | "custom";

const FAMILY_IDS: readonly EncoderFamilyId[] = ["auto", "vcn", "nvenc", "qsv", "cpu", "custom"];
export function asFamilyId(v: string): EncoderFamilyId {
  return (FAMILY_IDS as readonly string[]).includes(v) ? (v as EncoderFamilyId) : "auto";
}

export interface EncoderFamily {
  id: EncoderFamilyId;
  label: string;
  preset_1080: string;
  preset_4k: string;
  hardware: boolean;
  available: boolean;
}

export interface EncodersResponse {
  available: string[];
  detected_at: string | null;
  families: EncoderFamily[];
}

export interface DetectResponse extends EncodersResponse {
  ok: boolean;
  error?: string;
}

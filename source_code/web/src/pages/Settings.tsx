import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import cronstrue from 'cronstrue';
import { getSettings, updateSettings } from '../api/client';
import type { SettingsUpdate } from '../api/types';

const REDACTED = '••••••••';
const PRESETS = ['H.265 NVENC 1080p', 'H.265 NVENC 2160p 4K'];

function Section({ title, children, onSave, saving, saved, error }: {
  title: string;
  children: React.ReactNode;
  onSave: () => void;
  saving: boolean;
  saved: boolean;
  error: string | null;
}) {
  return (
    <div className="mb-8 rounded-lg border border-gray-200 bg-white p-6 shadow-sm">
      <h2 className="mb-4 text-lg font-semibold text-gray-900">{title}</h2>
      <div className="space-y-4">{children}</div>
      <div className="mt-4 flex items-center gap-3">
        <button
          onClick={onSave}
          disabled={saving}
          className="rounded bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
        >
          {saving ? 'Saving…' : 'Save'}
        </button>
        {saved && <span className="text-sm text-green-600">Saved</span>}
        {error && <span className="text-sm text-red-600">{error}</span>}
      </div>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-3 items-start gap-4">
      <label className="pt-2 text-sm font-medium text-gray-700">{label}</label>
      <div className="col-span-2">{children}</div>
    </div>
  );
}

function Input({ value, onChange, type = 'text', placeholder }: {
  value: string; onChange: (v: string) => void; type?: string; placeholder?: string;
}) {
  return (
    <input
      type={type}
      value={value}
      onChange={e => onChange(e.target.value)}
      placeholder={placeholder}
      className="w-full rounded border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
    />
  );
}

function MaskedInput({ value, onChange, placeholder }: {
  value: string; onChange: (v: string) => void; placeholder?: string;
}) {
  const [show, setShow] = useState(false);
  return (
    <div className="flex gap-2">
      <input
        type={show ? 'text' : 'password'}
        value={value}
        onChange={e => onChange(e.target.value)}
        placeholder={placeholder}
        className="w-full rounded border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
      />
      <button
        type="button"
        onClick={() => setShow(s => !s)}
        className="shrink-0 rounded border border-gray-300 px-3 py-2 text-xs text-gray-600 hover:bg-gray-50"
      >
        {show ? 'Hide' : 'Show'}
      </button>
    </div>
  );
}

function cronDescription(expr: string): string {
  try { return cronstrue.toString(expr); }
  catch { return 'Invalid cron expression'; }
}

export default function Settings() {
  const qc = useQueryClient();
  const { data, isLoading } = useQuery({ queryKey: ['settings'], queryFn: getSettings });

  const [cron, setCron] = useState('');
  const [schedEnabled, setSchedEnabled] = useState(false);
  const [runAtStartup, setRunAtStartup] = useState(false);
  const [schedSaved, setSchedSaved] = useState(false);
  const [schedError, setSchedError] = useState<string | null>(null);

  const [sonarrUrl, setSonarrUrl] = useState('');
  const [sonarrKey, setSonarrKey] = useState(REDACTED);
  const [radarrUrl, setRadarrUrl] = useState('');
  const [radarrKey, setRadarrKey] = useState(REDACTED);
  const [sftpHost, setSftpHost] = useState('');
  const [sftpPort, setSftpPort] = useState('22');
  const [sftpUser, setSftpUser] = useState(REDACTED);
  const [sftpPass, setSftpPass] = useState(REDACTED);
  const [connSaved, setConnSaved] = useState(false);
  const [connError, setConnError] = useState<string | null>(null);

  const [hbCli, setHbCli] = useState('');
  const [hbPreset, setHbPreset] = useState(PRESETS[0]);
  const [transSaved, setTransSaved] = useState(false);
  const [transError, setTransError] = useState<string | null>(null);

  const [currentPw, setCurrentPw] = useState('');
  const [newPw, setNewPw] = useState('');
  const [confirmPw, setConfirmPw] = useState('');
  const [secSaved, setSecSaved] = useState(false);
  const [secError, setSecError] = useState<string | null>(null);

  const [seeded, setSeeded] = useState(false);
  if (data && !seeded) {
    setCron(data.scheduler_cron ?? '');
    setSchedEnabled(!!data.scheduler_cron);
    setRunAtStartup(data.scheduler_run_at_startup === 'true');
    setSonarrUrl(data.sonarr_url);
    setSonarrKey(data.sonarr_api_key || REDACTED);
    setRadarrUrl(data.radarr_url);
    setRadarrKey(data.radarr_api_key || REDACTED);
    setSftpHost(data.sftp_host);
    setSftpPort(data.sftp_port);
    setSftpUser(data.sftp_username || REDACTED);
    setSftpPass(data.sftp_password || REDACTED);
    setHbCli(data.handbrake_cli);
    setHbPreset(data.handbrake_preset || PRESETS[0]);
    setSeeded(true);
  }

  const mut = useMutation({
    mutationFn: updateSettings,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['settings'] }),
  });

  const save = async (
    payload: SettingsUpdate,
    setSaved: (v: boolean) => void,
    setError: (v: string | null) => void
  ) => {
    setError(null);
    try {
      await mut.mutateAsync(payload);
      setSaved(true);
      setTimeout(() => setSaved(false), 3000);
    } catch (e: unknown) {
      setSaved(false);
      setError(e instanceof Error ? e.message : 'Save failed');
    }
  };

  if (isLoading) return <div className="p-8 text-gray-500">Loading settings…</div>;

  return (
    <div className="mx-auto max-w-2xl p-8">
      <h1 className="mb-6 text-2xl font-bold text-gray-900">Settings</h1>

      <Section
        title="Scheduler"
        onSave={() => save(
          { scheduler_cron: schedEnabled ? cron : null,
            scheduler_run_at_startup: runAtStartup ? 'true' : 'false' },
          setSchedSaved, setSchedError
        )}
        saving={mut.isPending}
        saved={schedSaved}
        error={schedError}
      >
        <Field label="Run at startup">
          <label className="flex items-center gap-2 text-sm text-gray-700">
            <input type="checkbox" checked={runAtStartup}
              onChange={e => setRunAtStartup(e.target.checked)} className="h-4 w-4" />
            Trigger a scan when the server starts
          </label>
        </Field>
        <Field label="Enable schedule">
          <label className="flex items-center gap-2 text-sm text-gray-700">
            <input type="checkbox" checked={schedEnabled}
              onChange={e => setSchedEnabled(e.target.checked)} className="h-4 w-4" />
            Run on a cron schedule
          </label>
        </Field>
        {schedEnabled && (
          <Field label="Cron expression">
            <Input value={cron} onChange={setCron} placeholder="0 3 * * *" />
            {cron && <p className="mt-1 text-xs text-gray-500">{cronDescription(cron)}</p>}
            {data?.scheduler_next_run && (
              <p className="mt-1 text-xs text-gray-400">
                Next run: {new Date(data.scheduler_next_run).toLocaleString()}
              </p>
            )}
            <a href="https://crontab.guru" target="_blank" rel="noreferrer"
              className="mt-1 block text-xs text-blue-500 hover:underline">
              crontab.guru →
            </a>
          </Field>
        )}
      </Section>

      <Section
        title="Connections"
        onSave={() => save(
          { sonarr_url: sonarrUrl, sonarr_api_key: sonarrKey,
            radarr_url: radarrUrl, radarr_api_key: radarrKey,
            sftp_host: sftpHost, sftp_port: sftpPort,
            sftp_username: sftpUser, sftp_password: sftpPass },
          setConnSaved, setConnError
        )}
        saving={mut.isPending} saved={connSaved} error={connError}
      >
        <Field label="Sonarr URL"><Input value={sonarrUrl} onChange={setSonarrUrl} /></Field>
        <Field label="Sonarr API key"><MaskedInput value={sonarrKey} onChange={setSonarrKey} /></Field>
        <Field label="Radarr URL"><Input value={radarrUrl} onChange={setRadarrUrl} /></Field>
        <Field label="Radarr API key"><MaskedInput value={radarrKey} onChange={setRadarrKey} /></Field>
        <Field label="SFTP host"><Input value={sftpHost} onChange={setSftpHost} /></Field>
        <Field label="SFTP port"><Input value={sftpPort} onChange={setSftpPort} /></Field>
        <Field label="SFTP username"><MaskedInput value={sftpUser} onChange={setSftpUser} /></Field>
        <Field label="SFTP password"><MaskedInput value={sftpPass} onChange={setSftpPass} /></Field>
      </Section>

      <Section
        title="Transcoding"
        onSave={() => save(
          { handbrake_cli: hbCli, handbrake_preset: hbPreset },
          setTransSaved, setTransError
        )}
        saving={mut.isPending} saved={transSaved} error={transError}
      >
        <Field label="HandBrake CLI path">
          <Input value={hbCli} onChange={setHbCli} placeholder="C:\...\HandBrakeCLI.exe" />
        </Field>
        <Field label="Preset">
          <select value={hbPreset} onChange={e => setHbPreset(e.target.value)}
            className="w-full rounded border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500">
            {PRESETS.map(p => <option key={p} value={p}>{p}</option>)}
          </select>
        </Field>
      </Section>

      <Section
        title="Security"
        onSave={() => {
          if (newPw !== confirmPw) { setSecError('Passwords do not match'); return; }
          save({ current_password: currentPw, new_password: newPw }, setSecSaved, setSecError);
        }}
        saving={mut.isPending} saved={secSaved} error={secError}
      >
        <Field label="Current password">
          <Input type="password" value={currentPw} onChange={setCurrentPw} />
        </Field>
        <Field label="New password">
          <Input type="password" value={newPw} onChange={setNewPw} />
        </Field>
        <Field label="Confirm new password">
          <Input type="password" value={confirmPw} onChange={setConfirmPw} />
        </Field>
      </Section>
    </div>
  );
}

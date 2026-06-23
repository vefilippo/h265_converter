import { useEffect, useState } from 'react';
import { usePageTitle } from '../hooks/usePageTitle';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import cronstrue from 'cronstrue';
import { Button } from '../components/ui/button';
import { Card, CardContent, CardHeader } from '../components/ui/card';
import { Input } from '../components/ui/input';
import { Spinner } from '../components/ui/spinner';
import { api, getSettings, updateSettings } from '../api/client';
import BackupRestoreCard from './BackupRestoreCard';
import type { SettingsUpdate } from '../api/types';

const REDACTED = '••••••••';

// ── helpers ──────────────────────────────────────────────────────────────────

function cronDesc(expr: string): string {
  try { return cronstrue.toString(expr); }
  catch { return ''; }
}

function cronValid(expr: string): boolean {
  try { cronstrue.toString(expr); return true; }
  catch { return false; }
}

// ── primitive components ──────────────────────────────────────────────────────

/** Label above input, compact — used inside SubCards */
function LabeledField({ htmlFor, label, children }: {
  htmlFor: string; label: string; children: React.ReactNode;
}) {
  return (
    <div className="space-y-1">
      <label htmlFor={htmlFor} className="block text-xs font-medium text-muted">{label}</label>
      {children}
    </div>
  );
}

/** 3-col grid label / input — used in Scheduler and Security */
function Field({ htmlFor, label, children }: {
  htmlFor: string; label: string; children: React.ReactNode;
}) {
  return (
    <div className="grid grid-cols-3 items-start gap-4">
      <label htmlFor={htmlFor} className="pt-2 text-sm font-medium text-muted">{label}</label>
      <div className="col-span-2">{children}</div>
    </div>
  );
}

/** Password input with accessible show/hide toggle.
 *  When value is the REDACTED sentinel the input shows empty with a
 *  placeholder so the user knows a value is saved without seeing bullets. */
function MaskedInput({ id, fieldLabel, value, onChange }: {
  id: string; fieldLabel: string; value: string; onChange: (v: string) => void;
}) {
  const [show, setShow] = useState(false);
  const isRedacted = value === REDACTED;

  return (
    <div className="flex gap-2">
      <Input
        id={id}
        type={show ? 'text' : 'password'}
        value={isRedacted ? '' : value}
        placeholder={isRedacted ? 'saved — type to change' : undefined}
        onChange={e => onChange(e.target.value)}
        className="w-full"
      />
      <Button type="button" variant="outline" size="sm"
        onClick={() => setShow(s => !s)}
        aria-pressed={show}
        aria-label={show ? `Hide ${fieldLabel}` : `Show ${fieldLabel}`}>
        {show ? 'Hide' : 'Show'}
      </Button>
    </div>
  );
}

/** Persistent live-region feedback (always in DOM so AT picks up updates) */
function StatusMessage({ saving, saved, error }: {
  saving: boolean; saved: boolean; error: string | null;
}) {
  return (
    <div role="status" aria-live="polite" aria-atomic="true" className="min-h-[1.25rem] text-sm">
      {saved && !saving && <span className="text-accent">Saved</span>}
      {error && !saving && <span role="alert" className="text-state-failed">{error}</span>}
    </div>
  );
}

/** Dark sub-card for service groups inside Connections */
function SubCard({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-md border border-border bg-elevated p-4">
      <h3 className="mb-3 text-sm font-semibold text-fg">{title}</h3>
      <div className="space-y-3">{children}</div>
    </div>
  );
}

/** Test-connection button with inline status.
 *  Passes current form values so the test reflects what you see, not what's saved. */
function TestButton({ service, params }: {
  service: 'sonarr' | 'radarr' | 'sftp';
  params: Record<string, string>;
}) {
  const [status, setStatus] = useState<'idle' | 'testing' | 'ok' | 'fail'>('idle');

  async function test() {
    setStatus('testing');
    try {
      const result = await api.post<{ ok: boolean }>(`/api/settings/test/${service}`, params);
      setStatus(result.ok ? 'ok' : 'fail');
    } catch {
      setStatus('fail');
    }
    setTimeout(() => setStatus('idle'), 5000);
  }

  return (
    <div className="mt-3 flex items-center gap-2">
      <Button type="button" variant="outline" size="sm"
        onClick={test} disabled={status === 'testing'} aria-busy={status === 'testing'}>
        {status === 'testing' ? 'Testing…' : 'Test connection'}
      </Button>
      {status === 'ok' && (
        <span role="status" className="text-xs text-accent">Connected ✓</span>
      )}
      {status === 'fail' && (
        <span role="alert" className="text-xs text-state-failed">Connection failed</span>
      )}
    </div>
  );
}

/** Unsaved-changes amber dot */
function DirtyDot() {
  return (
    <span className="ml-2 inline-block h-2 w-2 rounded-full bg-amber-400"
      aria-label="Unsaved changes" title="Unsaved changes" />
  );
}

// ── main component ────────────────────────────────────────────────────────────

export default function Settings() {
  usePageTitle("Settings");
  const qc = useQueryClient();
  const { data, isLoading } = useQuery({ queryKey: ['settings'], queryFn: getSettings });

  // Scheduler
  const [cron, setCron] = useState('');
  const [schedEnabled, setSchedEnabled] = useState(false);
  const [runAtStartup, setRunAtStartup] = useState(false);
  const [schedSaved, setSchedSaved] = useState(false);
  const [schedError, setSchedError] = useState<string | null>(null);
  const [schedDirty, setSchedDirty] = useState(false);

  // Connections
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
  const [connDirty, setConnDirty] = useState(false);

  // Encoder
  const [hbCli, setHbCli] = useState('');
  const [hbPreset1080, setHbPreset1080] = useState('H.265 NVENC 1080p');
  const [hbPreset4k, setHbPreset4k] = useState('H.265 NVENC 2160p 4K');
  const [transSaved, setTransSaved] = useState(false);
  const [transError, setTransError] = useState<string | null>(null);
  const [transDirty, setTransDirty] = useState(false);

  // Security
  const [currentPw, setCurrentPw] = useState('');
  const [newPw, setNewPw] = useState('');
  const [confirmPw, setConfirmPw] = useState('');
  const [secSaved, setSecSaved] = useState(false);
  const [secError, setSecError] = useState<string | null>(null);

  // Webhooks
  const [webhookUser, setWebhookUser] = useState('');
  const [webhookPass, setWebhookPass] = useState(REDACTED);
  const [webhookSaved, setWebhookSaved] = useState(false);
  const [webhookError, setWebhookError] = useState<string | null>(null);
  const [webhookDirty, setWebhookDirty] = useState(false);

  // Seed from server — useEffect to avoid setState-during-render anti-pattern
  useEffect(() => {
    if (!data) return;
    setCron(data.scheduler_cron ?? '');
    setSchedEnabled(!!data.scheduler_cron);
    setRunAtStartup(data.scheduler_run_at_startup === 'true');
    setSonarrUrl(data.sonarr_url);
    setSonarrKey(data.sonarr_api_key || REDACTED);
    setRadarrUrl(data.radarr_url);
    setRadarrKey(data.radarr_api_key || REDACTED);
    setSftpHost(data.sftp_host);
    setSftpPort(data.sftp_port);
    setSftpUser(data.sftp_username || '');
    setSftpPass(data.sftp_password || REDACTED);
    setHbCli(data.handbrake_cli);
    setHbPreset1080(data.handbrake_preset_1080 || 'H.265 NVENC 1080p');
    setHbPreset4k(data.handbrake_preset_4k || 'H.265 NVENC 2160p 4K');
    setWebhookUser(data.webhook_username || '');
    setWebhookPass(data.webhook_password_set ? REDACTED : '');
    setSchedDirty(false);
    setConnDirty(false);
    setTransDirty(false);
    setWebhookDirty(false);
  }, [data]);

  const onSuccess = () => qc.invalidateQueries({ queryKey: ['settings'] });
  const schedMut = useMutation({ mutationFn: updateSettings, onSuccess });
  const connMut = useMutation({ mutationFn: updateSettings, onSuccess });
  const transMut = useMutation({ mutationFn: updateSettings, onSuccess });
  const secMut = useMutation({ mutationFn: updateSettings, onSuccess });
  const webhookMut = useMutation({ mutationFn: updateSettings, onSuccess });

  async function save(
    payload: SettingsUpdate,
    mutateAsync: (p: SettingsUpdate) => Promise<unknown>,
    setSaved: (v: boolean) => void,
    setError: (v: string | null) => void,
    setDirty?: (v: boolean) => void,
  ) {
    setError(null);
    try {
      await mutateAsync(payload);
      setSaved(true);
      setDirty?.(false);
      setTimeout(() => setSaved(false), 3000);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Save failed');
    }
  }

  const cronDescription = cron ? cronDesc(cron) : '';
  const cronIsValid = !cron || cronValid(cron);
  const pwMismatch = !!(newPw && confirmPw && newPw !== confirmPw);
  const webhookBase = `${window.location.origin}/api/webhook`;

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-16">
        <Spinner size="lg" />
      </div>
    );
  }

  return (
    <main id="settings-main" aria-labelledby="settings-heading" className="mx-auto max-w-2xl p-8">
      <h1 id="settings-heading" className="mb-6 font-display text-2xl text-fg">Settings</h1>

      {/* ── Scheduler ── */}
      <section aria-labelledby="sched-heading" className="mb-6">
        <Card>
          <CardHeader className="flex flex-row items-center gap-2 border-b border-border">
            <h2 id="sched-heading" className="font-display text-lg text-fg">
              Scheduler
            </h2>
            {schedDirty && <DirtyDot />}
          </CardHeader>
          <CardContent className="space-y-5 pt-5">
            <div className="flex items-start gap-3">
              <input id="run-at-startup" type="checkbox" checked={runAtStartup}
                onChange={e => { setRunAtStartup(e.target.checked); setSchedDirty(true); }}
                className="mt-0.5 h-4 w-4 rounded accent-accent" />
              <label htmlFor="run-at-startup" className="cursor-pointer text-sm text-fg">
                Run at startup
                <span className="mt-0.5 block text-xs text-muted">
                  Trigger a scan each time the server starts
                </span>
              </label>
            </div>

            <div className="flex items-start gap-3">
              <input id="sched-enabled" type="checkbox" checked={schedEnabled}
                onChange={e => { setSchedEnabled(e.target.checked); setSchedDirty(true); }}
                className="mt-0.5 h-4 w-4 rounded accent-accent" />
              <label htmlFor="sched-enabled" className="cursor-pointer text-sm text-fg">
                Enable schedule
                <span className="mt-0.5 block text-xs text-muted">
                  Run a scan on a recurring cron schedule
                </span>
              </label>
            </div>

            {schedEnabled && (
              <Field htmlFor="cron-input" label="Cron expression">
                <Input id="cron-input" value={cron} placeholder="0 3 * * *"
                  aria-describedby={cron ? 'cron-desc' : undefined}
                  aria-invalid={cron !== '' && !cronIsValid}
                  onChange={e => { setCron(e.target.value); setSchedDirty(true); }}
                  className={cron && !cronIsValid ? 'border-state-failed focus:ring-state-failed/50' : ''} />
                <div id="cron-desc" className="mt-1 space-y-0.5">
                  {cron && cronIsValid && (
                    <p className="text-xs text-accent">{cronDescription}</p>
                  )}
                  {cron && !cronIsValid && (
                    <p role="alert" className="text-xs text-state-failed">
                      Invalid cron expression
                    </p>
                  )}
                  {data?.scheduler_next_run && cronIsValid && (
                    <p className="text-xs text-muted">
                      Next run:{' '}
                      {new Date(data.scheduler_next_run).toLocaleString(undefined, {
                        timeZoneName: 'short',
                      })}
                    </p>
                  )}
                  <a href="https://crontab.guru" target="_blank" rel="noreferrer"
                    className="block text-xs text-accent hover:underline">
                    crontab.guru →
                  </a>
                </div>
              </Field>
            )}

            <div className="flex items-center gap-3 border-t border-border pt-4">
              <Button size="sm"
                onClick={() => save(
                  { scheduler_cron: schedEnabled && cronIsValid ? cron || null : null,
                    scheduler_run_at_startup: runAtStartup ? 'true' : 'false' },
                  schedMut.mutateAsync, setSchedSaved, setSchedError, setSchedDirty,
                )}
                disabled={schedMut.isPending || (schedEnabled && !cronIsValid)}
                aria-busy={schedMut.isPending}
                aria-label="Save Scheduler settings">
                {schedMut.isPending ? 'Saving…' : 'Save'}
              </Button>
              <StatusMessage saving={schedMut.isPending} saved={schedSaved} error={schedError} />
            </div>
          </CardContent>
        </Card>
      </section>

      {/* ── Connections ── */}
      <section aria-labelledby="conn-heading" className="mb-6">
        <Card>
          <CardHeader className="flex flex-row items-center gap-2 border-b border-border">
            <h2 id="conn-heading" className="font-display text-lg text-fg">Connections</h2>
            {connDirty && <DirtyDot />}
          </CardHeader>
          <CardContent className="space-y-4 pt-5">

            {/* Sonarr + Radarr side-by-side */}
            <div className="grid grid-cols-2 gap-4">
              <SubCard title="Sonarr">
                <LabeledField htmlFor="sonarr-url" label="URL">
                  <Input id="sonarr-url" value={sonarrUrl} className="w-full"
                    onChange={e => { setSonarrUrl(e.target.value); setConnDirty(true); }} />
                </LabeledField>
                <LabeledField htmlFor="sonarr-key" label="API key">
                  <MaskedInput id="sonarr-key" fieldLabel="Sonarr API key"
                    value={sonarrKey} onChange={v => { setSonarrKey(v); setConnDirty(true); }} />
                </LabeledField>
                <TestButton service="sonarr" params={{ url: sonarrUrl, api_key: sonarrKey }} />
              </SubCard>

              <SubCard title="Radarr">
                <LabeledField htmlFor="radarr-url" label="URL">
                  <Input id="radarr-url" value={radarrUrl} className="w-full"
                    onChange={e => { setRadarrUrl(e.target.value); setConnDirty(true); }} />
                </LabeledField>
                <LabeledField htmlFor="radarr-key" label="API key">
                  <MaskedInput id="radarr-key" fieldLabel="Radarr API key"
                    value={radarrKey} onChange={v => { setRadarrKey(v); setConnDirty(true); }} />
                </LabeledField>
                <TestButton service="radarr" params={{ url: radarrUrl, api_key: radarrKey }} />
              </SubCard>
            </div>

            {/* SFTP full-width */}
            <SubCard title="SFTP">
              <div className="grid grid-cols-3 gap-3">
                <div className="col-span-2">
                  <LabeledField htmlFor="sftp-host" label="Host">
                    <Input id="sftp-host" value={sftpHost} className="w-full"
                      onChange={e => { setSftpHost(e.target.value); setConnDirty(true); }} />
                  </LabeledField>
                </div>
                <LabeledField htmlFor="sftp-port" label="Port">
                  <Input id="sftp-port" value={sftpPort} className="w-full"
                    onChange={e => { setSftpPort(e.target.value); setConnDirty(true); }} />
                </LabeledField>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <LabeledField htmlFor="sftp-user" label="Username">
                  <Input id="sftp-user" value={sftpUser} className="w-full"
                    onChange={e => { setSftpUser(e.target.value); setConnDirty(true); }} />
                </LabeledField>
                <LabeledField htmlFor="sftp-pass" label="Password">
                  <MaskedInput id="sftp-pass" fieldLabel="SFTP password"
                    value={sftpPass} onChange={v => { setSftpPass(v); setConnDirty(true); }} />
                </LabeledField>
              </div>
              <TestButton service="sftp" params={{ host: sftpHost, port: sftpPort, username: sftpUser, password: sftpPass }} />
            </SubCard>

            <div className="flex items-center gap-3 border-t border-border pt-4">
              <Button size="sm"
                onClick={() => save(
                  { sonarr_url: sonarrUrl, sonarr_api_key: sonarrKey,
                    radarr_url: radarrUrl, radarr_api_key: radarrKey,
                    sftp_host: sftpHost, sftp_port: sftpPort,
                    sftp_username: sftpUser, sftp_password: sftpPass },
                  connMut.mutateAsync, setConnSaved, setConnError, setConnDirty,
                )}
                disabled={connMut.isPending}
                aria-busy={connMut.isPending}
                aria-label="Save Connections settings">
                {connMut.isPending ? 'Saving…' : 'Save'}
              </Button>
              <StatusMessage saving={connMut.isPending} saved={connSaved} error={connError} />
            </div>
          </CardContent>
        </Card>
      </section>

      {/* ── Encoder ── */}
      <section aria-labelledby="enc-heading" className="mb-6">
        <Card>
          <CardHeader className="flex flex-row items-center gap-2 border-b border-border">
            <h2 id="enc-heading" className="font-display text-lg text-fg">Encoder</h2>
            {transDirty && <DirtyDot />}
          </CardHeader>
          <CardContent className="space-y-4 pt-5">
            <Field htmlFor="hb-cli" label="HandBrake CLI">
              <Input id="hb-cli" value={hbCli} placeholder="C:\...\HandBrakeCLI.exe"
                className="font-mono text-xs"
                onChange={e => { setHbCli(e.target.value); setTransDirty(true); }} />
            </Field>
            <Field htmlFor="hb-1080" label="1080p preset">
              <Input id="hb-1080" value={hbPreset1080}
                onChange={e => { setHbPreset1080(e.target.value); setTransDirty(true); }} />
            </Field>
            <Field htmlFor="hb-4k" label="4K preset">
              <Input id="hb-4k" value={hbPreset4k}
                onChange={e => { setHbPreset4k(e.target.value); setTransDirty(true); }} />
            </Field>

            <div className="flex items-center gap-3 border-t border-border pt-4">
              <Button size="sm"
                onClick={() => save(
                  { handbrake_cli: hbCli, handbrake_preset_1080: hbPreset1080,
                    handbrake_preset_4k: hbPreset4k },
                  transMut.mutateAsync, setTransSaved, setTransError, setTransDirty,
                )}
                disabled={transMut.isPending}
                aria-busy={transMut.isPending}
                aria-label="Save Encoder settings">
                {transMut.isPending ? 'Saving…' : 'Save'}
              </Button>
              <StatusMessage saving={transMut.isPending} saved={transSaved} error={transError} />
            </div>
          </CardContent>
        </Card>
      </section>

      {/* ── Security ── */}
      <section aria-labelledby="sec-heading" className="mb-6">
        <Card>
          <CardHeader className="border-b border-border">
            <h2 id="sec-heading" className="font-display text-lg text-fg">Security</h2>
          </CardHeader>
          <CardContent className="space-y-4 pt-5">
            <Field htmlFor="cur-pw" label="Current password">
              <Input id="cur-pw" type="password" value={currentPw}
                onChange={e => setCurrentPw(e.target.value)} />
            </Field>
            <Field htmlFor="new-pw" label="New password">
              <Input id="new-pw" type="password" value={newPw}
                onChange={e => setNewPw(e.target.value)} />
            </Field>
            <Field htmlFor="confirm-pw" label="Confirm new">
              <div>
                <Input id="confirm-pw" type="password" value={confirmPw}
                  aria-describedby={pwMismatch ? 'pw-mismatch' : undefined}
                  aria-invalid={pwMismatch}
                  className={pwMismatch ? 'border-state-failed focus:ring-state-failed/50' : ''}
                  onChange={e => setConfirmPw(e.target.value)} />
                {pwMismatch && (
                  <p id="pw-mismatch" role="alert" className="mt-1 text-xs text-state-failed">
                    Passwords do not match
                  </p>
                )}
              </div>
            </Field>

            <div className="flex items-center gap-3 border-t border-border pt-4">
              <Button size="sm"
                onClick={() => {
                  if (pwMismatch) { setSecError('Passwords do not match'); return; }
                  if (!newPw) { setSecError('New password is required'); return; }
                  save({ current_password: currentPw, new_password: newPw },
                    secMut.mutateAsync, setSecSaved, setSecError);
                }}
                disabled={secMut.isPending || pwMismatch}
                aria-busy={secMut.isPending}
                aria-label="Save Security settings">
                {secMut.isPending ? 'Saving…' : 'Save'}
              </Button>
              <StatusMessage saving={secMut.isPending} saved={secSaved} error={secError} />
            </div>
          </CardContent>
        </Card>
      </section>

      {/* ── Webhooks ── */}
      <section aria-labelledby="webhook-heading" className="mb-6">
        <Card>
          <CardHeader className="flex flex-row items-center gap-2 border-b border-border">
            <h2 id="webhook-heading" className="font-display text-lg text-fg">Webhooks</h2>
            {webhookDirty && <DirtyDot />}
          </CardHeader>
          <CardContent className="space-y-4 pt-5">
            <p className="text-sm text-muted">
              Add a <span className="font-medium text-fg">Webhook</span> connection in Sonarr and
              Radarr (Settings → Connect) pointing at the URLs below, triggered <span className="font-medium text-fg">On Import</span>{' '}and{' '}
              <span className="font-medium text-fg">On Import Upgrade</span>. Use the username and
              password below as the connection's Basic-auth credentials. The host must be reachable
              from the Sonarr/Radarr machine.
            </p>

            <div className="space-y-1 text-sm">
              <div className="text-xs font-medium text-muted">Sonarr URL</div>
              <code className="block break-all rounded bg-elevated px-2 py-1 font-mono text-xs text-fg">
                {webhookBase}/sonarr
              </code>
              <div className="pt-2 text-xs font-medium text-muted">Radarr URL</div>
              <code className="block break-all rounded bg-elevated px-2 py-1 font-mono text-xs text-fg">
                {webhookBase}/radarr
              </code>
            </div>

            <Field htmlFor="webhook-user" label="Webhook username">
              <Input id="webhook-user" value={webhookUser}
                onChange={e => { setWebhookUser(e.target.value); setWebhookDirty(true); }} />
            </Field>
            <Field htmlFor="webhook-pass" label="Webhook password">
              <MaskedInput id="webhook-pass" fieldLabel="Webhook password"
                value={webhookPass} onChange={v => { setWebhookPass(v); setWebhookDirty(true); }} />
            </Field>

            <div className="flex items-center gap-3 border-t border-border pt-4">
              <Button size="sm"
                onClick={() => save(
                  {
                    webhook_username: webhookUser,
                    ...(webhookPass !== REDACTED ? { webhook_password: webhookPass } : {}),
                  },
                  webhookMut.mutateAsync, setWebhookSaved, setWebhookError, setWebhookDirty,
                )}
                disabled={webhookMut.isPending}
                aria-busy={webhookMut.isPending}
                aria-label="Save Webhook settings">
                {webhookMut.isPending ? 'Saving…' : 'Save'}
              </Button>
              <StatusMessage saving={webhookMut.isPending} saved={webhookSaved} error={webhookError} />
            </div>
          </CardContent>
        </Card>
      </section>

      {/* ── Backup & Restore ── */}
      <section aria-labelledby="backup-heading" className="mb-6">
        <BackupRestoreCard />
      </section>
    </main>
  );
}

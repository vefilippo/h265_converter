import { useState } from "react";
import { api, ApiError } from "../api/client";
import { updateSettings, detectEncoders } from "../api/client";
import { Button } from "../components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "../components/ui/card";
import { Input } from "../components/ui/input";
import type { EncoderFamily } from "../api/types";

interface SetupProps {
  onDone: () => void;
}

type Step = "password" | "connections" | "handbrake" | "done";

export default function Setup({ onDone }: SetupProps) {
  const [step, setStep] = useState<Step>("password");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // connection fields
  const [sonarrUrl, setSonarrUrl] = useState("");
  const [sonarrKey, setSonarrKey] = useState("");
  const [radarrUrl, setRadarrUrl] = useState("");
  const [radarrKey, setRadarrKey] = useState("");
  const [sftpHost, setSftpHost] = useState("");
  const [sftpUser, setSftpUser] = useState("");
  const [sftpPass, setSftpPass] = useState("");
  const [handbrake, setHandbrake] = useState("");
  const [encFamily, setEncFamily] = useState<EncoderFamily["id"]>("auto");
  const [familyChosen, setFamilyChosen] = useState(false);
  const [encFound, setEncFound] = useState<string | null>(null);
  const [encError, setEncError] = useState<string | null>(null);
  const [detecting, setDetecting] = useState(false);

  async function createPassword(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await api.post("/api/setup/password", { password });
      setStep("connections");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not set password");
    } finally {
      setBusy(false);
    }
  }

  async function saveConnections() {
    setBusy(true);
    try {
      await updateSettings({
        sonarr_url: sonarrUrl, sonarr_api_key: sonarrKey,
        radarr_url: radarrUrl, radarr_api_key: radarrKey,
        sftp_host: sftpHost, sftp_username: sftpUser, sftp_password: sftpPass,
      });
    } finally {
      setBusy(false);
      setStep("handbrake");
    }
  }

  async function detect() {
    setDetecting(true);
    setEncError(null);
    setEncFound(null);
    try {
      const res = await detectEncoders(handbrake);
      if (!res.ok) {
        setEncError(res.error ?? "Detection failed");
        return;
      }
      // Hardware before software, matching the backend's auto priority.
      const best = res.families.find(f => f.available && f.hardware);
      setEncFamily(best ? best.id : "cpu");
      setFamilyChosen(true);
      setEncFound(best
        ? `Found ${best.label} — using hardware H.265 encoding.`
        : "No hardware encoder found — using CPU x265.");
    } catch {
      setEncError("Detection failed");
    } finally {
      setDetecting(false);
    }
  }

  async function saveHandbrake() {
    setBusy(true);
    try {
      const payload: Parameters<typeof updateSettings>[0] = { handbrake_cli: handbrake };
      // Only send encoder_family when the user actually established one (via
      // Detect); otherwise this would pre-empt the backend's
      // migrate_encoder_family, which honours ENCODER_FAMILY from .env.
      if (familyChosen) payload.encoder_family = encFamily;
      await updateSettings(payload);
    } finally {
      setBusy(false);
      setStep("done");
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-bg">
      <Card className="w-full max-w-md">
        <CardHeader>
          <CardTitle>Set up H.265 Transcoder</CardTitle>
        </CardHeader>
        <CardContent>
          {step === "password" && (
            <form onSubmit={createPassword} className="flex flex-col gap-4">
              <p className="text-sm text-muted">Choose a password for the dashboard.</p>
              <div className="flex flex-col gap-1.5">
                <label htmlFor="setup-password" className="text-sm text-muted">Password</label>
                <Input id="setup-password" type="password" value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  autoComplete="new-password" required />
              </div>
              {error && <p className="text-sm text-state-failed">{error}</p>}
              <Button type="submit" disabled={busy || !password.trim()}>
                {busy ? "Saving…" : "Create password"}
              </Button>
            </form>
          )}

          {step === "connections" && (
            <div className="flex flex-col gap-4">
              <p className="text-sm text-muted">Connect your media managers and SFTP (optional — configure later in Settings).</p>
              <fieldset className="flex flex-col gap-2">
                <legend className="text-sm font-medium">Sonarr</legend>
                <Input placeholder="Sonarr URL" value={sonarrUrl} onChange={(e) => setSonarrUrl(e.target.value)} />
                <Input placeholder="Sonarr API key" value={sonarrKey} onChange={(e) => setSonarrKey(e.target.value)} />
              </fieldset>
              <fieldset className="flex flex-col gap-2">
                <legend className="text-sm font-medium">Radarr</legend>
                <Input placeholder="Radarr URL" value={radarrUrl} onChange={(e) => setRadarrUrl(e.target.value)} />
                <Input placeholder="Radarr API key" value={radarrKey} onChange={(e) => setRadarrKey(e.target.value)} />
              </fieldset>
              <fieldset className="flex flex-col gap-2">
                <legend className="text-sm font-medium">SFTP</legend>
                <Input placeholder="SFTP host" value={sftpHost} onChange={(e) => setSftpHost(e.target.value)} />
                <Input placeholder="SFTP username" value={sftpUser} onChange={(e) => setSftpUser(e.target.value)} />
                <Input placeholder="SFTP password" type="password" value={sftpPass} onChange={(e) => setSftpPass(e.target.value)} />
              </fieldset>
              <div className="flex gap-2">
                <Button variant="outline" onClick={() => setStep("handbrake")} disabled={busy}>Skip</Button>
                <Button onClick={saveConnections} disabled={busy}>Save & continue</Button>
              </div>
            </div>
          )}

          {step === "handbrake" && (
            <div className="flex flex-col gap-4">
              <p className="text-sm text-muted">Path to HandBrakeCLI.exe (optional).</p>
              <Input placeholder="C:\path\to\HandBrakeCLI.exe" value={handbrake}
                onChange={(e) => setHandbrake(e.target.value)} />
              <div className="flex items-center gap-2">
                <Button variant="outline" onClick={detect} disabled={detecting}
                  aria-busy={detecting}>
                  {detecting ? "Detecting…" : "Detect"}
                </Button>
                {encFound && <span className="text-xs text-muted">{encFound}</span>}
                {encError && <span className="text-xs text-state-failed">{encError}</span>}
              </div>
              <div className="flex gap-2">
                <Button variant="outline" onClick={() => setStep("done")} disabled={busy}>Skip</Button>
                <Button onClick={saveHandbrake} disabled={busy || detecting}>Save & continue</Button>
              </div>
            </div>
          )}

          {step === "done" && (
            <div className="flex flex-col gap-4">
              <p className="text-sm text-muted">You're all set.</p>
              <Button onClick={onDone}>Finish — go to dashboard</Button>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

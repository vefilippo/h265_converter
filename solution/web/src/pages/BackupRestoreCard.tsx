import { useState } from 'react';
import { Card, CardContent, CardHeader } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { downloadBackup, restoreBackup } from '../api/client';

export default function BackupRestoreCard() {
  const [backupPass, setBackupPass] = useState('');
  const [restorePass, setRestorePass] = useState('');
  const [file, setFile] = useState<File | null>(null);
  const [status, setStatus] = useState('');

  async function onDownload() {
    setStatus('');
    try {
      const blob = await downloadBackup(backupPass);
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      const stamp = new Date().toISOString().slice(0, 10).replace(/-/g, '');
      a.href = url;
      a.download = `h265-backup-${stamp}.zip`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      setStatus(`Backup failed: ${(e as Error).message}`);
    }
  }

  async function onRestore() {
    if (!file) { setStatus('Choose a backup file first.'); return; }
    setStatus('Uploading…');
    try {
      await restoreBackup(file, restorePass);
      setStatus('Restarting… reconnecting');
      for (let i = 0; i < 120; i++) {
        await new Promise((r) => setTimeout(r, 1000));
        try {
          const res = await fetch('/api/health');
          if (res.ok) { location.reload(); return; }
        } catch { /* server still down */ }
      }
      setStatus('Restore applied, but the server did not come back — check the service.');
    } catch (e) {
      setStatus(`Restore failed: ${(e as Error).message}`);
    }
  }

  return (
    <Card>
      <CardHeader className="flex flex-row items-center gap-2 border-b border-border">
        <h2 className="font-display text-lg text-fg">Backup &amp; Restore</h2>
      </CardHeader>
      <CardContent className="space-y-4 pt-5">
        <div className="space-y-2">
          <label htmlFor="backup-pass" className="block text-xs font-medium text-muted">
            Backup passphrase (encrypts your credentials)
          </label>
          <Input
            id="backup-pass"
            type="password"
            value={backupPass}
            onChange={(e) => setBackupPass(e.target.value)}
          />
          <Button onClick={onDownload} disabled={!backupPass}>Download backup</Button>
        </div>
        <div className="space-y-2 border-t pt-4">
          <p className="text-xs text-red-500">
            ⚠ Restore replaces all data on this instance (database + credentials) and restarts it.
          </p>
          <input
            aria-label="backup file"
            type="file"
            accept=".zip"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          />
          <label htmlFor="restore-pass" className="block text-xs font-medium text-muted">
            Passphrase
          </label>
          <Input
            id="restore-pass"
            type="password"
            value={restorePass}
            onChange={(e) => setRestorePass(e.target.value)}
          />
          <Button onClick={onRestore} disabled={!file || !restorePass}>Restore</Button>
        </div>
        {status && <p className="text-sm text-muted">{status}</p>}
      </CardContent>
    </Card>
  );
}

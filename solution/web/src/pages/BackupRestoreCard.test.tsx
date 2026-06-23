// solution/web/src/pages/BackupRestoreCard.test.tsx
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import BackupRestoreCard from './BackupRestoreCard';
import * as client from '../api/client';

it('downloads a backup with the entered passphrase', async () => {
  const spy = vi.spyOn(client, 'downloadBackup').mockResolvedValue(new Blob(['z']));
  // jsdom lacks object-URL APIs
  (URL as unknown as { createObjectURL: () => string }).createObjectURL = () => 'blob:x';
  (URL as unknown as { revokeObjectURL: () => void }).revokeObjectURL = () => {};
  render(<BackupRestoreCard />);
  fireEvent.change(screen.getByLabelText(/backup passphrase/i), { target: { value: 'pw' } });
  fireEvent.click(screen.getByRole('button', { name: /download backup/i }));
  await waitFor(() => expect(spy).toHaveBeenCalledWith('pw'));
});

it('warns about data loss near restore', () => {
  render(<BackupRestoreCard />);
  expect(screen.getByText(/replaces all data/i)).toBeInTheDocument();
});

it('restore calls restoreBackup with the chosen file and passphrase', async () => {
  const spy = vi.spyOn(client, 'restoreBackup').mockResolvedValue(undefined);
  // Make the post-restore health poll + reload harmless during the test.
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true }));
  const reload = vi.fn();
  Object.defineProperty(window, 'location', {
    value: { ...window.location, reload }, writable: true,
  });
  render(<BackupRestoreCard />);
  const file = new File(['z'], 'backup.zip');
  fireEvent.change(screen.getByLabelText(/backup file/i), { target: { files: [file] } });
  fireEvent.change(screen.getByLabelText('Passphrase'), { target: { value: 'pw' } });
  fireEvent.click(screen.getByRole('button', { name: /^restore$/i }));
  await waitFor(() => expect(spy).toHaveBeenCalledWith(file, 'pw'));
  vi.unstubAllGlobals();
});

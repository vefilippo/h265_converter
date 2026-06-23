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

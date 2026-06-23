import { afterEach, expect, test, vi } from "vitest";
import { api, ApiError, downloadBackup, restoreBackup } from "./client";

afterEach(() => vi.restoreAllMocks());

test("GET returns parsed json", async () => {
  vi.stubGlobal("fetch", vi.fn(async () =>
    new Response(JSON.stringify({ total: 0, items: [] }), { status: 200 })
  ));
  const data = await api.get<{ total: number }>("/api/jobs");
  expect(data.total).toBe(0);
});

test("non-2xx throws ApiError with status", async () => {
  vi.stubGlobal("fetch", vi.fn(async () =>
    new Response(JSON.stringify({ detail: "nope" }), { status: 401 })
  ));
  await expect(api.get("/api/library")).rejects.toMatchObject({ status: 401 });
  expect(ApiError).toBeTruthy();
});

test("204 returns undefined", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => new Response(null, { status: 204 })));
  const r = await api.del("/api/exclusions/1");
  expect(r).toBeUndefined();
});

describe('backup/restore', () => {
  it('downloadBackup POSTs passphrase and returns a blob', async () => {
    const blob = new Blob(['zip']);
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, status: 200, blob: () => Promise.resolve(blob) });
    vi.stubGlobal('fetch', fetchMock);
    const out = await downloadBackup('pw');
    expect(out).toBe(blob);
    const [url, opts] = fetchMock.mock.calls[0];
    expect(url).toBe('/api/backup');
    expect(opts.method).toBe('POST');
    expect(JSON.parse(opts.body)).toEqual({ passphrase: 'pw' });
    vi.unstubAllGlobals();
  });

  it('restoreBackup POSTs multipart file + passphrase', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, status: 202 });
    vi.stubGlobal('fetch', fetchMock);
    await restoreBackup(new File(['z'], 'b.zip'), 'pw');
    const [url, opts] = fetchMock.mock.calls[0];
    expect(url).toBe('/api/restore');
    expect(opts.method).toBe('POST');
    expect(opts.body).toBeInstanceOf(FormData);
    vi.unstubAllGlobals();
  });
});

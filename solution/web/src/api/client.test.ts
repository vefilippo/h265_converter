import { afterEach, expect, test, vi } from "vitest";
import { api, ApiError } from "./client";

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

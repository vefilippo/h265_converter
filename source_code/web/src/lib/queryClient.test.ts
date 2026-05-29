import { expect, test, vi } from "vitest";
import { ApiError } from "../api/client";
import { createQueryClient } from "./queryClient";

test("a 401 query error invalidates the me query (routes back to login)", async () => {
  const qc = createQueryClient();
  const spy = vi.spyOn(qc, "invalidateQueries");
  await qc
    .fetchQuery({
      queryKey: ["library"],
      queryFn: async () => {
        throw new ApiError(401, "authentication required");
      },
      retry: false,
    })
    .catch(() => undefined);
  expect(spy).toHaveBeenCalledWith({ queryKey: ["me"] });
});

test("a non-401 error does NOT invalidate me", async () => {
  const qc = createQueryClient();
  const spy = vi.spyOn(qc, "invalidateQueries");
  await qc
    .fetchQuery({
      queryKey: ["library"],
      queryFn: async () => {
        throw new ApiError(500, "boom");
      },
      retry: false,
    })
    .catch(() => undefined);
  expect(spy).not.toHaveBeenCalled();
});

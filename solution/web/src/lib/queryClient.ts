import { MutationCache, QueryCache, QueryClient } from "@tanstack/react-query";
import { ApiError } from "../api/client";

/**
 * QueryClient with a global 401 handler: any query/mutation that fails with an
 * ApiError(401) invalidates the ["me"] query, so AuthGate re-renders the Login
 * view when the session has expired (spec: a 401 routes the user back to login).
 */
export function createQueryClient(): QueryClient {
  const onError = (err: unknown) => {
    if (err instanceof ApiError && err.status === 401) {
      client.invalidateQueries({ queryKey: ["me"] });
    }
  };
  const client = new QueryClient({
    queryCache: new QueryCache({ onError }),
    mutationCache: new MutationCache({ onError }),
  });
  return client;
}

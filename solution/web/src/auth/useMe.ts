import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";

export function useMe() {
  return useQuery({
    queryKey: ["me"],
    queryFn: () => api.get<{ authed: boolean }>("/api/me"),
    retry: false,
  });
}

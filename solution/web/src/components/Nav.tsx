import { useQueryClient } from "@tanstack/react-query";
import { NavLink } from "react-router-dom";
import { api } from "../api/client";
import { Button } from "./ui/button";
import { useStatus } from "../hooks/queries";
import { VersionBadge } from "./VersionBadge";

const navLinks = [
  { to: "/", label: "Dashboard" },
  { to: "/library", label: "Library" },
  { to: "/jobs", label: "Jobs" },
  { to: "/exclusions", label: "Exclusions" },
  { to: "/logs", label: "Logs" },
  { to: "/settings", label: "Settings" },
];

export function Nav() {
  const queryClient = useQueryClient();
  const { data: status } = useStatus();

  async function handleLogout() {
    try {
      await api.post("/api/logout");
    } catch {
      // ignore errors
    }
    queryClient.invalidateQueries({ queryKey: ["me"] });
  }

  return (
    <nav className="flex flex-col h-screen w-56 bg-surface border-r border-border shrink-0">
      <div className="px-4 py-5 border-b border-border">
        <span className="font-display text-lg text-fg">H.265 Transcoder</span>
      </div>

      <ul className="flex-1 flex flex-col gap-1 p-2 mt-1">
        {navLinks.map(({ to, label }) => (
          <li key={to}>
            <NavLink
              to={to}
              end={to === "/"}
              className={({ isActive }) =>
                [
                  "flex items-center px-3 py-2 rounded-md text-sm transition-colors",
                  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/50",
                  isActive
                    ? "bg-elevated text-accent font-medium"
                    : "text-muted hover:bg-elevated hover:text-fg",
                ].join(" ")
              }
            >
              {label}
            </NavLink>
          </li>
        ))}
      </ul>

      {status !== undefined && (
        <div className="px-4 py-2 border-t border-border flex items-center gap-2">
          <span
            className={`inline-block h-2 w-2 rounded-full ${status.worker_alive ? "bg-accent" : "bg-muted"}`}
            aria-hidden="true"
          />
          <span className="text-xs text-muted">
            Worker {status.worker_alive ? "online" : "offline"}
          </span>
        </div>
      )}

      <div className="px-4 py-2 border-t border-border">
        <VersionBadge />
      </div>

      <div className="p-3 border-t border-border">
        <Button
          variant="ghost"
          size="sm"
          className="w-full justify-start text-muted hover:text-fg"
          onClick={handleLogout}
        >
          Logout
        </Button>
      </div>
    </nav>
  );
}

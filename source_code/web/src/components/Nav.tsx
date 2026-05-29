import { useQueryClient } from "@tanstack/react-query";
import { NavLink } from "react-router-dom";
import { api } from "../api/client";
import { Button } from "./ui/button";

const navLinks = [
  { to: "/", label: "Dashboard" },
  { to: "/library", label: "Library" },
  { to: "/jobs", label: "Jobs" },
  { to: "/exclusions", label: "Exclusions" },
];

export function Nav() {
  const queryClient = useQueryClient();

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
                  isActive
                    ? "bg-surface text-accent font-medium"
                    : "text-muted hover:bg-elevated hover:text-fg",
                ].join(" ")
              }
            >
              {label}
            </NavLink>
          </li>
        ))}
      </ul>

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

import { useEffect, useRef } from "react";
import { Route, Routes, useLocation } from "react-router-dom";
import { AuthGate } from "./auth/AuthGate";
import { Nav } from "./components/Nav";
import Dashboard from "./pages/Dashboard";
import Exclusions from "./pages/Exclusions";
import Jobs from "./pages/Jobs";
import Library from "./pages/Library";
import Logs from "./pages/Logs";
import Settings from "./pages/Settings";

export default function App() {
  const mainRef = useRef<HTMLElement>(null);
  const location = useLocation();

  useEffect(() => {
    mainRef.current?.focus();
  }, [location.pathname]);

  return (
    <AuthGate>
      <a
        href="#main-content"
        className="sr-only focus:not-sr-only focus:fixed focus:top-2 focus:left-2 focus:z-[100] focus:rounded focus:bg-accent focus:px-4 focus:py-2 focus:text-sm focus:font-medium focus:text-bg"
      >
        Skip to content
      </a>
      <div className="flex h-screen bg-bg text-fg overflow-hidden">
        <Nav />
        <main
          id="main-content"
          ref={mainRef}
          tabIndex={-1}
          className="flex-1 overflow-y-auto p-6 outline-none"
        >
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/library" element={<Library />} />
            <Route path="/jobs" element={<Jobs />} />
            <Route path="/exclusions" element={<Exclusions />} />
            <Route path="/logs" element={<Logs />} />
            <Route path="/settings" element={<Settings />} />
          </Routes>
        </main>
      </div>
    </AuthGate>
  );
}

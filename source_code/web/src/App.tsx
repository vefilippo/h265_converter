import { Route, Routes } from "react-router-dom";
import { AuthGate } from "./auth/AuthGate";
import { Nav } from "./components/Nav";
import Dashboard from "./pages/Dashboard";
import Exclusions from "./pages/Exclusions";
import Jobs from "./pages/Jobs";
import Library from "./pages/Library";
import Logs from "./pages/Logs";
import Settings from "./pages/Settings";

export default function App() {
  return (
    <AuthGate>
      <div className="flex h-screen bg-bg text-fg overflow-hidden">
        <Nav />
        <main className="flex-1 overflow-y-auto p-6">
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

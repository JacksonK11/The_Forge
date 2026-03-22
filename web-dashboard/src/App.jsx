import { BrowserRouter, Route, Routes, Link, useLocation } from "react-router-dom";
import Home from "./pages/Home.jsx";
import RunStatus from "./pages/RunStatus.jsx";
import History from "./pages/History.jsx";

function Nav() {
  const location = useLocation();
  const navLink = (to, label) => (
    <Link
      to={to}
      className={`px-4 py-2 text-sm rounded transition-colors ${
        location.pathname === to
          ? "bg-forge-accent text-white"
          : "text-gray-400 hover:text-white hover:bg-forge-700"
      }`}
    >
      {label}
    </Link>
  );

  return (
    <nav className="border-b border-forge-600 bg-forge-800 px-6 py-3 flex items-center gap-6">
      <Link to="/" className="text-white font-bold text-lg tracking-tight mr-4">
        🔨 The Forge
      </Link>
      {navLink("/", "New Build")}
      {navLink("/history", "History")}
    </nav>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <div className="min-h-screen bg-forge-900">
        <Nav />
        <main className="max-w-5xl mx-auto px-6 py-8">
          <Routes>
            <Route path="/" element={<Home />} />
            <Route path="/runs/:runId" element={<RunStatus />} />
            <Route path="/history" element={<History />} />
          </Routes>
        </main>
      </div>
    </BrowserRouter>
  );
}

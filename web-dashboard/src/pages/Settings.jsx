import { useState, useEffect } from "react";
import { getForgeConfig, getSettings, saveSettings } from "../api.js";
import { useToast } from "../context/ToastContext.jsx";

export default function Settings() {
  const { addToast } = useToast();
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState({
    push_to_github: true,
    default_region: "syd",
    notification_email: "",
    telegram_chat_id: "",
    auto_approve_low_risk: false,
    max_parallel_builds: 2,
  });
  const [config, setConfig] = useState(null);

  useEffect(() => {
    async function load() {
      const [settingsRes, configRes] = await Promise.allSettled([getSettings(), getForgeConfig()]);
      if (settingsRes.status === "fulfilled" && settingsRes.value) {
        setForm((prev) => ({ ...prev, ...settingsRes.value }));
      }
      if (configRes.status === "fulfilled") setConfig(configRes.value);
      setLoading(false);
    }
    load();
  }, []);

  async function handleSave(e) {
    e.preventDefault();
    setSaving(true);
    try {
      // Backend stores all values as strings — convert booleans and numbers
      const payload = {
        push_to_github: String(form.push_to_github),
        default_region: form.default_region,
        auto_approve_low_risk: String(form.auto_approve_low_risk),
        max_parallel_builds: String(form.max_parallel_builds),
        notification_email: form.notification_email || "",
        telegram_chat_id: form.telegram_chat_id || "",
      };
      await saveSettings(payload);
      addToast("Settings saved.", "success");
    } catch (err) {
      addToast(err.message || "Failed to save settings.", "error");
    } finally {
      setSaving(false);
    }
  }

  function set(key, value) { setForm((prev) => ({ ...prev, [key]: value })); }

  return (
    <>
      <div className="sec-title">Settings</div>
      <div className="sec-sub">Configuration, secrets status, and system integrations</div>

      <div className="g2" style={{ gridTemplateColumns: "1.6fr 1fr" }}>
        <form onSubmit={handleSave}>
          <div className="ddd-card">
            <div className="card-title">Build Settings</div>

            <div className="form-row stat-row" style={{ paddingTop: 12 }}>
              <div>
                <div style={{ fontSize: 12, fontWeight: 600, color: "var(--t1)" }}>Push to GitHub</div>
                <div style={{ fontFamily: "var(--fm)", fontSize: 10, color: "var(--t3)" }}>Auto-push generated code to GitHub after build</div>
              </div>
              <label style={{ display: "flex", alignItems: "center", cursor: "pointer" }}>
                <input type="checkbox" checked={form.push_to_github} onChange={(e) => set("push_to_github", e.target.checked)} style={{ accentColor: "var(--p)", width: 16, height: 16 }} />
              </label>
            </div>

            <div className="form-row stat-row">
              <div>
                <div style={{ fontSize: 12, fontWeight: 600, color: "var(--t1)" }}>Auto-Approve Low Risk</div>
                <div style={{ fontFamily: "var(--fm)", fontSize: 10, color: "var(--t3)" }}>Skip manual approval for simple builds</div>
              </div>
              <label style={{ display: "flex", alignItems: "center", cursor: "pointer" }}>
                <input type="checkbox" checked={form.auto_approve_low_risk} onChange={(e) => set("auto_approve_low_risk", e.target.checked)} style={{ accentColor: "var(--p)", width: 16, height: 16 }} />
              </label>
            </div>

            <div className="form-row">
              <label className="ddd-lbl">Default Fly.io Region</label>
              <select
                className="ddd-input"
                value={form.default_region}
                onChange={(e) => set("default_region", e.target.value)}
                style={{ cursor: "pointer" }}
              >
                {["syd", "lhr", "iad", "sjc", "fra", "nrt", "sin"].map((r) => (
                  <option key={r} value={r} style={{ background: "var(--bg4)", color: "var(--t1)" }}>{r.toUpperCase()}</option>
                ))}
              </select>
            </div>

            <div className="form-row">
              <label className="ddd-lbl">Max Parallel Builds</label>
              <input
                className="ddd-input"
                type="number"
                min={1} max={8}
                value={form.max_parallel_builds}
                onChange={(e) => set("max_parallel_builds", parseInt(e.target.value, 10))}
              />
            </div>

            <div className="ddd-div" />

            <div className="card-title">Notification Settings</div>

            <div className="form-row">
              <label className="ddd-lbl">Notification Email</label>
              <input
                className="ddd-input"
                type="email"
                value={form.notification_email}
                onChange={(e) => set("notification_email", e.target.value)}
                placeholder="jackson@example.com"
              />
            </div>

            <div className="form-row">
              <label className="ddd-lbl">Telegram Chat ID</label>
              <input
                className="ddd-input"
                type="text"
                value={form.telegram_chat_id}
                onChange={(e) => set("telegram_chat_id", e.target.value)}
                placeholder="Your personal Telegram Chat ID"
              />
            </div>

            <button
              type="submit"
              disabled={saving || loading}
              className="ddd-btn btn-purple"
              style={{ marginTop: 8, padding: "10px 24px" }}
            >
              {saving ? "SAVING..." : "SAVE SETTINGS"}
            </button>
          </div>
        </form>

        {/* ── Secrets status ── */}
        <div className="gcol">
          <div className="ddd-card">
            <div className="card-title">Secrets Status</div>
            {config ? (
              Object.entries(config).map(([key, present]) => (
                <div key={key} className="int-badge" style={{ marginBottom: 8 }}>
                  <div className={`int-dot ${present ? "on" : "off"}`} />
                  <div className="int-body">
                    <div className="int-name">{key}</div>
                    <div className={`int-status ${present ? "on" : "off"}`}>
                      {present ? "SET" : "MISSING"}
                    </div>
                  </div>
                </div>
              ))
            ) : (
              <div style={{ fontFamily: "var(--fm)", fontSize: 10, color: "var(--t3)", padding: "12px 0" }}>
                {loading ? "Loading..." : "Config unavailable"}
              </div>
            )}
          </div>

          <div className="ddd-card">
            <div className="card-title">Deployment Targets</div>
            {[
              ["the-forge-api",       "API",       "on"],
              ["the-forge-worker",    "Worker",    "on"],
              ["the-forge-dashboard1","Dashboard", "on"],
            ].map(([app, label, status]) => (
              <div key={app} className="int-badge" style={{ marginBottom: 8 }}>
                <div className="int-icon" style={{ background: "var(--p-d)", fontSize: 14 }}>🚀</div>
                <div className="int-body">
                  <div className="int-name">{label}</div>
                  <div style={{ fontFamily: "var(--fm)", fontSize: 10, color: "var(--t3)" }}>{app}.fly.dev</div>
                </div>
                <div className={`int-dot ${status}`} />
              </div>
            ))}
          </div>
        </div>
      </div>
    </>
  );
}

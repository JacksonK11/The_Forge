import { useState, useEffect } from "react";
import { getForgeConfig, getSettings, saveSettings } from "../api.js";
import { useToast } from "../context/ToastContext.jsx";

function SettingRow({ label, description, children }) {
  return (
    <div className="flex items-start justify-between gap-6 py-4 border-b border-gray-800 last:border-0">
      <div className="flex-1 min-w-0">
        <p className="text-sm font-medium text-white">{label}</p>
        {description && <p className="text-xs text-gray-500 mt-0.5">{description}</p>}
      </div>
      <div className="flex-shrink-0">{children}</div>
    </div>
  );
}

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
    async function fetchData() {
      try {
        const [settingsData, configData] = await Promise.allSettled([getSettings(), getForgeConfig()]);
        if (settingsData.status === "fulfilled" && settingsData.value) {
          const s = settingsData.value;
          setForm((prev) => ({
            ...prev,
            push_to_github: s.push_to_github ?? prev.push_to_github,
            default_region: s.default_region ?? prev.default_region,
            notification_email: s.notification_email ?? prev.notification_email,
            telegram_chat_id: s.telegram_chat_id ?? prev.telegram_chat_id,
            auto_approve_low_risk: s.auto_approve_low_risk ?? prev.auto_approve_low_risk,
            max_parallel_builds: s.max_parallel_builds ?? prev.max_parallel_builds,
          }));
        }
        if (configData.status === "fulfilled") {
          setConfig(configData.value);
        }
      } catch {
        // show empty form
      } finally {
        setLoading(false);
      }
    }
    fetchData();
  }, []);

  function set(key, value) {
    setForm((prev) => ({ ...prev, [key]: value }));
  }

  async function handleSave() {
    setSaving(true);
    try {
      await saveSettings(form);
      addToast("Settings saved.", "success");
    } catch (err) {
      addToast(err.message || "Failed to save settings.", "error");
    } finally {
      setSaving(false);
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center p-12">
        <div className="w-6 h-6 border-2 border-purple-500 border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  return (
    <div className="p-6 max-w-2xl mx-auto">
      <div className="mb-6">
        <h1 className="font-['Bebas_Neue'] text-3xl text-white tracking-widest">Settings</h1>
        <p className="text-gray-500 text-sm mt-1">Configure The Forge build engine defaults.</p>
      </div>

      <div className="space-y-4">
        {/* Build defaults */}
        <div className="rounded-xl border border-gray-800 bg-gray-900 p-6">
          <h2 className="font-['Bebas_Neue'] text-lg text-purple-400 tracking-widest mb-1">
            Build Defaults
          </h2>
          <div>
            <SettingRow
              label="Push to GitHub"
              description="Automatically push generated code to a new GitHub repository."
            >
              <button
                onClick={() => set("push_to_github", !form.push_to_github)}
                className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
                  form.push_to_github ? "bg-purple-600" : "bg-gray-700"
                }`}
              >
                <span
                  className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                    form.push_to_github ? "translate-x-6" : "translate-x-1"
                  }`}
                />
              </button>
            </SettingRow>

            <SettingRow
              label="Default Region"
              description="Fly.io deployment region for generated agents."
            >
              <select
                value={form.default_region}
                onChange={(e) => set("default_region", e.target.value)}
                className="bg-gray-800 border border-gray-700 rounded-lg px-3 py-1.5 text-sm text-gray-200 focus:outline-none focus:border-purple-500"
              >
                <option value="syd">Sydney (syd)</option>
                <option value="lhr">London (lhr)</option>
                <option value="iad">Ashburn (iad)</option>
                <option value="sin">Singapore (sin)</option>
              </select>
            </SettingRow>

            <SettingRow
              label="Max Parallel Builds"
              description="Maximum number of builds running simultaneously."
            >
              <input
                type="number"
                min={1}
                max={10}
                value={form.max_parallel_builds}
                onChange={(e) => set("max_parallel_builds", Number(e.target.value))}
                className="w-20 bg-gray-800 border border-gray-700 rounded-lg px-3 py-1.5 text-sm text-gray-200 text-center focus:outline-none focus:border-purple-500"
              />
            </SettingRow>

            <SettingRow
              label="Auto-approve Low Risk"
              description="Skip manual approval for builds flagged as low risk."
            >
              <button
                onClick={() => set("auto_approve_low_risk", !form.auto_approve_low_risk)}
                className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
                  form.auto_approve_low_risk ? "bg-purple-600" : "bg-gray-700"
                }`}
              >
                <span
                  className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                    form.auto_approve_low_risk ? "translate-x-6" : "translate-x-1"
                  }`}
                />
              </button>
            </SettingRow>
          </div>
        </div>

        {/* Notifications */}
        <div className="rounded-xl border border-gray-800 bg-gray-900 p-6">
          <h2 className="font-['Bebas_Neue'] text-lg text-purple-400 tracking-widest mb-1">
            Notifications
          </h2>
          <div>
            <SettingRow label="Notification Email" description="Receive build completion emails.">
              <input
                type="email"
                value={form.notification_email}
                onChange={(e) => set("notification_email", e.target.value)}
                placeholder="you@example.com"
                className="bg-gray-800 border border-gray-700 rounded-lg px-3 py-1.5 text-sm text-gray-200 placeholder-gray-600 focus:outline-none focus:border-purple-500 w-52"
              />
            </SettingRow>

            <SettingRow label="Telegram Chat ID" description="Send alerts to your Telegram account.">
              <input
                type="text"
                value={form.telegram_chat_id}
                onChange={(e) => set("telegram_chat_id", e.target.value)}
                placeholder="123456789"
                className="bg-gray-800 border border-gray-700 rounded-lg px-3 py-1.5 text-sm text-gray-200 placeholder-gray-600 focus:outline-none focus:border-purple-500 w-36"
              />
            </SettingRow>
          </div>
        </div>

        {/* System config */}
        {config && (
          <div className="rounded-xl border border-gray-800 bg-gray-900 p-6">
            <h2 className="font-['Bebas_Neue'] text-lg text-purple-400 tracking-widest mb-3">
              System Config
            </h2>
            <pre className="font-['IBM_Plex_Mono'] text-xs text-gray-500 overflow-x-auto whitespace-pre-wrap">
              {JSON.stringify(config, null, 2)}
            </pre>
          </div>
        )}

        <button
          onClick={handleSave}
          disabled={saving}
          className="w-full rounded-lg font-medium px-4 py-2.5 transition-all duration-200 bg-purple-600 hover:bg-purple-500 disabled:opacity-50 text-white text-sm flex items-center justify-center gap-2"
        >
          {saving ? (
            <>
              <div className="w-4 h-4 border-2 border-white/40 border-t-white rounded-full animate-spin" />
              Saving...
            </>
          ) : (
            "Save Settings"
          )}
        </button>
      </div>
    </div>
  );
}

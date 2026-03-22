import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import {
  submitBlueprint,
  submitBlueprintFile,
  listTemplates,
  getTemplate,
} from "../api/client.js";

const STAGES = {
  queued: { label: "Queued", color: "text-gray-400" },
  validating: { label: "Validating", color: "text-blue-400" },
  parsing: { label: "Parsing Blueprint", color: "text-blue-400" },
  confirming: { label: "Awaiting Approval", color: "text-yellow-400" },
  architecting: { label: "Mapping Architecture", color: "text-purple-400" },
  generating: { label: "Generating Code", color: "text-forge-accent" },
  packaging: { label: "Packaging", color: "text-teal-400" },
  complete: { label: "Complete", color: "text-green-400" },
  failed: { label: "Failed", color: "text-red-400" },
};

export default function Home() {
  const navigate = useNavigate();
  const [title, setTitle] = useState("");
  const [blueprintText, setBlueprintText] = useState("");
  const [file, setFile] = useState(null);
  const [inputMode, setInputMode] = useState("text"); // "text" | "file"
  const [templates, setTemplates] = useState([]);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    listTemplates()
      .then(setTemplates)
      .catch((err) => console.warn("Templates unavailable:", err));
  }, []);

  async function handleLoadTemplate(templateId) {
    try {
      const t = await getTemplate(templateId);
      setTitle(t.name);
      setBlueprintText(t.blueprint_text);
      setInputMode("text");
    } catch (err) {
      setError(`Could not load template: ${err.message}`);
    }
  }

  async function handleSubmit(e) {
    e.preventDefault();
    setError(null);
    if (!title.trim()) {
      setError("Agent name is required.");
      return;
    }
    if (inputMode === "text" && blueprintText.trim().length < 50) {
      setError("Blueprint must be at least 50 characters.");
      return;
    }
    if (inputMode === "file" && !file) {
      setError("Please select a .docx or .pdf file.");
      return;
    }

    setSubmitting(true);
    try {
      let result;
      if (inputMode === "file") {
        result = await submitBlueprintFile(title.trim(), file);
      } else {
        result = await submitBlueprint(title.trim(), blueprintText.trim());
      }
      navigate(`/runs/${result.run_id}`);
    } catch (err) {
      setError(`Submission failed: ${err.message}`);
      setSubmitting(false);
    }
  }

  return (
    <div className="space-y-8">
      {/* Header */}
      <div>
        <h1 className="text-3xl font-bold text-white mb-2">New Build</h1>
        <p className="text-gray-400 text-sm">
          Upload a blueprint document → get a complete deployable codebase in 15–25 minutes.
        </p>
      </div>

      {/* Template library */}
      {templates.length > 0 && (
        <div>
          <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wider mb-3">
            Start from a Template
          </h2>
          <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
            {templates.map((t) => (
              <button
                key={t.id}
                onClick={() => handleLoadTemplate(t.id)}
                className="text-left p-3 rounded-lg border border-forge-600 bg-forge-800 hover:border-forge-accent hover:bg-forge-700 transition-all"
              >
                <div className="text-white text-sm font-medium">{t.name}</div>
                <div className="text-gray-400 text-xs mt-1 line-clamp-2">
                  {t.description}
                </div>
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Submit form */}
      <form onSubmit={handleSubmit} className="space-y-5">
        <div>
          <label className="block text-sm text-gray-400 mb-1">
            Agent Name <span className="text-red-400">*</span>
          </label>
          <input
            type="text"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="e.g. BuildRight AI Agent"
            className="w-full bg-forge-800 border border-forge-600 rounded-lg px-4 py-2.5 text-white placeholder-gray-500 focus:outline-none focus:border-forge-accent text-sm"
            required
          />
        </div>

        {/* Input mode toggle */}
        <div className="flex gap-2">
          <button
            type="button"
            onClick={() => setInputMode("text")}
            className={`px-4 py-2 text-sm rounded transition-colors ${
              inputMode === "text"
                ? "bg-forge-accent text-white"
                : "bg-forge-700 text-gray-400 hover:text-white"
            }`}
          >
            Paste Text
          </button>
          <button
            type="button"
            onClick={() => setInputMode("file")}
            className={`px-4 py-2 text-sm rounded transition-colors ${
              inputMode === "file"
                ? "bg-forge-accent text-white"
                : "bg-forge-700 text-gray-400 hover:text-white"
            }`}
          >
            Upload File
          </button>
        </div>

        {inputMode === "text" ? (
          <div>
            <label className="block text-sm text-gray-400 mb-1">
              Blueprint Document <span className="text-red-400">*</span>
            </label>
            <textarea
              value={blueprintText}
              onChange={(e) => setBlueprintText(e.target.value)}
              placeholder="Paste your blueprint document here. Describe what the agent does, its database schema, API routes, dashboard screens, and required services..."
              rows={16}
              className="w-full bg-forge-800 border border-forge-600 rounded-lg px-4 py-3 text-white placeholder-gray-500 focus:outline-none focus:border-forge-accent text-sm font-mono resize-y"
            />
            <div className="text-right text-xs text-gray-500 mt-1">
              {blueprintText.length} characters
            </div>
          </div>
        ) : (
          <div>
            <label className="block text-sm text-gray-400 mb-1">
              Blueprint File (.docx or .pdf) <span className="text-red-400">*</span>
            </label>
            <input
              type="file"
              accept=".docx,.pdf"
              onChange={(e) => setFile(e.target.files[0])}
              className="w-full bg-forge-800 border border-forge-600 rounded-lg px-4 py-2.5 text-white focus:outline-none focus:border-forge-accent text-sm file:mr-4 file:py-1 file:px-3 file:rounded file:border-0 file:bg-forge-accent file:text-white file:text-sm file:cursor-pointer"
            />
          </div>
        )}

        {error && (
          <div className="bg-red-900/30 border border-red-700 rounded-lg px-4 py-3 text-red-300 text-sm">
            {error}
          </div>
        )}

        <button
          type="submit"
          disabled={submitting}
          className="w-full bg-forge-accent hover:bg-forge-accent-hover disabled:opacity-50 disabled:cursor-not-allowed text-white font-semibold py-3 px-6 rounded-lg transition-colors text-sm"
        >
          {submitting ? "Submitting..." : "Start Build →"}
        </button>
      </form>
    </div>
  );
}

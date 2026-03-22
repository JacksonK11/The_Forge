import { useState, useEffect, useRef, useCallback } from "react";

const STORAGE_KEY = "forge_files";

function loadFiles() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? JSON.parse(raw) : [];
  } catch {
    return [];
  }
}

function saveFiles(files) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(files));
  } catch {
    // storage full or unavailable
  }
}

function formatBytes(bytes) {
  if (!bytes && bytes !== 0) return "—";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
}

function isTextFile(type, name) {
  if (!type && !name) return false;
  const textTypes = [
    "text/",
    "application/json",
    "application/javascript",
    "application/xml",
    "application/x-yaml",
  ];
  const textExts = [
    ".txt", ".md", ".json", ".js", ".jsx", ".ts", ".tsx", ".py",
    ".yaml", ".yml", ".toml", ".env", ".sh", ".css", ".html",
  ];
  if (type && textTypes.some((t) => type.startsWith(t))) return true;
  if (name) return textExts.some((ext) => name.toLowerCase().endsWith(ext));
  return false;
}

export default function FilesTab() {
  const [files, setFiles] = useState([]);
  const [dragging, setDragging] = useState(false);
  const [previewFile, setPreviewFile] = useState(null);
  const fileInputRef = useRef(null);
  const dropZoneRef = useRef(null);

  useEffect(() => {
    setFiles(loadFiles());
  }, []);

  function persistFiles(updated) {
    setFiles(updated);
    saveFiles(updated);
  }

  function processFile(file) {
    return new Promise((resolve) => {
      const reader = new FileReader();
      const isText = isTextFile(file.type, file.name);
      reader.onload = (e) => {
        resolve({
          id: `${Date.now()}-${Math.random().toString(36).slice(2)}`,
          name: file.name,
          size: file.size,
          type: file.type || "application/octet-stream",
          description: "",
          uploadDate: new Date().toISOString(),
          content: e.target.result,
          isText,
        });
      };
      if (isText) {
        reader.readAsText(file);
      } else {
        reader.readAsDataURL(file);
      }
    });
  }

  async function handleFiles(fileList) {
    const newFiles = await Promise.all(Array.from(fileList).map(processFile));
    persistFiles([...loadFiles(), ...newFiles]);
  }

  function handleDrop(e) {
    e.preventDefault();
    setDragging(false);
    handleFiles(e.dataTransfer.files);
  }

  function handleDragOver(e) {
    e.preventDefault();
    setDragging(true);
  }

  function handleDragLeave(e) {
    if (!dropZoneRef.current?.contains(e.relatedTarget)) {
      setDragging(false);
    }
  }

  function handleInputChange(e) {
    handleFiles(e.target.files);
    e.target.value = "";
  }

  function updateDescription(id, description) {
    const updated = files.map((f) => (f.id === id ? { ...f, description } : f));
    persistFiles(updated);
  }

  function deleteFile(id) {
    const updated = files.filter((f) => f.id !== id);
    persistFiles(updated);
    if (previewFile?.id === id) setPreviewFile(null);
  }

  function clearAll() {
    if (confirm("Clear all uploaded files? This cannot be undone.")) {
      persistFiles([]);
      setPreviewFile(null);
    }
  }

  return (
    <div className="max-w-3xl mx-auto">
      <div className="flex items-start justify-between mb-6">
        <div>
          <h2 className="font-['Bebas_Neue'] text-4xl text-gray-100 tracking-widest">
            FILES
          </h2>
          <p className="text-gray-500 text-sm mt-1">
            Files are attached to every Chat conversation for AI context.
          </p>
        </div>
        {files.length > 0 && (
          <button
            onClick={clearAll}
            className="text-xs text-red-500 hover:text-red-400 border border-red-900 hover:border-red-700 px-3 py-1.5 rounded-lg transition-colors"
          >
            Clear All
          </button>
        )}
      </div>

      {/* Drop zone */}
      <div
        ref={dropZoneRef}
        onDrop={handleDrop}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onClick={() => fileInputRef.current?.click()}
        className={`border-2 border-dashed rounded-lg p-10 text-center cursor-pointer transition-colors ${
          dragging
            ? "border-purple-500 bg-purple-950/20"
            : "border-gray-700 hover:border-gray-600 bg-gray-900"
        }`}
      >
        <input
          ref={fileInputRef}
          type="file"
          multiple
          onChange={handleInputChange}
          className="hidden"
        />
        <div className="text-4xl mb-3 opacity-40">
          {dragging ? "↓" : "↑"}
        </div>
        <p className="text-gray-400 text-sm">
          {dragging ? "Release to upload" : "Drop files here or click to upload"}
        </p>
        <p className="text-gray-600 text-xs mt-1">Any file type accepted</p>
      </div>

      {/* File list */}
      {files.length > 0 && (
        <div className="mt-6 space-y-3">
          {files.map((f) => (
            <div key={f.id} className="border border-gray-800 rounded-lg bg-gray-900 p-4">
              <div className="flex items-start gap-3">
                <div className="w-8 h-8 rounded bg-gray-800 flex items-center justify-center flex-shrink-0 text-sm">
                  {f.isText ? (
                    <span className="text-teal-400">T</span>
                  ) : (
                    <span className="text-gray-500">B</span>
                  )}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <p className="text-gray-200 text-sm font-medium font-mono truncate">
                        {f.name}
                      </p>
                      <p className="text-gray-600 text-xs font-mono mt-0.5">
                        {formatBytes(f.size)} · {f.type || "unknown"}
                      </p>
                    </div>
                    <div className="flex items-center gap-2 flex-shrink-0">
                      {f.isText && (
                        <button
                          onClick={() => setPreviewFile(previewFile?.id === f.id ? null : f)}
                          className="text-xs text-cyan-500 hover:text-cyan-400 transition-colors"
                        >
                          {previewFile?.id === f.id ? "Hide" : "Preview"}
                        </button>
                      )}
                      <button
                        onClick={() => deleteFile(f.id)}
                        className="text-xs text-gray-600 hover:text-red-400 transition-colors"
                      >
                        Delete
                      </button>
                    </div>
                  </div>
                  <input
                    type="text"
                    value={f.description}
                    onChange={(e) => updateDescription(f.id, e.target.value)}
                    placeholder="Add a description for AI context..."
                    className="mt-2 w-full bg-gray-800 border border-gray-700 rounded px-3 py-1.5 text-gray-300 text-xs placeholder-gray-600 focus:border-purple-600 focus:outline-none transition-colors"
                  />
                </div>
              </div>

              {previewFile?.id === f.id && (
                <div className="mt-3 border border-gray-700 rounded overflow-hidden">
                  <pre className="bg-gray-950 text-gray-300 text-xs font-['IBM_Plex_Mono'] p-3 overflow-x-auto max-h-48 overflow-y-auto whitespace-pre-wrap">
                    {f.content}
                  </pre>
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {files.length === 0 && (
        <div className="mt-6 text-center text-gray-600 text-sm">
          No files uploaded yet.
        </div>
      )}
    </div>
  );
}

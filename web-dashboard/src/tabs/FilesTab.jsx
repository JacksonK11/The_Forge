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

export default function FilesTab({ isMobile = false }) {
  const [files, setFiles] = useState([]);
  const [dragging, setDragging] = useState(false);
  const [previewFile, setPreviewFile] = useState(null);
  const [expandedFiles, setExpandedFiles] = useState({});
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
      setExpandedFiles({});
    }
  }

  function toggleExpanded(id) {
    setExpandedFiles((prev) => ({
      ...prev,
      [id]: !prev[id],
    }));
  }

  return (
    <div className={isMobile ? "w-full px-2" : "max-w-3xl mx-auto"}>
      <div className={`flex items-start justify-between ${isMobile ? "mb-4" : "mb-6"}`}>
        <div>
          <h2 className={`font-['Bebas_Neue'] text-gray-100 tracking-widest ${isMobile ? "text-3xl" : "text-4xl"}`}>
            FILES
          </h2>
          <p className={`text-gray-500 mt-1 ${isMobile ? "text-xs" : "text-sm"}`}>
            Files are attached to every Chat conversation for AI context.
          </p>
        </div>
        {files.length > 0 && (
          <button
            onClick={clearAll}
            className={`text-xs text-red-500 hover:text-red-400 border border-red-900 hover:border-red-700 rounded-lg transition-colors ${
              isMobile ? "px-3 py-2 min-h-[44px] min-w-[44px] flex items-center justify-center" : "px-3 py-1.5"
            }`}
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
        className={`border-2 border-dashed rounded-lg text-center cursor-pointer transition-colors ${
          isMobile ? "p-6" : "p-10"
        } ${
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
        <div className={`mb-3 opacity-40 ${isMobile ? "text-3xl" : "text-4xl"}`}>
          {dragging ? "↓" : "↑"}
        </div>
        <p className={`text-gray-400 ${isMobile ? "text-sm" : "text-sm"}`}>
          {dragging ? "Release to upload" : "Drop files here or tap to upload"}
        </p>
        <p className="text-gray-600 text-xs mt-1">Any file type accepted</p>
      </div>

      {/* File list */}
      {files.length > 0 && (
        <div className={`mt-6 ${isMobile ? "space-y-2" : "space-y-3"}`}>
          {files.map((f) => {
            const isExpanded = isMobile ? expandedFiles[f.id] : true;
            const isPreviewOpen = previewFile?.id === f.id;

            return (
              <div key={f.id} className={`border border-gray-800 rounded-lg bg-gray-900 ${isMobile ? "p-3" : "p-4"}`}>
                {/* Mobile: collapsible header */}
                {isMobile ? (
                  <>
                    <button
                      onClick={() => toggleExpanded(f.id)}
                      className="w-full flex items-center gap-3 min-h-[44px] text-left"
                    >
                      <div className="w-9 h-9 rounded bg-gray-800 flex items-center justify-center flex-shrink-0 text-sm">
                        {f.isText ? (
                          <span className="text-teal-400">T</span>
                        ) : (
                          <span className="text-gray-500">B</span>
                        )}
                      </div>
                      <div className="flex-1 min-w-0">
                        <p className="text-gray-200 text-sm font-medium font-mono truncate">
                          {f.name}
                        </p>
                        <p className="text-gray-600 text-xs font-mono mt-0.5">
                          {formatBytes(f.size)}
                        </p>
                      </div>
                      <span className="text-gray-500 text-xs flex-shrink-0 ml-2">
                        {isExpanded ? "▲" : "▼"}
                      </span>
                    </button>

                    {isExpanded && (
                      <div className="mt-3 pt-3 border-t border-gray-800">
                        <p className="text-gray-600 text-xs font-mono mb-2">
                          {f.type || "unknown"}
                        </p>
                        <input
                          type="text"
                          value={f.description}
                          onChange={(e) => updateDescription(f.id, e.target.value)}
                          placeholder="Add a description for AI context..."
                          className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2.5 text-gray-300 text-sm placeholder-gray-600 focus:border-purple-600 focus:outline-none transition-colors min-h-[44px]"
                        />
                        <div className="flex gap-2 mt-3">
                          {f.isText && (
                            <button
                              onClick={() => setPreviewFile(isPreviewOpen ? null : f)}
                              className="flex-1 min-h-[44px] text-sm text-cyan-500 hover:text-cyan-400 bg-gray-800 border border-gray-700 rounded-lg transition-colors"
                            >
                              {isPreviewOpen ? "Hide Preview" : "Preview"}
                            </button>
                          )}
                          <button
                            onClick={() => deleteFile(f.id)}
                            className="flex-1 min-h-[44px] text-sm text-red-500 hover:text-red-400 bg-gray-800 border border-gray-700 rounded-lg transition-colors"
                          >
                            Delete
                          </button>
                        </div>
                      </div>
                    )}
                  </>
                ) : (
                  /* Desktop layout */
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
                              onClick={() => setPreviewFile(isPreviewOpen ? null : f)}
                              className="text-xs text-cyan-500 hover:text-cyan-400 transition-colors"
                            >
                              {isPreviewOpen ? "Hide" : "Preview"}
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
                )}

                {/* Preview (shared between mobile and desktop) */}
                {isPreviewOpen && (
                  <div className={`mt-3 border border-gray-700 rounded overflow-hidden ${isMobile ? "w-full" : ""}`}>
                    <pre
                      className={`bg-gray-950 text-gray-300 font-['IBM_Plex_Mono'] p-3 overflow-x-auto max-h-48 overflow-y-auto ${
                        isMobile
                          ? "text-xs whitespace-pre -webkit-overflow-scrolling-touch"
                          : "text-xs whitespace-pre-wrap"
                      }`}
                      style={isMobile ? { WebkitOverflowScrolling: "touch" } : undefined}
                    >
                      {f.content}
                    </pre>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      {files.length === 0 && (
        <div className={`mt-6 text-center text-gray-600 text-sm ${isMobile ? "py-8" : ""}`}>
          No files uploaded yet.
        </div>
      )}
    </div>
  );
}
import React, { useRef, useCallback, useState } from 'react';

const FILE_TYPE_ICONS = {
  // Documents
  pdf: '📄',
  docx: '📝',
  doc: '📝',
  txt: '📃',
  md: '📋',
  rst: '📋',
  // Code
  py: '🐍',
  js: '🟨',
  jsx: '⚛️',
  ts: '🔷',
  tsx: '⚛️',
  html: '🌐',
  css: '🎨',
  scss: '🎨',
  less: '🎨',
  // Data
  json: '📦',
  yaml: '⚙️',
  yml: '⚙️',
  toml: '⚙️',
  xml: '📰',
  csv: '📊',
  sql: '🗃️',
  // Shell / Config
  sh: '🖥️',
  bash: '🖥️',
  zsh: '🖥️',
  env: '🔐',
  ini: '⚙️',
  cfg: '⚙️',
  conf: '⚙️',
  // Systems
  go: '🔵',
  rs: '🦀',
  java: '☕',
  kt: '🟣',
  scala: '🔴',
  c: '©️',
  cpp: '➕',
  h: '📎',
  hpp: '📎',
  swift: '🍊',
  rb: '💎',
  dart: '🎯',
  // Infra
  dockerfile: '🐳',
  tf: '🏗️',
  hcl: '🏗️',
  // Web frameworks
  vue: '💚',
  svelte: '🧡',
  // Other
  lock: '🔒',
  log: '📜',
  graphql: '◼️',
  proto: '📡',
  prisma: '🔺',
  sol: '⛓️',
};

function getFileIcon(filename) {
  const ext = getExtension(filename);
  return FILE_TYPE_ICONS[ext] || '📎';
}

function getExtension(filename) {
  const parts = filename.split('.');
  if (parts.length < 2) return '';
  return parts[parts.length - 1].toLowerCase();
}

function formatFileSize(bytes) {
  if (bytes == null || bytes === 0) return '0 B';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`;
}

function getExtBadgeColor(ext) {
  const map = {
    py: { bg: 'bg-blue-500/20', border: 'border-blue-500/40', text: 'text-blue-300' },
    js: { bg: 'bg-yellow-500/20', border: 'border-yellow-500/40', text: 'text-yellow-300' },
    jsx: { bg: 'bg-yellow-500/20', border: 'border-yellow-500/40', text: 'text-yellow-300' },
    ts: { bg: 'bg-blue-400/20', border: 'border-blue-400/40', text: 'text-blue-300' },
    tsx: { bg: 'bg-blue-400/20', border: 'border-blue-400/40', text: 'text-blue-300' },
    json: { bg: 'bg-green-500/20', border: 'border-green-500/40', text: 'text-green-300' },
    yaml: { bg: 'bg-orange-500/20', border: 'border-orange-500/40', text: 'text-orange-300' },
    yml: { bg: 'bg-orange-500/20', border: 'border-orange-500/40', text: 'text-orange-300' },
    toml: { bg: 'bg-purple-500/20', border: 'border-purple-500/40', text: 'text-purple-300' },
    md: { bg: 'bg-gray-500/20', border: 'border-gray-500/40', text: 'text-gray-300' },
    txt: { bg: 'bg-gray-500/20', border: 'border-gray-500/40', text: 'text-gray-300' },
    pdf: { bg: 'bg-red-500/20', border: 'border-red-500/40', text: 'text-red-300' },
    docx: { bg: 'bg-blue-500/20', border: 'border-blue-500/40', text: 'text-blue-300' },
    html: { bg: 'bg-red-400/20', border: 'border-red-400/40', text: 'text-red-300' },
    css: { bg: 'bg-indigo-500/20', border: 'border-indigo-500/40', text: 'text-indigo-300' },
    sql: { bg: 'bg-sky-500/20', border: 'border-sky-500/40', text: 'text-sky-300' },
    sh: { bg: 'bg-green-500/20', border: 'border-green-500/40', text: 'text-green-300' },
    go: { bg: 'bg-sky-500/20', border: 'border-sky-500/40', text: 'text-sky-300' },
    rs: { bg: 'bg-orange-500/20', border: 'border-orange-500/40', text: 'text-orange-300' },
    java: { bg: 'bg-red-500/20', border: 'border-red-500/40', text: 'text-red-300' },
    rb: { bg: 'bg-red-500/20', border: 'border-red-500/40', text: 'text-red-300' },
    swift: { bg: 'bg-orange-500/20', border: 'border-orange-500/40', text: 'text-orange-300' },
    dockerfile: { bg: 'bg-sky-500/20', border: 'border-sky-500/40', text: 'text-sky-300' },
  };
  return map[ext] || { bg: 'bg-purple-700/20', border: 'border-purple-700/40', text: 'text-purple-300' };
}

/**
 * FileAttachmentArea — drag-drop zone + attachment card grid.
 *
 * Props:
 *   attachedFiles   — File[] managed by parent
 *   onFilesAdded    — (newFiles: File[]) => void
 *   onFileRemoved   — (index: number) => void
 */
export default function FileAttachmentArea({ attachedFiles, onFilesAdded, onFileRemoved }) {
  const [isDragOver, setIsDragOver] = useState(false);
  const fileInputRef = useRef(null);

  const handleDragOver = useCallback((e) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragOver(true);
  }, []);

  const handleDragLeave = useCallback((e) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragOver(false);
  }, []);

  const handleDrop = useCallback(
    (e) => {
      e.preventDefault();
      e.stopPropagation();
      setIsDragOver(false);
      if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
        onFilesAdded(Array.from(e.dataTransfer.files));
      }
    },
    [onFilesAdded]
  );

  const handleFileInputChange = useCallback(
    (e) => {
      if (e.target.files && e.target.files.length > 0) {
        onFilesAdded(Array.from(e.target.files));
        e.target.value = '';
      }
    },
    [onFilesAdded]
  );

  const handleClickZone = useCallback(() => {
    if (fileInputRef.current) {
      fileInputRef.current.click();
    }
  }, []);

  return (
    <div className="w-full">
      {/* Hidden file input */}
      <input
        ref={fileInputRef}
        type="file"
        multiple
        accept="*/*"
        onChange={handleFileInputChange}
        className="hidden"
      />

      {/* Drop zone */}
      <div
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
        onClick={handleClickZone}
        className={`
          border-2 border-dashed rounded-xl px-4 py-5 text-center cursor-pointer
          transition-all duration-200 ease-in-out
          ${isDragOver
            ? 'border-amber-400/70 bg-amber-500/10'
            : 'border-purple-700/40 bg-purple-900/5 hover:border-purple-500/50 hover:bg-purple-900/10'
          }
          ${attachedFiles.length > 0 ? 'mb-3' : ''}
        `}
      >
        <div className="text-2xl mb-1.5">📎</div>
        <div className={`text-sm font-semibold mb-1 ${isDragOver ? 'text-amber-300' : 'text-purple-300'}`}>
          Attach files — .docx, .pdf, .py, .txt, .json, any type
        </div>
        <div className="text-xs text-gray-500">
          Drop files here or click to browse • Multiple files supported
        </div>
      </div>

      {/* Attachment cards grid */}
      {attachedFiles.length > 0 && (
        <div>
          {/* Header */}
          <div className="flex items-center justify-between mb-2">
            <span className="text-xs font-medium text-gray-400">
              {attachedFiles.length} file{attachedFiles.length !== 1 ? 's' : ''} attached
            </span>
            <span className="text-xs text-gray-500">
              {formatFileSize(attachedFiles.reduce((sum, f) => sum + (f.size || 0), 0))} total
            </span>
          </div>

          {/* Card grid */}
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2">
            {attachedFiles.map((file, index) => {
              const ext = getExtension(file.name);
              const icon = getFileIcon(file.name);
              const badgeColors = getExtBadgeColor(ext);

              return (
                <div
                  key={`${file.name}-${file.size}-${file.lastModified}-${index}`}
                  className="group relative flex items-center gap-3 rounded-lg border border-purple-800/30 bg-[#110d1f]/80 px-3 py-2.5 transition-all duration-150 hover:border-purple-600/40 hover:bg-[#15102a]/90"
                >
                  {/* File icon */}
                  <div className="flex-shrink-0 flex items-center justify-center w-10 h-10 rounded-lg bg-purple-900/30 text-xl">
                    {icon}
                  </div>

                  {/* File info */}
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-1.5 mb-0.5">
                      <span className="text-sm font-medium text-gray-200 truncate" title={file.name}>
                        {file.name}
                      </span>
                    </div>
                    <div className="flex items-center gap-2">
                      {ext && (
                        <span
                          className={`inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-semibold uppercase border ${badgeColors.bg} ${badgeColors.border} ${badgeColors.text}`}
                        >
                          .{ext}
                        </span>
                      )}
                      <span className="text-xs text-gray-500">
                        {formatFileSize(file.size)}
                      </span>
                    </div>
                  </div>

                  {/* Remove button */}
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      onFileRemoved(index);
                    }}
                    className="flex-shrink-0 flex items-center justify-center w-7 h-7 rounded-md text-gray-500 hover:text-red-400 hover:bg-red-500/10 transition-all duration-150 opacity-60 group-hover:opacity-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-red-500"
                    aria-label={`Remove ${file.name}`}
                    title="Remove file"
                  >
                    <svg
                      xmlns="http://www.w3.org/2000/svg"
                      className="w-4 h-4"
                      fill="none"
                      viewBox="0 0 24 24"
                      stroke="currentColor"
                      strokeWidth={2}
                    >
                      <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                    </svg>
                  </button>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
/**
 * @deprecated This component is deprecated for use in BuildTab.
 * The Build tab now uses FileAttachmentArea.jsx which stores File objects
 * as attachments (like chat attachments) instead of reading file contents
 * into the Blueprint textarea. File text extraction is now handled server-side
 * via POST /forge/submit-with-files.
 *
 * This component is retained for backward compatibility in case it is used
 * elsewhere, but new code should use FileAttachmentArea.jsx instead.
 */

import React, { useState, useRef, useCallback } from 'react';

const TEXT_EXTENSIONS = new Set([
  'py', 'txt', 'md', 'rst', 'js', 'jsx', 'ts', 'tsx', 'html', 'css', 'scss',
  'less', 'json', 'yaml', 'yml', 'toml', 'ini', 'cfg', 'conf', 'env', 'sh',
  'bash', 'zsh', 'fish', 'bat', 'cmd', 'ps1', 'rb', 'go', 'rs', 'java',
  'kt', 'kts', 'scala', 'c', 'h', 'cpp', 'hpp', 'cs', 'swift', 'm', 'mm',
  'r', 'jl', 'lua', 'pl', 'pm', 'php', 'sql', 'graphql', 'gql',
  'proto', 'xml', 'svg', 'csv', 'tsv', 'log', 'diff', 'patch', 'makefile',
  'dockerfile', 'gitignore', 'gitattributes', 'editorconfig', 'prettierrc',
  'eslintrc', 'babelrc', 'webpack', 'vite', 'vue', 'svelte', 'astro',
  'mdx', 'tex', 'bib', 'srt', 'vtt', 'asm', 's', 'tf', 'hcl', 'nix',
  'ex', 'exs', 'erl', 'hrl', 'hs', 'lhs', 'ml', 'mli', 'clj', 'cljs',
  'cljc', 'edn', 'elm', 'purs', 'dart', 'v', 'sv', 'vhd', 'vhdl',
  'lock', 'pip', 'pipfile', 'gemfile', 'rakefile', 'procfile', 'vagrantfile',
  'gradle', 'cmake', 'meson', 'ninja', 'bazel', 'build', 'bzl',
  'properties', 'plist', 'manifest', 'htaccess', 'nginx',
  'cjs', 'mjs', 'mts', 'cts', 'jsonc', 'json5', 'jsonl', 'ndjson',
  'graphqlrc', 'eslintignore', 'npmrc', 'yarnrc', 'nvmrc',
  'dockerignore', 'browserslistrc', 'stylelintrc',
  'prisma', 'sol', 'vy', 'move', 'cairo', 'circom',
  'tf', 'tfvars', 'hcl', 'nomad', 'sentinel',
  'robot', 'feature', 'story', 'stories',
  'rmd', 'qmd', 'ipynb',
  'snap', 'test', 'spec',
  'env', 'env.local', 'env.development', 'env.production', 'env.test',
  'cfg', 'config', 'rc', 'rules',
]);

const BINARY_EXTENSIONS = new Set([
  'png', 'jpg', 'jpeg', 'gif', 'bmp', 'ico', 'webp', 'tiff', 'tif',
  'mp3', 'mp4', 'wav', 'avi', 'mov', 'mkv', 'flv', 'wmv', 'ogg', 'webm',
  'woff', 'woff2', 'ttf', 'otf', 'eot',
  'exe', 'dll', 'so', 'dylib', 'bin', 'dat', 'db', 'sqlite',
  'zip', 'tar', 'gz', 'bz2', 'rar', '7z', 'xz', 'zst',
  'xlsx', 'xls', 'pptx', 'ppt',
  'class', 'pyc', 'pyo', 'o', 'obj', 'a', 'lib',
  'iso', 'img', 'dmg',
]);

const EXTRACTABLE_EXTENSIONS = new Set(['pdf', 'docx']);

function getExtension(filename) {
  const parts = filename.split('.');
  if (parts.length < 2) return '';
  return parts[parts.length - 1].toLowerCase();
}

function isTextFile(filename) {
  const ext = getExtension(filename);
  if (TEXT_EXTENSIONS.has(ext)) return true;
  if (BINARY_EXTENSIONS.has(ext)) return false;
  if (EXTRACTABLE_EXTENSIONS.has(ext)) return false;
  return true;
}

function isExtractable(filename) {
  return EXTRACTABLE_EXTENSIONS.has(getExtension(filename));
}

function isBinaryNonExtractable(filename) {
  const ext = getExtension(filename);
  return BINARY_EXTENSIONS.has(ext);
}

function formatFileSize(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function getBadgeColor(ext) {
  const colors = {
    py: { bg: 'rgba(59, 130, 246, 0.2)', border: 'rgba(59, 130, 246, 0.4)', text: '#93c5fd' },
    js: { bg: 'rgba(234, 179, 8, 0.2)', border: 'rgba(234, 179, 8, 0.4)', text: '#fde047' },
    jsx: { bg: 'rgba(234, 179, 8, 0.2)', border: 'rgba(234, 179, 8, 0.4)', text: '#fde047' },
    ts: { bg: 'rgba(59, 130, 246, 0.2)', border: 'rgba(59, 130, 246, 0.4)', text: '#93c5fd' },
    tsx: { bg: 'rgba(59, 130, 246, 0.2)', border: 'rgba(59, 130, 246, 0.4)', text: '#93c5fd' },
    json: { bg: 'rgba(34, 197, 94, 0.2)', border: 'rgba(34, 197, 94, 0.4)', text: '#86efac' },
    yaml: { bg: 'rgba(234, 88, 12, 0.2)', border: 'rgba(234, 88, 12, 0.4)', text: '#fdba74' },
    yml: { bg: 'rgba(234, 88, 12, 0.2)', border: 'rgba(234, 88, 12, 0.4)', text: '#fdba74' },
    toml: { bg: 'rgba(168, 85, 247, 0.2)', border: 'rgba(168, 85, 247, 0.4)', text: '#c4b5fd' },
    md: { bg: 'rgba(156, 163, 175, 0.2)', border: 'rgba(156, 163, 175, 0.4)', text: '#d1d5db' },
    txt: { bg: 'rgba(156, 163, 175, 0.2)', border: 'rgba(156, 163, 175, 0.4)', text: '#d1d5db' },
    csv: { bg: 'rgba(34, 197, 94, 0.2)', border: 'rgba(34, 197, 94, 0.4)', text: '#86efac' },
    html: { bg: 'rgba(239, 68, 68, 0.2)', border: 'rgba(239, 68, 68, 0.4)', text: '#fca5a5' },
    css: { bg: 'rgba(99, 102, 241, 0.2)', border: 'rgba(99, 102, 241, 0.4)', text: '#a5b4fc' },
    scss: { bg: 'rgba(99, 102, 241, 0.2)', border: 'rgba(99, 102, 241, 0.4)', text: '#a5b4fc' },
    sql: { bg: 'rgba(14, 165, 233, 0.2)', border: 'rgba(14, 165, 233, 0.4)', text: '#7dd3fc' },
    docx: { bg: 'rgba(59, 130, 246, 0.2)', border: 'rgba(59, 130, 246, 0.4)', text: '#93c5fd' },
    pdf: { bg: 'rgba(239, 68, 68, 0.2)', border: 'rgba(239, 68, 68, 0.4)', text: '#fca5a5' },
    sh: { bg: 'rgba(34, 197, 94, 0.2)', border: 'rgba(34, 197, 94, 0.4)', text: '#86efac' },
    bash: { bg: 'rgba(34, 197, 94, 0.2)', border: 'rgba(34, 197, 94, 0.4)', text: '#86efac' },
    dockerfile: { bg: 'rgba(14, 165, 233, 0.2)', border: 'rgba(14, 165, 233, 0.4)', text: '#7dd3fc' },
    go: { bg: 'rgba(14, 165, 233, 0.2)', border: 'rgba(14, 165, 233, 0.4)', text: '#7dd3fc' },
    rs: { bg: 'rgba(234, 88, 12, 0.2)', border: 'rgba(234, 88, 12, 0.4)', text: '#fdba74' },
    java: { bg: 'rgba(239, 68, 68, 0.2)', border: 'rgba(239, 68, 68, 0.4)', text: '#fca5a5' },
    rb: { bg: 'rgba(239, 68, 68, 0.2)', border: 'rgba(239, 68, 68, 0.4)', text: '#fca5a5' },
    c: { bg: 'rgba(107, 114, 128, 0.2)', border: 'rgba(107, 114, 128, 0.4)', text: '#d1d5db' },
    cpp: { bg: 'rgba(107, 114, 128, 0.2)', border: 'rgba(107, 114, 128, 0.4)', text: '#d1d5db' },
    h: { bg: 'rgba(107, 114, 128, 0.2)', border: 'rgba(107, 114, 128, 0.4)', text: '#d1d5db' },
    hpp: { bg: 'rgba(107, 114, 128, 0.2)', border: 'rgba(107, 114, 128, 0.4)', text: '#d1d5db' },
    swift: { bg: 'rgba(234, 88, 12, 0.2)', border: 'rgba(234, 88, 12, 0.4)', text: '#fdba74' },
    kt: { bg: 'rgba(168, 85, 247, 0.2)', border: 'rgba(168, 85, 247, 0.4)', text: '#c4b5fd' },
    scala: { bg: 'rgba(239, 68, 68, 0.2)', border: 'rgba(239, 68, 68, 0.4)', text: '#fca5a5' },
    dart: { bg: 'rgba(14, 165, 233, 0.2)', border: 'rgba(14, 165, 233, 0.4)', text: '#7dd3fc' },
    vue: { bg: 'rgba(34, 197, 94, 0.2)', border: 'rgba(34, 197, 94, 0.4)', text: '#86efac' },
    svelte: { bg: 'rgba(234, 88, 12, 0.2)', border: 'rgba(234, 88, 12, 0.4)', text: '#fdba74' },
    prisma: { bg: 'rgba(99, 102, 241, 0.2)', border: 'rgba(99, 102, 241, 0.4)', text: '#a5b4fc' },
    graphql: { bg: 'rgba(236, 72, 153, 0.2)', border: 'rgba(236, 72, 153, 0.4)', text: '#f9a8d4' },
    proto: { bg: 'rgba(34, 197, 94, 0.2)', border: 'rgba(34, 197, 94, 0.4)', text: '#86efac' },
    xml: { bg: 'rgba(234, 88, 12, 0.2)', border: 'rgba(234, 88, 12, 0.4)', text: '#fdba74' },
    env: { bg: 'rgba(234, 179, 8, 0.2)', border: 'rgba(234, 179, 8, 0.4)', text: '#fde047' },
    ini: { bg: 'rgba(156, 163, 175, 0.2)', border: 'rgba(156, 163, 175, 0.4)', text: '#d1d5db' },
    cfg: { bg: 'rgba(156, 163, 175, 0.2)', border: 'rgba(156, 163, 175, 0.4)', text: '#d1d5db' },
    conf: { bg: 'rgba(156, 163, 175, 0.2)', border: 'rgba(156, 163, 175, 0.4)', text: '#d1d5db' },
    lock: { bg: 'rgba(107, 114, 128, 0.2)', border: 'rgba(107, 114, 128, 0.4)', text: '#9ca3af' },
    tf: { bg: 'rgba(99, 102, 241, 0.2)', border: 'rgba(99, 102, 241, 0.4)', text: '#a5b4fc' },
    sol: { bg: 'rgba(107, 114, 128, 0.2)', border: 'rgba(107, 114, 128, 0.4)', text: '#d1d5db' },
  };
  const defaultColor = { bg: 'rgba(107, 33, 168, 0.2)', border: 'rgba(107, 33, 168, 0.4)', text: '#c4b5fd' };
  return colors[ext] || defaultColor;
}

/**
 * @deprecated Use FileAttachmentArea.jsx instead. File content extraction
 * is now handled server-side via POST /forge/submit-with-files.
 *
 * Read a single file's text content client-side.
 * For text files, reads as UTF-8 text.
 * For extractable binary files (.docx, .pdf), returns a placeholder
 * indicating server-side extraction is needed, along with the raw file object.
 * For other binary files, returns a placeholder note.
 */
function readFileContentClientSide(fileEntry) {
  return new Promise((resolve) => {
    const { file, name } = fileEntry;
    const ext = getExtension(name);

    if (EXTRACTABLE_EXTENSIONS.has(ext)) {
      resolve({
        name,
        content: null,
        needsServerExtraction: true,
        file,
        ext,
        placeholder: `[${ext.toUpperCase()} file: ${name} — ${formatFileSize(file.size)}. Will be extracted server-side.]`,
      });
      return;
    }

    if (isTextFile(name)) {
      const reader = new FileReader();
      reader.onload = (e) => {
        resolve({
          name,
          content: e.target.result,
          needsServerExtraction: false,
          file: null,
          ext,
          placeholder: null,
        });
      };
      reader.onerror = () => {
        resolve({
          name,
          content: `[Error reading file: ${name}]`,
          needsServerExtraction: false,
          file: null,
          ext,
          placeholder: null,
        });
      };
      reader.readAsText(file, 'utf-8');
      return;
    }

    resolve({
      name,
      content: `[Binary file: ${name} — ${formatFileSize(file.size)}]`,
      needsServerExtraction: false,
      file: null,
      ext,
      placeholder: null,
    });
  });
}

/**
 * @deprecated Use POST /forge/submit-with-files instead.
 * Server-side extraction is now handled by the new endpoint automatically.
 *
 * Submit a file to the server for text extraction (for .docx, .pdf, etc).
 * Calls the /forge/submit-file endpoint and returns the extracted text.
 */
async function extractFileOnServer(file, apiBase, apiKey) {
  const formData = new FormData();
  formData.append('file', file);

  const response = await fetch(`${apiBase}/forge/submit-file`, {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${apiKey}`,
    },
    body: formData,
  });

  if (!response.ok) {
    const errorText = await response.text().catch(() => 'Unknown error');
    throw new Error(`Server extraction failed (${response.status}): ${errorText}`);
  }

  const data = await response.json();
  return {
    text: data.text || data.content || '',
    filename: data.filename || file.name,
  };
}

/**
 * @deprecated Use FileAttachmentArea.jsx and POST /forge/submit-with-files instead.
 * File content combination is now handled server-side.
 *
 * Read all files and combine their contents into labeled sections.
 * For extractable files (.docx, .pdf), sends them to the server for extraction.
 * Returns a string with format:
 * === filename.ext ===
 * <file contents>
 *
 * For each file.
 */
export async function combineFileContents(fileEntries, options = {}) {
  if (!fileEntries || fileEntries.length === 0) return '';

  const { apiBase, apiKey, onProgress } = options;
  const results = [];

  for (let i = 0; i < fileEntries.length; i++) {
    const entry = fileEntries[i];
    if (onProgress) {
      onProgress({ current: i + 1, total: fileEntries.length, fileName: entry.name });
    }

    const clientResult = await readFileContentClientSide(entry);

    if (clientResult.needsServerExtraction && apiBase && apiKey) {
      try {
        const { text: extractedText } = await extractFileOnServer(clientResult.file, apiBase, apiKey);
        results.push({ name: entry.name, content: extractedText });
      } catch (err) {
        results.push({
          name: entry.name,
          content: `[Server extraction failed for ${entry.name}: ${err.message}]`,
        });
      }
    } else if (clientResult.needsServerExtraction) {
      results.push({ name: entry.name, content: clientResult.placeholder });
    } else {
      results.push({ name: entry.name, content: clientResult.content });
    }
  }

  const sections = results.map(({ name, content }) => {
    return `=== ${name} ===\n${content}`;
  });

  return sections.join('\n\n');
}

/**
 * @deprecated Use FileAttachmentArea.jsx and POST /forge/submit-with-files instead.
 * File content reading is now handled server-side.
 *
 * Read all file contents and return as an array of { name, content } objects.
 * For extractable files, sends them to the server for extraction.
 */
export async function readAllFileContents(fileEntries, options = {}) {
  if (!fileEntries || fileEntries.length === 0) return [];

  const { apiBase, apiKey, onProgress } = options;
  const results = [];

  for (let i = 0; i < fileEntries.length; i++) {
    const entry = fileEntries[i];
    if (onProgress) {
      onProgress({ current: i + 1, total: fileEntries.length, fileName: entry.name });
    }

    const clientResult = await readFileContentClientSide(entry);

    if (clientResult.needsServerExtraction && apiBase && apiKey) {
      try {
        const { text: extractedText } = await extractFileOnServer(clientResult.file, apiBase, apiKey);
        results.push({ name: entry.name, content: extractedText });
      } catch (err) {
        results.push({
          name: entry.name,
          content: `[Server extraction failed for ${entry.name}: ${err.message}]`,
        });
      }
    } else if (clientResult.needsServerExtraction) {
      results.push({ name: entry.name, content: clientResult.placeholder });
    } else {
      results.push({ name: entry.name, content: clientResult.content });
    }
  }

  return results;
}

/**
 * @deprecated Use FileAttachmentArea.jsx instead.
 *
 * Get the list of files that need server-side extraction.
 */
export function getExtractableFiles(fileEntries) {
  if (!fileEntries || fileEntries.length === 0) return [];
  return fileEntries.filter((entry) => isExtractable(entry.name));
}

/**
 * @deprecated Use FileAttachmentArea.jsx instead.
 *
 * Get the list of files that can be read client-side as text.
 */
export function getTextFiles(fileEntries) {
  if (!fileEntries || fileEntries.length === 0) return [];
  return fileEntries.filter((entry) => isTextFile(entry.name));
}

/**
 * @deprecated This component is deprecated for use in BuildTab.
 * Use FileAttachmentArea.jsx instead, which stores File objects as attachments
 * and sends them to POST /forge/submit-with-files for server-side text extraction.
 *
 * FileUploadGrid component with two-path upload flow:
 * - Binary files (.docx, .pdf) are sent to the backend via POST /forge/submit-file for text extraction
 * - Text files (.py, .txt, .toml, .json, .md, .yml, etc.) are read client-side with FileReader
 *
 * Props:
 * - files: Array of file entry objects
 * - setFiles: State setter for files array
 * - onTextExtracted: Callback(text, filename) — called when text is extracted from any file,
 *   so the parent can display it in the Blueprint textarea
 * - onServerExtract: Optional callback(file, id) => Promise<string> for custom server extraction
 * - apiBase: API base URL for server-side extraction (used when onServerExtract is not provided)
 * - apiKey: API secret key for authorization
 */
export default function FileUploadGrid({ files, setFiles, onTextExtracted, onServerExtract, apiBase, apiKey }) {
  const [isDragOver, setIsDragOver] = useState(false);
  const [extracting, setExtracting] = useState({});
  const fileInputRef = useRef(null);

  const handleServerExtraction = useCallback(async (file, entryId) => {
    setExtracting((prev) => ({ ...prev, [entryId]: true }));

    try {
      let extractedText;

      if (onServerExtract) {
        extractedText = await onServerExtract(file, entryId);
      } else if (apiBase && apiKey) {
        const result = await extractFileOnServer(file, apiBase, apiKey);
        extractedText = result.text;
      } else {
        throw new Error('No server extraction method available. Provide apiBase+apiKey or onServerExtract.');
      }

      setFiles((prev) =>
        prev.map((f) =>
          f.id === entryId
            ? { ...f, serverExtracted: true, extractedContent: extractedText, extractionError: null }
            : f
        )
      );

      if (onTextExtracted && extractedText) {
        onTextExtracted(extractedText, file.name);
      }

      return extractedText;
    } catch (err) {
      setFiles((prev) =>
        prev.map((f) =>
          f.id === entryId
            ? { ...f, serverExtracted: false, extractionError: err.message }
            : f
        )
      );
      return null;
    } finally {
      setExtracting((prev) => {
        const next = { ...prev };
        delete next[entryId];
        return next;
      });
    }
  }, [onServerExtract, apiBase, apiKey, setFiles, onTextExtracted]);

  const handleClientTextRead = useCallback((file, entryId, fileName) => {
    const reader = new FileReader();
    reader.onload = (e) => {
      const text = e.target.result;
      const lines = text.split('\n').length;
      setFiles((prev) =>
        prev.map((f) =>
          f.id === entryId ? { ...f, lineCount: lines, textPreview: text.slice(0, 200), extractedContent: text } : f
        )
      );

      if (onTextExtracted && text) {
        onTextExtracted(text, fileName);
      }
    };
    reader.onerror = () => {
      setFiles((prev) =>
        prev.map((f) =>
          f.id === entryId ? { ...f, extractionError: `Failed to read ${fileName}` } : f
        )
      );
    };
    reader.readAsText(file, 'utf-8');
  }, [setFiles, onTextExtracted]);

  const processFiles = useCallback((fileList) => {
    const newEntries = Array.from(fileList).map((file) => {
      const name = file.name;
      const ext = getExtension(name);
      const size = file.size;
      const id = `${name}-${size}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;

      const entry = {
        id,
        file,
        name,
        ext,
        size,
        isText: isTextFile(name),
        isExtractable: isExtractable(name),
        isBinary: isBinaryNonExtractable(name),
        lineCount: null,
        textPreview: null,
        serverExtracted: false,
        extractedContent: null,
        extractionError: null,
      };

      if (isTextFile(name) && !isExtractable(name)) {
        handleClientTextRead(file, id, name);
      }

      if (isExtractable(name)) {
        handleServerExtraction(file, id);
      }

      return entry;
    });

    setFiles((prev) => [...prev, ...newEntries]);
  }, [setFiles, handleClientTextRead, handleServerExtraction]);

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

  const handleDrop = useCallback((e) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragOver(false);
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      processFiles(e.dataTransfer.files);
    }
  }, [processFiles]);

  const handleFileInputChange = useCallback((e) => {
    if (e.target.files && e.target.files.length > 0) {
      processFiles(e.target.files);
      e.target.value = '';
    }
  }, [processFiles]);

  const handleRemoveFile = useCallback((id) => {
    setFiles((prev) => prev.filter((f) => f.id !== id));
  }, [setFiles]);

  const handleClickUpload = useCallback(() => {
    if (fileInputRef.current) {
      fileInputRef.current.click();
    }
  }, []);

  const handleRetryExtraction = useCallback((entry) => {
    if (entry.file && entry.isExtractable) {
      handleServerExtraction(entry.file, entry.id);
    }
  }, [handleServerExtraction]);

  return (
    <div style={{ width: '100%' }}>
      {/* Deprecation notice for developers */}
      {/* This component is deprecated for BuildTab. Use FileAttachmentArea.jsx instead. */}

      {/* Hidden file input — accept all file types */}
      <input
        ref={fileInputRef}
        type="file"
        multiple
        accept="*/*"
        onChange={handleFileInputChange}
        style={{ display: 'none' }}
      />

      {/* Drag-drop zone */}
      <div
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
        onClick={handleClickUpload}
        style={{
          border: `2px dashed ${isDragOver ? 'rgba(168, 85, 247, 0.8)' : 'rgba(107, 33, 168, 0.4)'}`,
          borderRadius: '12px',
          padding: '24px 16px',
          textAlign: 'center',
          cursor: 'pointer',
          backgroundColor: isDragOver ? 'rgba(168, 85, 247, 0.1)' : 'rgba(107, 33, 168, 0.05)',
          transition: 'all 0.2s ease',
          marginBottom: files.length > 0 ? '16px' : '0',
        }}
      >
        <div style={{ fontSize: '28px', marginBottom: '8px' }}>📎</div>
        <div style={{ fontSize: '14px', color: '#a78bfa', fontWeight: 600, marginBottom: '4px' }}>
          Drop files here or click to select
        </div>
        <div style={{ fontSize: '12px', color: '#6b7280' }}>
          .docx & .pdf extracted server-side • .py .js .toml .json .md .yml read client-side • Multiple files
        </div>
      </div>

      {/* File count header */}
      {files.length > 0 && (
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            marginBottom: '12px',
          }}
        >
          <span style={{ fontSize: '13px', color: '#a78bfa', fontWeight: 600 }
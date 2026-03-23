import React, { useState, useRef, useCallback } from 'react';

const TEXT_EXTENSIONS = new Set([
  'py', 'txt', 'md', 'rst', 'js', 'jsx', 'ts', 'tsx', 'html', 'css', 'scss',
  'less', 'json', 'yaml', 'yml', 'toml', 'ini', 'cfg', 'conf', 'env', 'sh',
  'bash', 'zsh', 'fish', 'bat', 'cmd', 'ps1', 'rb', 'go', 'rs', 'java',
  'kt', 'kts', 'scala', 'c', 'h', 'cpp', 'hpp', 'cs', 'swift', 'm', 'mm',
  'r', 'R', 'jl', 'lua', 'pl', 'pm', 'php', 'sql', 'graphql', 'gql',
  'proto', 'xml', 'svg', 'csv', 'tsv', 'log', 'diff', 'patch', 'makefile',
  'dockerfile', 'gitignore', 'gitattributes', 'editorconfig', 'prettierrc',
  'eslintrc', 'babelrc', 'webpack', 'vite', 'vue', 'svelte', 'astro',
  'mdx', 'tex', 'bib', 'srt', 'vtt', 'asm', 's', 'tf', 'hcl', 'nix',
  'ex', 'exs', 'erl', 'hrl', 'hs', 'lhs', 'ml', 'mli', 'clj', 'cljs',
  'cljc', 'edn', 'elm', 'purs', 'dart', 'v', 'sv', 'vhd', 'vhdl',
]);

const BINARY_EXTENSIONS = new Set(['pdf', 'docx', 'doc', 'xlsx', 'xls', 'pptx', 'ppt', 'zip', 'tar', 'gz', 'bz2', 'rar', '7z', 'png', 'jpg', 'jpeg', 'gif', 'bmp', 'ico', 'webp', 'mp3', 'mp4', 'wav', 'avi', 'mov', 'mkv', 'woff', 'woff2', 'ttf', 'otf', 'eot', 'exe', 'dll', 'so', 'dylib', 'bin', 'dat', 'db', 'sqlite']);

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
  // Default: treat unknown extensions as text
  return true;
}

function isExtractable(filename) {
  return EXTRACTABLE_EXTENSIONS.has(getExtension(filename));
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
    sql: { bg: 'rgba(14, 165, 233, 0.2)', border: 'rgba(14, 165, 233, 0.4)', text: '#7dd3fc' },
    docx: { bg: 'rgba(59, 130, 246, 0.2)', border: 'rgba(59, 130, 246, 0.4)', text: '#93c5fd' },
    pdf: { bg: 'rgba(239, 68, 68, 0.2)', border: 'rgba(239, 68, 68, 0.4)', text: '#fca5a5' },
    sh: { bg: 'rgba(34, 197, 94, 0.2)', border: 'rgba(34, 197, 94, 0.4)', text: '#86efac' },
    dockerfile: { bg: 'rgba(14, 165, 233, 0.2)', border: 'rgba(14, 165, 233, 0.4)', text: '#7dd3fc' },
    go: { bg: 'rgba(14, 165, 233, 0.2)', border: 'rgba(14, 165, 233, 0.4)', text: '#7dd3fc' },
    rs: { bg: 'rgba(234, 88, 12, 0.2)', border: 'rgba(234, 88, 12, 0.4)', text: '#fdba74' },
    java: { bg: 'rgba(239, 68, 68, 0.2)', border: 'rgba(239, 68, 68, 0.4)', text: '#fca5a5' },
    rb: { bg: 'rgba(239, 68, 68, 0.2)', border: 'rgba(239, 68, 68, 0.4)', text: '#fca5a5' },
  };
  const defaultColor = { bg: 'rgba(107, 33, 168, 0.2)', border: 'rgba(107, 33, 168, 0.4)', text: '#c4b5fd' };
  return colors[ext] || defaultColor;
}

/**
 * Read a single file's text content.
 * For text files, reads as UTF-8 text.
 * For .docx and .pdf, attempts basic text extraction client-side.
 * For other binary files, returns a placeholder note.
 */
function readFileContent(fileEntry) {
  return new Promise((resolve) => {
    const { file, name } = fileEntry;
    const ext = getExtension(name);

    if (ext === 'pdf') {
      // PDF: read as text with basic extraction attempt
      const reader = new FileReader();
      reader.onload = (e) => {
        try {
          const text = e.target.result;
          // Try to extract readable text from PDF binary
          // This is a basic approach; for full extraction, a library like pdf.js would be needed
          const extracted = extractTextFromPDFBinary(text);
          if (extracted && extracted.trim().length > 20) {
            resolve({ name, content: extracted });
          } else {
            resolve({ name, content: `[Binary PDF file: ${name} — ${formatFileSize(file.size)}. Upload to server for full text extraction.]` });
          }
        } catch {
          resolve({ name, content: `[Binary PDF file: ${name} — ${formatFileSize(file.size)}. Upload to server for full text extraction.]` });
        }
      };
      reader.onerror = () => {
        resolve({ name, content: `[Error reading file: ${name}]` });
      };
      reader.readAsText(file, 'utf-8');
      return;
    }

    if (ext === 'docx') {
      // DOCX: read as ArrayBuffer and extract text from XML parts
      const reader = new FileReader();
      reader.onload = async (e) => {
        try {
          const extracted = await extractTextFromDocx(e.target.result);
          if (extracted && extracted.trim().length > 0) {
            resolve({ name, content: extracted });
          } else {
            resolve({ name, content: `[DOCX file: ${name} — ${formatFileSize(file.size)}. Upload to server for full text extraction.]` });
          }
        } catch {
          resolve({ name, content: `[DOCX file: ${name} — ${formatFileSize(file.size)}. Upload to server for full text extraction.]` });
        }
      };
      reader.onerror = () => {
        resolve({ name, content: `[Error reading file: ${name}]` });
      };
      reader.readAsArrayBuffer(file);
      return;
    }

    if (isTextFile(name)) {
      const reader = new FileReader();
      reader.onload = (e) => {
        resolve({ name, content: e.target.result });
      };
      reader.onerror = () => {
        resolve({ name, content: `[Error reading file: ${name}]` });
      };
      reader.readAsText(file, 'utf-8');
      return;
    }

    // Binary file — can't extract text client-side
    resolve({ name, content: `[Binary file: ${name} — ${formatFileSize(file.size)}]` });
  });
}

/**
 * Basic PDF text extraction from raw binary string.
 * Extracts text between BT/ET blocks. This is rudimentary; 
 * for production use, pdf.js or server-side extraction is recommended.
 */
function extractTextFromPDFBinary(raw) {
  const lines = [];
  // Look for text in parentheses within BT...ET blocks
  const btEtRegex = /BT\s([\s\S]*?)ET/g;
  let match;
  while ((match = btEtRegex.exec(raw)) !== null) {
    const block = match[1];
    const textRegex = /\(([^)]*)\)/g;
    let textMatch;
    while ((textMatch = textRegex.exec(block)) !== null) {
      const decoded = textMatch[1]
        .replace(/\\n/g, '\n')
        .replace(/\\r/g, '')
        .replace(/\\\\/g, '\\')
        .replace(/\\([()])/g, '$1');
      if (decoded.trim()) {
        lines.push(decoded);
      }
    }
  }
  return lines.join(' ');
}

/**
 * Basic DOCX text extraction.
 * DOCX files are ZIP archives containing XML. We look for word/document.xml
 * and extract text from <w:t> tags.
 */
async function extractTextFromDocx(arrayBuffer) {
  try {
    // Use the browser's built-in JSZip-like capabilities or manual ZIP parsing
    // For simplicity, we use a basic approach to find XML content
    const uint8 = new Uint8Array(arrayBuffer);
    const text = new TextDecoder('utf-8', { fatal: false }).decode(uint8);

    // Find XML content within the DOCX ZIP
    const paragraphs = [];
    const wtRegex = /<w:t[^>]*>([^<]*)<\/w:t>/g;
    let match;
    while ((match = wtRegex.exec(text)) !== null) {
      if (match[1]) {
        paragraphs.push(match[1]);
      }
    }

    if (paragraphs.length > 0) {
      return paragraphs.join(' ');
    }

    return '';
  } catch {
    return '';
  }
}

/**
 * Read all files and combine their contents into labeled sections.
 * Returns a string with format:
 * === filename.ext ===
 * <file contents>
 * 
 * For each file.
 */
export async function combineFileContents(fileEntries) {
  if (!fileEntries || fileEntries.length === 0) return '';

  const results = await Promise.all(fileEntries.map(readFileContent));
  const sections = results.map(({ name, content }) => {
    return `=== ${name} ===\n${content}`;
  });

  return sections.join('\n\n');
}

/**
 * Read all file contents and return as an array of { name, content } objects.
 */
export async function readAllFileContents(fileEntries) {
  if (!fileEntries || fileEntries.length === 0) return [];
  return Promise.all(fileEntries.map(readFileContent));
}

export default function FileUploadGrid({ files, setFiles }) {
  const [isDragOver, setIsDragOver] = useState(false);
  const fileInputRef = useRef(null);

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
        lineCount: null,
        textPreview: null,
      };

      // For text files, read line count
      if (isTextFile(name) && !isExtractable(name)) {
        const reader = new FileReader();
        reader.onload = (e) => {
          const text = e.target.result;
          const lines = text.split('\n').length;
          setFiles((prev) =>
            prev.map((f) =>
              f.id === id ? { ...f, lineCount: lines, textPreview: text.slice(0, 200) } : f
            )
          );
        };
        reader.readAsText(file, 'utf-8');
      }

      return entry;
    });

    setFiles((prev) => [...prev, ...newEntries]);
  }, [setFiles]);

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
      // Reset input so same file can be re-selected
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

  return (
    <div style={{ width: '100%' }}>
      {/* Hidden file input */}
      <input
        ref={fileInputRef}
        type="file"
        multiple
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
          Any file type • Multiple files • Unlimited
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
            paddingLeft: '4px',
          }}
        >
          <span style={{ fontSize: '13px', color: '#a78bfa', fontWeight: 600 }}>
            {files.length} file{files.length !== 1 ? 's' : ''} attached
          </span>
          <button
            onClick={(e) => {
              e.stopPropagation();
              setFiles([]);
            }}
            style={{
              fontSize: '11px',
              color: '#ef4444',
              background: 'rgba(239, 68, 68, 0.1)',
              border: '1px solid rgba(239, 68, 68, 0.3)',
              borderRadius: '6px',
              padding: '4px 10px',
              cursor: 'pointer',
              transition: 'all 0.15s ease',
            }}
            onMouseEnter={(e) => {
              e.target.style.background = 'rgba(239, 68, 68, 0.2)';
            }}
            onMouseLeave={(e) => {
              e.target.style.background = 'rgba(239, 68, 68, 0.1)';
            }}
          >
            Clear all
          </button>
        </div>
      )}

      {/* File grid */}
      {files.length > 0 && (
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fill, minmax(180px, 1fr))',
            gap: '10px',
          }}
        >
          {files.map((entry) => {
            const badgeColor = getBadgeColor(entry.ext);
            const displayExt = entry.ext ? entry.ext.toUpperCase() : 'FILE';

            return (
              <div
                key={entry.id}
                style={{
                  position: 'relative',
                  backgroundColor: 'rgba(15, 11, 26, 0.8)',
                  border: '1px solid rgba(107, 33, 168, 0.25)',
                  borderRadius: '10px',
                  padding: '12px',
                  display: 'flex',
                  flexDirection: 'column',
                  gap: '8px',
                  transition: 'border-color 0.15s ease',
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.borderColor = 'rgba(168, 85, 247, 0.5)';
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.borderColor = 'rgba(107, 33, 168, 0.25)';
                }}
              >
                {/* Remove button */}
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    handleRemoveFile(entry.id);
                  }}
                  style={{
                    position: 'absolute',
                    top: '6px',
                    right: '6px',
                    width: '20px',
                    height: '20px',
                    borderRadius: '50%',
                    border: '1px solid rgba(239, 68, 68, 0.3)',
                    background: 'rgba(239, 68, 68, 0.1)',
                    color: '#ef4444',
                    fontSize: '12px',
                    lineHeight: '1',
                    cursor: 'pointer',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    padding: 0,
                    transition: 'all 0.15s ease',
                  }}
                  onMouseEnter={(e) => {
                    e.target.style.background = 'rgba(239, 68, 68, 0.3)';
                    e.target.style.color = '#fca5a5';
                  }}
                  onMouseLeave={(e) => {
                    e.target.style.background = 'rgba(239, 68, 68, 0.1)';
                    e.target.style.color = '#ef4444';
                  }}
                  title={`Remove ${entry.name}`}
                  aria-label={`Remove ${entry.name}`}
                >
                  ✕
                </button>

                {/* Extension badge */}
                <span
                  style={{
                    display: 'inline-block',
                    alignSelf: 'flex-start',
                    fontSize: '10px',
                    fontWeight: 700,
                    letterSpacing: '0.5px',
                    padding: '2px 8px',
                    borderRadius: '4px',
                    backgroundColor: badgeColor.bg,
                    border: `1px solid ${badgeColor.border}`,
                    color: badgeColor.text,
                    fontFamily: 'monospace',
                  }}
                >
                  {displayExt}
                </span>

                {/* Filename */}
                <div
                  style={{
                    fontSize: '12px',
                    fontWeight: 600,
                    color: '#e2e8f0',
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                    whiteSpace: 'nowrap',
                    paddingRight: '16px',
                  }}
                  title={entry.name}
                >
                  {entry.name}
                </div>

                {/* File info: line count for text, size for binary */}
                <div style={{ fontSize: '11px', color: '#6b7280' }}>
                  {entry.isText && !entry.isExtractable ? (
                    entry.lineCount !== null ? (
                      <span>{entry.lineCount.toLocaleString()} lines • {formatFileSize(entry.size)}</span>
                    ) : (
                      <span>Reading... • {formatFileSize(entry.size)}</span>
                    )
                  ) : entry.isExtractable ? (
                    <span>📄 Extractable • {formatFileSize(entry.size)}</span>
                  ) : (
                    <span>{formatFileSize(entry.size)}</span>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
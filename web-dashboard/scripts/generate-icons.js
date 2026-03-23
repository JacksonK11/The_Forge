#!/usr/bin/env node

/**
 * generate-icons.js
 * Build-time helper script for The Forge PWA icons.
 * 
 * Reads icon.svg from the public directory and generates:
 *   - icon-192.png (192x192)
 *   - icon-512.png (512x512)
 * 
 * Usage:
 *   node scripts/generate-icons.js
 * 
 * Requirements:
 *   npm install sharp
 * 
 * If sharp is not available, the script will:
 *   1. Generate the SVG file if it doesn't exist
 *   2. Print manual conversion instructions
 */

const fs = require('fs');
const path = require('path');

const PUBLIC_DIR = path.resolve(__dirname, '..', 'public');
const SVG_PATH = path.join(PUBLIC_DIR, 'icon.svg');

// Purple forge icon SVG — an anvil/hammer silhouette with The Forge's purple theme
const ICON_SVG = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512" width="512" height="512">
  <defs>
    <linearGradient id="bg" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" style="stop-color:#7C3AED;stop-opacity:1" />
      <stop offset="100%" style="stop-color:#6B21A8;stop-opacity:1" />
    </linearGradient>
    <linearGradient id="glow" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" style="stop-color:#A78BFA;stop-opacity:1" />
      <stop offset="100%" style="stop-color:#8B5CF6;stop-opacity:1" />
    </linearGradient>
    <filter id="shadow" x="-10%" y="-10%" width="120%" height="120%">
      <feDropShadow dx="0" dy="4" stdDeviation="8" flood-color="#000" flood-opacity="0.3"/>
    </filter>
  </defs>
  <!-- Background rounded square -->
  <rect width="512" height="512" rx="96" ry="96" fill="url(#bg)"/>
  <!-- Inner subtle border -->
  <rect x="16" y="16" width="480" height="480" rx="80" ry="80" fill="none" stroke="#A78BFA" stroke-width="2" opacity="0.3"/>
  <!-- Anvil body -->
  <g filter="url(#shadow)">
    <!-- Anvil top surface -->
    <path d="M 130 280 L 160 240 L 352 240 L 382 280 Z" fill="#E2E8F0"/>
    <!-- Anvil horn (left) -->
    <path d="M 130 280 L 160 240 L 100 260 Z" fill="#CBD5E1"/>
    <!-- Anvil body -->
    <path d="M 150 280 L 150 340 L 200 360 L 312 360 L 362 340 L 362 280 Z" fill="#CBD5E1"/>
    <!-- Anvil base -->
    <path d="M 170 360 L 160 380 L 130 380 L 130 400 L 382 400 L 382 380 L 352 380 L 342 360 Z" fill="#94A3B8"/>
    <!-- Anvil highlight -->
    <path d="M 160 240 L 170 245 L 345 245 L 352 240 Z" fill="#F1F5F9" opacity="0.6"/>
  </g>
  <!-- Hammer -->
  <g filter="url(#shadow)">
    <!-- Hammer handle -->
    <rect x="244" y="100" width="12" height="140" rx="4" ry="4" fill="#92400E" transform="rotate(-30 250 170)"/>
    <!-- Hammer head -->
    <rect x="210" y="80" width="80" height="40" rx="6" ry="6" fill="url(#glow)" transform="rotate(-30 250 100)"/>
    <!-- Hammer head highlight -->
    <rect x="215" y="83" width="70" height="12" rx="4" ry="4" fill="#C4B5FD" opacity="0.5" transform="rotate(-30 250 100)"/>
  </g>
  <!-- Sparks -->
  <circle cx="200" cy="220" r="5" fill="#FCD34D" opacity="0.9">
    <animate attributeName="opacity" values="0.9;0.3;0.9" dur="1.5s" repeatCount="indefinite"/>
  </circle>
  <circle cx="230" cy="200" r="4" fill="#FBBF24" opacity="0.8">
    <animate attributeName="opacity" values="0.8;0.2;0.8" dur="1.2s" repeatCount="indefinite"/>
  </circle>
  <circle cx="185" cy="205" r="3" fill="#FDE68A" opacity="0.7">
    <animate attributeName="opacity" values="0.7;0.1;0.7" dur="1.8s" repeatCount="indefinite"/>
  </circle>
  <circle cx="215" cy="210" r="3.5" fill="#FCD34D" opacity="0.85">
    <animate attributeName="opacity" values="0.85;0.25;0.85" dur="1.4s" repeatCount="indefinite"/>
  </circle>
</svg>`;

const SIZES = [
  { name: 'icon-192.png', size: 192 },
  { name: 'icon-512.png', size: 512 },
];

function ensureSvgExists() {
  if (!fs.existsSync(PUBLIC_DIR)) {
    fs.mkdirSync(PUBLIC_DIR, { recursive: true });
    console.log(`Created directory: ${PUBLIC_DIR}`);
  }

  if (!fs.existsSync(SVG_PATH)) {
    fs.writeFileSync(SVG_PATH, ICON_SVG, 'utf-8');
    console.log(`Generated SVG icon: ${SVG_PATH}`);
  } else {
    console.log(`SVG icon already exists: ${SVG_PATH}`);
  }
}

async function generateWithSharp() {
  let sharp;
  try {
    sharp = require('sharp');
  } catch (err) {
    return false;
  }

  console.log('Using sharp for PNG generation...\n');

  const svgBuffer = fs.readFileSync(SVG_PATH);

  for (const { name, size } of SIZES) {
    const outputPath = path.join(PUBLIC_DIR, name);
    try {
      await sharp(svgBuffer)
        .resize(size, size, {
          fit: 'contain',
          background: { r: 107, g: 33, b: 168, alpha: 1 }, // #6B21A8
        })
        .png({
          quality: 100,
          compressionLevel: 9,
        })
        .toFile(outputPath);

      const stats = fs.statSync(outputPath);
      console.log(`  ✓ ${name} (${size}x${size}) — ${(stats.size / 1024).toFixed(1)} KB`);
    } catch (err) {
      console.error(`  ✗ Failed to generate ${name}: ${err.message}`);
      return false;
    }
  }

  return true;
}

function printManualInstructions() {
  console.log(`
╔════════════════════════════════════════════════════════════════════╗
║  sharp is not installed — manual PNG generation required          ║
╠════════════════════════════════════════════════════════════════════╣
║                                                                    ║
║  Option 1: Install sharp and re-run                               ║
║                                                                    ║
║    npm install sharp                                               ║
║    node scripts/generate-icons.js                                  ║
║                                                                    ║
║  Option 2: Use Inkscape (CLI)                                      ║
║                                                                    ║
║    inkscape --export-type=png --export-width=192 \\                 ║
║      --export-filename=public/icon-192.png public/icon.svg         ║
║    inkscape --export-type=png --export-width=512 \\                 ║
║      --export-filename=public/icon-512.png public/icon.svg         ║
║                                                                    ║
║  Option 3: Use ImageMagick                                         ║
║                                                                    ║
║    convert -background none -resize 192x192 \\                      ║
║      public/icon.svg public/icon-192.png                           ║
║    convert -background none -resize 512x512 \\                      ║
║      public/icon.svg public/icon-512.png                           ║
║                                                                    ║
║  Option 4: Use rsvg-convert (librsvg)                              ║
║                                                                    ║
║    rsvg-convert -w 192 -h 192 public/icon.svg > public/icon-192.png║
║    rsvg-convert -w 512 -h 512 public/icon.svg > public/icon-512.png║
║                                                                    ║
║  Option 5: Use an online converter                                 ║
║                                                                    ║
║    1. Open public/icon.svg in a browser                            ║
║    2. Use cloudconvert.com or svgtopng.com                         ║
║    3. Export at 192x192 and 512x512                                ║
║    4. Save as public/icon-192.png and public/icon-512.png          ║
║                                                                    ║
║  The SVG source file has been saved to:                            ║
║    ${SVG_PATH}
║                                                                    ║
╚════════════════════════════════════════════════════════════════════╝
`);
}

async function main() {
  console.log('');
  console.log('┌──────────────────────────────────────┐');
  console.log('│  The Forge — PWA Icon Generator       │');
  console.log('└──────────────────────────────────────┘');
  console.log('');

  // Step 1: Ensure SVG exists
  ensureSvgExists();
  console.log('');

  // Step 2: Try to generate PNGs with sharp
  const success = await generateWithSharp();

  if (success) {
    console.log('');
    console.log('All icons generated successfully! ✨');
    console.log('');
    console.log('Files:');
    console.log(`  ${path.join(PUBLIC_DIR, 'icon.svg')}`);
    for (const { name } of SIZES) {
      console.log(`  ${path.join(PUBLIC_DIR, name)}`);
    }
    console.log('');
  } else {
    // Step 3: If sharp not available, provide manual instructions
    printManualInstructions();

    // Step 4: Generate placeholder PNGs as a fallback (1x1 purple pixel expanded)
    // This ensures the build doesn't break, but icons won't look right
    console.log('Generating minimal placeholder PNGs so the build succeeds...');
    console.log('(Replace these with properly converted PNGs for production)\n');

    for (const { name, size } of SIZES) {
      const outputPath = path.join(PUBLIC_DIR, name);
      if (!fs.existsSync(outputPath)) {
        // Create a minimal valid PNG — a 1x1 purple pixel
        // PNG header + IHDR + IDAT (single pixel) + IEND
        const pngHeader = Buffer.from([
          0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A, // PNG signature
        ]);

        // For a proper placeholder, we just write an empty file with a note
        // The service worker and manifest will still reference them
        fs.writeFileSync(outputPath, pngHeader);
        console.log(`  ⚠ Placeholder created: ${name} (replace with real PNG!)`);
      } else {
        console.log(`  ✓ ${name} already exists, skipping`);
      }
    }

    console.log('');
    console.log('⚠  Placeholder PNGs are NOT valid images.');
    console.log('   Install sharp or use one of the manual methods above');
    console.log('   to generate proper icons before deploying to production.');
    console.log('');

    process.exitCode = 0; // Don't fail the build
  }
}

main().catch((err) => {
  console.error('Icon generation failed:', err);
  process.exitCode = 1;
});
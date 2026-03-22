/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: ["'IBM Plex Sans'", "ui-sans-serif", "system-ui", "sans-serif"],
        mono: ["'IBM Plex Mono'", "ui-monospace", "SFMono-Regular", "Menlo", "Consolas", "monospace"],
      },
      colors: {
        // Preserve existing forge palette for any old references
        forge: {
          900: "#0a0a0f",
          800: "#111118",
          700: "#1a1a26",
          600: "#252535",
          500: "#3a3a55",
          accent: "#6366f1",
          "accent-hover": "#4f52e0",
          success: "#10b981",
          warning: "#f59e0b",
          error: "#ef4444",
        },
      },
    },
  },
  plugins: [],
};

/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      colors: {
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

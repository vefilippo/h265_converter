export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bg: "#1a1d24",
        surface: "#20242c",
        elevated: "#161920",
        border: "#2c313a",
        fg: "#e8eaed",
        muted: "#9aa0aa",
        accent: { DEFAULT: "#10b981", hover: "#0ea371", fg: "#04140d" },
        state: {
          queued: "#64748b", running: "#10b981", done: "#16a34a",
          failed: "#ef4444", skipped: "#f59e0b", cancelled: "#71717a",
        },
      },
      fontFamily: {
        sans: ['Inter', 'ui-sans-serif', 'system-ui', 'sans-serif'],
        display: ['"Space Grotesk"', 'ui-sans-serif', 'sans-serif'],
        mono: ['"JetBrains Mono"', 'ui-monospace', 'monospace'],
      },
    },
  },
  plugins: [],
};

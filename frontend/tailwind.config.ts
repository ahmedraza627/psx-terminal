// Minimal project configuration for tailwind (no tailwindcss types available in this repo).
// This config is intentionally minimal to satisfy the build without external deps.
const config = {
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
    "./lib/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {},
  },
  plugins: [],
};

export default config;

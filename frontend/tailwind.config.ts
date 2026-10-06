import type { Config } from "tailwindcss";

/**
 * PSX Quant Terminal — institutional design tokens.
 *
 * Palette contract (executive slate navy, machined hairlines):
 *   obsidian  #0B0F19  root background (deep slate navy)
 *   panel     #1E293B  surface / panel tiling (refined slate)
 *   hairline  #334155  1px borders — the ONLY border color in the app
 *   hoverline #16202F  interactive hover fill (recessed vs panel)
 *   ink       #F8FAFC  primary active text (off-white)
 *   muted     #CBD5E1  secondary labels / table data (slate-300)
 *   ghost     #64748B  ghost / inactive badges (slate-500)
 *   bull      #10B981  smart accumulation (emerald-500)
 *   bullbright #34D399 bright emerald accent (emerald-400)
 *   bear      #EF4444  distribution / stop violation (crimson)
 *   warn      #F59E0B  transition / caution (amber-500)
 *   info      #38BDF8  accent / active states (electric sky)
 */
const config: Config = {
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
    "./lib/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        obsidian: "#0B0F19",
        panel: "#1E293B",
        hairline: "#334155",
        hoverline: "#16202F",
        ink: "#F8FAFC",
        muted: "#CBD5E1",
        ghost: "#64748B",
        bull: "#10B981",
        bullbright: "#34D399",
        bear: "#EF4444",
        warn: "#F59E0B",
        info: "#38BDF8",
      },
      fontFamily: {
        mono: [
          "IBM Plex Mono",
          "SFMono-Regular",
          "Menlo",
          "Consolas",
          "Liberation Mono",
          "monospace",
        ],
        sans: [
          "Inter",
          "-apple-system",
          "Segoe UI",
          "Roboto",
          "Helvetica Neue",
          "Arial",
          "sans-serif",
        ],
      },
    },
  },
  plugins: [],
};

export default config;

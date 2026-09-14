import type { Config } from "tailwindcss";

/**
 * PSX Quant Terminal — institutional design tokens.
 *
 * Palette contract (matte obsidian, zero glow):
 *   obsidian  #090A0C  root background
 *   panel     #111318  surface / panel tiling
 *   hairline  #1E222B  1px borders — the ONLY border color in the app
 *   hoverline #161922  interactive hover fill
 *   ink       #E6EDF3  primary active text
 *   muted     #848E9C  secondary labels (cold stainless)
 *   ghost     #484F58  ghost / inactive badges
 *   bull      #26A69A  smart accumulation (muted emerald; #00D084 accent)
 *   bear      #F23645  distribution / stop violation (brick red)
 *   warn      #E5A93C  transition / caution (amber gold)
 *   info      #388BFD  benchmark / system neutral (Refinitiv cyan)
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
        obsidian: "#090A0C",
        panel: "#111318",
        hairline: "#1E222B",
        hoverline: "#161922",
        ink: "#E6EDF3",
        muted: "#848E9C",
        ghost: "#484F58",
        bull: "#26A69A",
        bullbright: "#00D084",
        bear: "#F23645",
        warn: "#E5A93C",
        info: "#388BFD",
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

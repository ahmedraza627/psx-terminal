import type { Config } from "tailwindcss";

/**
 * PSX Quant Terminal — design tokens.
 *
 * Palette contract (professional light SaaS — Linear / Stripe style):
 *   obsidian  #F1F5F9  root background (soft slate-blue tint)
 *   panel     #FFFFFF  surface / card tiling (crisp white)
 *   hairline  #E2E8F0  1px borders — slate-200, the ONLY border color
 *   hoverline #F1F5F9  interactive hover fill (recessed vs white cards)
 *   ink       #0F172A  primary headers (deep charcoal slate-900)
 *   muted     #475569  secondary text / table data (slate-600)
 *   ghost     #94A3B8  faint labels / inactive badges (slate-400)
 *   bull      #059669  bullish verdicts (emerald-600 text)
 *   bullbright #10B981 bright emerald accent (emerald-500)
 *   bear      #E11D48  bearish verdicts (rose-600 text)
 *   warn      #D97706  transition / caution (amber-600)
 *   info      #2563EB  royal blue — primary actions / active tabs (blue-600)
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
        obsidian: "#F1F5F9",
        panel: "#FFFFFF",
        hairline: "#E2E8F0",
        hoverline: "#F1F5F9",
        ink: "#0F172A",
        muted: "#475569",
        ghost: "#94A3B8",
        bull: "#059669",
        bullbright: "#10B981",
        bear: "#E11D48",
        warn: "#D97706",
        info: "#2563EB",
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

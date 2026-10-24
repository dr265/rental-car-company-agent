import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#0d1117",
        ink2: "#131920",
        ink3: "#1a222c",
        ivory: "#eef2f7",
        brass: "#d6b36a",
        jewel: "#e08a2e",
        saffron: "#e08a2e",
        wine: "#232b36",
        cream: "#eef2f7",
        // customer website palette (index.html design language)
        zoomDark: {
          950: "#07090E",
          900: "#0D111A",
          850: "#111723",
          800: "#161E2E",
          700: "#222E45",
        },
        zoomBlue: {
          400: "#38BDF8",
          500: "#0284C7",
          600: "#0369A1",
        },
        zoomGold: {
          400: "#FBBF24",
          500: "#F59E0B",
          600: "#D97706",
        },
      },
      fontFamily: {
        serif: ["Instrument Serif", "Georgia", "serif"],
        mono: ["JetBrains Mono", "ui-monospace", "monospace"],
        heading: ["Space Grotesk", "ui-sans-serif", "sans-serif"],
        sans: ["Plus Jakarta Sans", "ui-sans-serif", "system-ui", "sans-serif"],
      },
    },
  },
  plugins: [],
};
export default config;

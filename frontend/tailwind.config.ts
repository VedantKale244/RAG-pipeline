import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
    "./pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      fontFamily: {
        sans: ["Inter", "-apple-system", "BlinkMacSystemFont", "Segoe UI", "sans-serif"],
        mono: ["JetBrains Mono", "Menlo", "Monaco", "Consolas", "monospace"],
      },
      colors: {
        // Page & surface
        bg:       { DEFAULT: "#EEEEE8", card: "#FFFFFF", subtle: "#F5F5F0" },
        // Forest green primary — matches header & CTA button
        forest:   {
          900: "#0F2D1E",
          800: "#163526",
          700: "#1B4232",
          600: "#21543F",
          500: "#2A6B50",
          400: "#358060",
          300: "#4A9E78",
          200: "#A3C8B5",
          100: "#DCF0E7",
          50:  "#F0F9F4",
        },
        // Neutral grays
        ink:      { DEFAULT: "#1A1A1A", 700: "#374151", 500: "#6B7280", 400: "#9CA3AF", 300: "#D1D5DB", 200: "#E5E7EB", 100: "#F3F4F6" },
        // Accent mint for info boxes
        mint:     { DEFAULT: "#E8F5EE", border: "#C3E0D0", text: "#1B5E3B" },
        // Accent red for errors
        danger:   { DEFAULT: "#FEF2F2", border: "#FECACA", text: "#B91C1C" },
      },
      boxShadow: {
        card:   "0 1px 3px 0 rgba(0,0,0,0.08), 0 1px 2px -1px rgba(0,0,0,0.06)",
        "card-md": "0 4px 12px 0 rgba(0,0,0,0.10)",
        "btn-green": "0 2px 8px rgba(26,66,46,0.30)",
        pill:   "0 1px 4px rgba(0,0,0,0.10)",
      },
      borderRadius: {
        "2xl": "1rem",
        "3xl": "1.25rem",
      },
    },
  },
  plugins: [],
};

export default config;

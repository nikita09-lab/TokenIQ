/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        brand: {
          dark: '#080A0F',
          surface: '#0E131F',
          card: '#121826',
          panel: '#151D2E',
          border: 'rgba(255, 255, 255, 0.07)',
          borderLight: 'rgba(255, 255, 255, 0.12)',
          accent: '#00F0FF',
          accentGlow: 'rgba(0, 240, 255, 0.15)',
          blue: '#3B82F6',
          up: '#10B981',
          upGlow: 'rgba(16, 185, 129, 0.15)',
          down: '#F43F5E',
          downGlow: 'rgba(244, 63, 94, 0.15)',
          muted: '#94A3B8',
          subtle: '#64748B',
        }
      },
      fontFamily: {
        sans: ['Inter', '-apple-system', 'BlinkMacSystemFont', 'Segoe UI', 'Roboto', 'sans-serif'],
        mono: ['JetBrains Mono', 'Fira Code', 'Roboto Mono', 'monospace'],
      },
      boxShadow: {
        'glow-cyan': '0 0 20px -3px rgba(0, 240, 255, 0.25)',
        'glow-green': '0 0 15px -3px rgba(16, 185, 129, 0.25)',
        'glow-red': '0 0 15px -3px rgba(244, 63, 94, 0.25)',
      },
      animation: {
        'pulse-slow': 'pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite',
        'flash-green': 'flashGreen 0.6s ease-out',
        'flash-red': 'flashRed 0.6s ease-out',
      },
      keyframes: {
        flashGreen: {
          '0%': { backgroundColor: 'rgba(16, 185, 129, 0.25)' },
          '100%': { backgroundColor: 'transparent' },
        },
        flashRed: {
          '0%': { backgroundColor: 'rgba(244, 63, 94, 0.25)' },
          '100%': { backgroundColor: 'transparent' },
        }
      }
    },
  },
  plugins: [],
}

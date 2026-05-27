/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx,ts,tsx}'],
  theme: {
    extend: {
      colors: {
        // ── Core palette (mirrors CSS vars in jcf_hq.html) ──────────────
        gold:        '#c9a84c',
        'gold-light': '#e8c96a',
        navy:        '#070c1a',
        'navy-mid':  '#0d1528',

        // ── Semantic accents ─────────────────────────────────────────────
        profit:  '#4ade80',   // --green
        loss:    '#f87171',   // --red
        info:    '#60a5fa',   // --blue
        accent:  '#a78bfa',   // --purple
        cyan:    '#22d3ee',
        orange:  '#fb923c',
      },

      fontFamily: {
        display: ['"Playfair Display"', 'serif'],
        sans:    ['"DM Sans"', 'sans-serif'],
        mono:    ['"IBM Plex Mono"', 'monospace'],
      },

      // ── Glass card helpers ───────────────────────────────────────────
      backgroundColor: {
        glass: 'rgba(255,255,255,0.03)',
      },
      borderColor: {
        glass:      'rgba(201,168,76,0.12)',
        'glass-dim': 'rgba(201,168,76,0.08)',
      },

      // ── Text shades matching --text-* vars ───────────────────────────
      textColor: {
        primary: '#e8dfc8',
        dim:     'rgba(232,223,200,0.75)',
        muted:   'rgba(232,223,200,0.55)',
      },

      // ── Sidebar width ────────────────────────────────────────────────
      width: {
        sidebar: '220px',
      },

      // ── Keyframe animations ──────────────────────────────────────────
      keyframes: {
        pulse: {
          '0%,100%': { opacity: '1' },
          '50%':     { opacity: '0.4' },
        },
        glow: {
          '0%,100%': { boxShadow: '0 0 10px rgba(201,168,76,0.5)' },
          '50%':     { boxShadow: '0 0 20px rgba(201,168,76,0.2)' },
        },
        fadeIn: {
          from: { opacity: '0', transform: 'translateY(6px)' },
          to:   { opacity: '1', transform: 'translateY(0)' },
        },
      },
      animation: {
        'pulse-slow': 'pulse 2s ease-in-out infinite',
        'glow':       'glow 2s ease-in-out infinite',
        'fade-in':    'fadeIn 0.2s ease-out',
      },

      // ── Box shadows ──────────────────────────────────────────────────
      boxShadow: {
        gold:   '0 0 10px rgba(201,168,76,0.5)',
        green:  '0 0 8px rgba(74,222,128,0.4)',
        glass:  '0 8px 32px rgba(0,0,0,0.4)',
      },
    },
  },
  plugins: [],
}

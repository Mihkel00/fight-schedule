/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./templates/**/*.html",
  ],
  theme: {
    extend: {
      fontFamily: {
        'staatliches': ['"Staatliches"', 'Impact', 'sans-serif'],
        'work': ['"Work Sans"', 'sans-serif'],
      },
      colors: {
        'dark-bg': '#0a0a0a',
        'dark-card': '#141414',
        'dark-elevated': '#1a1a1a',
        'dark-border': '#252525',
        'text-primary': '#f5f5f5',
        'text-secondary': '#a8a8a8',
        'text-tertiary': '#737373',
        'accent-red': '#ef4444',
        'accent-orange': '#fb923c',
        'accent-blue': '#3b82f6',
        'accent-green': '#22c55e',
        'accent-red-custom': '#C00000',
      }
    }
  },
  plugins: [],
}

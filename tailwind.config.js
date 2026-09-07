/** Design system build config.
 * Source of truth for design tokens. The compiled stylesheet
 * (app/static/css/app.css) is committed so deployment needs no Node.
 *
 * Rebuild after editing HTML/JS classes or tokens:
 *   npx tailwindcss@3.4.17 -c tailwind.config.js -i app/static/src/input.css -o app/static/css/app.css --minify
 */
module.exports = {
  content: ['./app/static/**/*.{html,js}'],
  theme: {
    extend: {
      colors: {
        /* Single brand accent (emerald) aliased for future re-theming. */
        brand: {
          50: '#ecfdf5',
          100: '#d1fae5',
          200: '#a7f3d0',
          300: '#6ee7b7',
          400: '#34d399',
          500: '#10b981',
          600: '#059669',
          700: '#047857',
          800: '#065f46',
          900: '#064e3b',
          950: '#022c22',
        },
      },
      boxShadow: {
        /* Tinted, never pure black. */
        card: '0 1px 2px 0 rgb(5 150 105 / 0.04), 0 1px 3px 0 rgb(15 23 42 / 0.06)',
        lift: '0 10px 30px -12px rgb(5 150 105 / 0.35)',
      },
    },
  },
  plugins: [],
};

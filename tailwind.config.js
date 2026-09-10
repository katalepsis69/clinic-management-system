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
      fontFamily: {
        sans: ['"Plus Jakarta Sans"', 'system-ui', '-apple-system', 'BlinkMacSystemFont', '"Segoe UI"', 'Roboto', 'sans-serif'],
      },
      colors: {
        /* Calibrated Hospitality Wellness Sage palette */
        brand: {
          50: '#f4f8f5',
          100: '#e5efe7',
          200: '#cce0d2',
          300: '#a5c9af',
          400: '#77ab84',
          500: '#4e8d5e',
          600: '#2d6a3f',
          700: '#245432',
          800: '#1f432a',
          900: '#1b3724',
          950: '#0b1e13',
        },
      },
      boxShadow: {
        /* Tinted with warm stone and soft sage */
        card: '0 1px 3px 0 rgb(41 37 36 / 0.04), 0 1px 2px -1px rgb(41 37 36 / 0.04)',
        lift: '0 10px 25px -5px rgb(45 106 63 / 0.22), 0 8px 10px -6px rgb(45 106 63 / 0.22)',
      },
    },
  },
  plugins: [],
};

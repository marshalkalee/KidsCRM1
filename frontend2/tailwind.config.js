/** @type {import('tailwindcss').Config} */
export default {
    content: [
      "./index.html",
      "./src/**/*.{js,ts,jsx,tsx}",
    ],
    theme: {
      extend: {
        colors: {
          primary: {
            50: '#FDF6F0',
            100: '#FAE8E0',
            200: '#F5C6BD',
            300: '#EFA99A',
            400: '#E8998D',
            500: '#C97B6E',
            600: '#A85E52',
            700: '#8A4A3F',
            800: '#6B372E',
            900: '#4D261F',
          },
        },
        fontFamily: {
          sans: ['Rubik', 'sans-serif'],
        },
      },
    },
    plugins: [],
  }

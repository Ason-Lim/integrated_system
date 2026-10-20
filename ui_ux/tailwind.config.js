/** @type {import('tailwindcss').Config} */
// 색은 index.css 의 CSS 변수로 정의 → 다크 모드는 변수만 바꾼다.
const v = (name) => `rgb(var(--${name}) / <alpha-value>)`;
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        paper: v("paper"), surface: v("surface"), chip: v("chip"), line: v("line"),
        ink: v("ink"), ink2: v("ink2"), ink3: v("ink3"),
        accent: v("accent"), accentSoft: v("accent-soft"),
        warn: v("warn"), warnSoft: v("warn-soft"),
        sponsor: v("sponsor"), sponsorSoft: v("sponsor-soft"),
        review: v("review"), reviewSoft: v("review-soft"),
      },
      fontFamily: { sans: ['"Pretendard Variable"', "Pretendard", "system-ui", "sans-serif"] },
      borderRadius: { card: "18px" },
      boxShadow: { card: "0 1px 2px rgba(0,0,0,.04), 0 6px 24px rgba(0,0,0,.05)" },
      maxWidth: { chat: "780px" },
    },
  },
  plugins: [],
};

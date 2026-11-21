/** @type {import('tailwindcss').Config} */
import typography from '@tailwindcss/typography'

/**
 * 语义色板：把 Tailwind 的高饱和色系重写成主题令牌。
 *
 * 界面里历史遗留了大量 text-amber-600 / bg-rose-50 / border-emerald-200
 * 这类直接色号，主题插件切换后它们不会跟随。这里按语义整族映射：
 * - emerald / green / teal / lime → 成功色
 * - amber / orange / yellow → 警告色
 * - rose / red / pink / fuchsia → 危险色
 * - sky / blue / cyan / indigo → 信息色
 * - violet / purple → 强调色
 *
 * 浅色档位用低透明度叠出 tint（透明度修饰符会继续相乘），深色档位统一
 * 取令牌本色——单套令牌要在亮 / 暗主题下都成立，不能再按经典色阶分深浅。
 * 主题插件通过 theme.colors 的 status.* / accent 令牌覆盖这些颜色。
 */
const semanticPalette = (token) => ({
  50: `rgb(var(${token}) / calc(0.08 * <alpha-value>))`,
  100: `rgb(var(${token}) / calc(0.13 * <alpha-value>))`,
  200: `rgb(var(${token}) / calc(0.22 * <alpha-value>))`,
  300: `rgb(var(${token}) / calc(0.4 * <alpha-value>))`,
  400: `rgb(var(${token}) / <alpha-value>)`,
  500: `rgb(var(${token}) / <alpha-value>)`,
  600: `rgb(var(${token}) / <alpha-value>)`,
  700: `rgb(var(${token}) / <alpha-value>)`,
  800: `rgb(var(${token}) / <alpha-value>)`,
  900: `rgb(var(${token}) / <alpha-value>)`,
})

export default {
  content: ['./index.html', './src/**/*.{vue,ts}'],
  theme: {
    extend: {
      colors: {
        // 主题色由 CSS 变量驱动：编辑模式冷紫，学习模式转为青绿。
        kiwi: {
          50: 'rgb(var(--kiwi-50) / <alpha-value>)',
          100: 'rgb(var(--kiwi-100) / <alpha-value>)',
          200: 'rgb(var(--kiwi-200) / <alpha-value>)',
          300: 'rgb(var(--kiwi-300) / <alpha-value>)',
          400: 'rgb(var(--kiwi-400) / <alpha-value>)',
          500: 'rgb(var(--kiwi-500) / <alpha-value>)',
          600: 'rgb(var(--kiwi-600) / <alpha-value>)',
          700: 'rgb(var(--kiwi-700) / <alpha-value>)',
          800: 'rgb(var(--kiwi-800) / <alpha-value>)',
          900: 'rgb(var(--kiwi-900) / <alpha-value>)',
        },
        // 语义状态色板：界面组件直接使用这些色系即可自动跟随主题插件。
        emerald: semanticPalette('--theme-success'),
        green: semanticPalette('--theme-success'),
        teal: semanticPalette('--theme-success'),
        lime: semanticPalette('--theme-success'),
        amber: semanticPalette('--theme-warning'),
        orange: semanticPalette('--theme-warning'),
        yellow: semanticPalette('--theme-warning'),
        rose: semanticPalette('--theme-danger'),
        red: semanticPalette('--theme-danger'),
        pink: semanticPalette('--theme-danger'),
        fuchsia: semanticPalette('--theme-danger'),
        sky: semanticPalette('--theme-info'),
        blue: semanticPalette('--theme-info'),
        cyan: semanticPalette('--theme-info'),
        indigo: semanticPalette('--theme-info'),
        violet: semanticPalette('--theme-accent'),
        purple: semanticPalette('--theme-accent'),
      },
      fontFamily: {
        sans: ['"Inter"', '"Noto Sans SC"', 'system-ui', 'sans-serif'],
        mono: ['"JetBrains Mono"', 'ui-monospace', 'monospace'],
      },
      boxShadow: {
        soft: '0 1px 3px rgba(15, 23, 42, 0.04), 0 1px 2px rgba(15, 23, 42, 0.03)',
        lifted: '0 8px 24px rgba(15, 23, 42, 0.08), 0 2px 6px rgba(15, 23, 42, 0.04)',
        glow: '0 0 0 1px rgb(var(--kiwi-600) / 0.08), 0 8px 32px rgb(var(--kiwi-500) / 0.14)',
      },
      backdropBlur: {
        xs: '2px',
      },
      keyframes: {
        'fade-up': {
          from: { opacity: '0', transform: 'translateY(14px)' },
          to: { opacity: '1', transform: 'translateY(0)' },
        },
        'fade-in': {
          from: { opacity: '0' },
          to: { opacity: '1' },
        },
        'scale-in': {
          from: { opacity: '0', transform: 'scale(0.96)' },
          to: { opacity: '1', transform: 'scale(1)' },
        },
        'slide-in-right': {
          from: { opacity: '0', transform: 'translateX(16px)' },
          to: { opacity: '1', transform: 'translateX(0)' },
        },
        shimmer: {
          '0%': { backgroundPosition: '-200% 0' },
          '100%': { backgroundPosition: '200% 0' },
        },
        float: {
          '0%, 100%': { transform: 'translateY(0)' },
          '50%': { transform: 'translateY(-6px)' },
        },
        'caret-blink': {
          '0%, 80%, 100%': { opacity: '0' },
          '40%': { opacity: '1' },
        },
        'pulse-ring': {
          '0%': { boxShadow: '0 0 0 0 rgb(var(--kiwi-500) / 0.25)' },
          '70%': { boxShadow: '0 0 0 8px rgb(var(--kiwi-500) / 0)' },
          '100%': { boxShadow: '0 0 0 0 rgb(var(--kiwi-500) / 0)' },
        },
      },
      animation: {
        'fade-up': 'fade-up 0.5s cubic-bezier(0.21, 0.75, 0.28, 1) both',
        'fade-in': 'fade-in 0.4s ease-out both',
        'scale-in': 'scale-in 0.3s cubic-bezier(0.21, 0.75, 0.28, 1) both',
        'slide-in-right': 'slide-in-right 0.4s cubic-bezier(0.21, 0.75, 0.28, 1) both',
        shimmer: 'shimmer 1.6s linear infinite',
        float: 'float 5s ease-in-out infinite',
        'caret-blink': 'caret-blink 1.1s step-end infinite',
        'pulse-ring': 'pulse-ring 1.8s cubic-bezier(0.6, 0, 0.4, 1) infinite',
      },
      transitionTimingFunction: {
        spring: 'cubic-bezier(0.21, 0.75, 0.28, 1)',
      },
    },
  },
  plugins: [typography],
}
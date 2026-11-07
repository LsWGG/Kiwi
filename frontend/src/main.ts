import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import router from './router'
import { IS_DESKTOP } from './desktop/env'
import './styles/main.css'
// 主题兼容层：把 Tailwind 中性色工具类映射到主题令牌。
import './styles/theme.css'
// 画布手绘字体全局声明：编辑、阅读态 SVG、分享页共用同一内置字体。
import './assets/fonts/kiwi-hand.css'
// 画布文本设置里的字体族：西文随构建内置，中文映射系统字体。
import './assets/fonts/draw-fonts.css'
import { applyCachedTheme } from './theme/apply'

// 桌面构建使用 Windows 原生字体栈，避免下载 Google Fonts。
if (IS_DESKTOP) document.documentElement.classList.add('kiwi-desktop')

// 首屏立即套用缓存主题，避免等待接口时先闪默认配色。
applyCachedTheme()

const app = createApp(App)
app.use(createPinia())
app.use(router)
app.mount('#app')

// Web Push：Service Worker 只负责接收通知，不做离线缓存。
// 桌面版没有推送服务，不注册 SW，避免后台网络通道。
if (!IS_DESKTOP && 'serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js').catch((error) => {
      console.warn('Service Worker 注册失败，推送提醒不可用', error)
    })
  })
}
import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import router from './router'
import { IS_DESKTOP } from './desktop/env'
import './styles/main.css'

// 桌面构建使用 Windows 原生字体栈，避免下载 Google Fonts。
if (IS_DESKTOP) document.documentElement.classList.add('kiwi-desktop')

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
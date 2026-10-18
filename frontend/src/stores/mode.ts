import { defineStore } from 'pinia'
import { ref } from 'vue'

export type AppMode = 'edit' | 'learn'

/** 全局模式切换器状态（双模共享状态保存在 localStorage）。 */
export const useModeStore = defineStore('mode', () => {
  const mode = ref<AppMode>(
    (localStorage.getItem('kiwi.mode') as AppMode) || 'edit',
  )

  function setMode(m: AppMode) {
    mode.value = m
    localStorage.setItem('kiwi.mode', m)
  }

  return { mode, setMode }
})
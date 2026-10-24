import { defineStore } from 'pinia'
import { ref } from 'vue'
import { useKbsStore } from './kbs'

export type AppMode = 'edit' | 'learn'

/** 全局模式切换器状态（双模共享状态保存在 localStorage）。 */
export const useModeStore = defineStore('mode', () => {
  const mode = ref<AppMode>(
    (localStorage.getItem('kiwi.mode') as AppMode) || 'edit',
  )

  function setMode(m: AppMode) {
    if (m === mode.value) return
    // 编辑 / 学习切换沿用当前知识库；目标模式不支持该库时保留原选择。
    useKbsStore().carryActiveKb(m)
    mode.value = m
    localStorage.setItem('kiwi.mode', m)
  }

  return { mode, setMode }
})
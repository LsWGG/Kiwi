/**
 * 全局命令面板状态：Ctrl/⌘+K 在任意业务页面唤起，既检索笔记，也承载
 * 新建、导航、页内查找与「置顶插件组件」等快捷操作。Ctrl/⌘+Shift+P
 * 直接以「仅命令」模式打开（对应 VSCode 的快捷键习惯）。
 */
import { defineStore } from 'pinia'
import { ref } from 'vue'

export const useCommandPaletteStore = defineStore('commandPalette', () => {
  const open = ref(false)
  /** 本次打开是否只显示命令（输入框预填 `>`）。 */
  const commandsOnly = ref(false)

  function show(commands = false) {
    commandsOnly.value = commands
    open.value = true
  }
  function close() {
    open.value = false
    commandsOnly.value = false
  }
  function toggle() {
    if (open.value) {
      close()
      return
    }
    show(false)
  }

  return { open, commandsOnly, show, close, toggle }
})

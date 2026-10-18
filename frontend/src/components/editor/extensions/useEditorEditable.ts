import { onBeforeUnmount, ref, type Ref } from 'vue'
import type { Editor } from '@tiptap/core'

/**
 * editor.isEditable 是普通 getter，不是响应式值；阅读 / 编辑切换时
 * NodeView 里的 computed 不会自动刷新。监听 update 事件把它同步成 ref。
 */
export function useEditorEditable(editor: Editor): Ref<boolean> {
  const editable = ref(editor.isEditable)
  const sync = () => {
    editable.value = editor.isEditable
  }
  editor.on('update', sync)
  onBeforeUnmount(() => {
    editor.off('update', sync)
  })
  return editable
}

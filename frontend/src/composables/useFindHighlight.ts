/**
 * 把页内查找状态同步到 ProseMirror 装饰。
 *
 * 文档 / 链接面板的正文是 contenteditable，Firefox 不会为其中的
 * CSS Custom Highlight 着色，因此这两个面板必须由编辑器装饰接管；
 * 其他笔记类型与只读 DOM 由查找条直接用 Highlight API 绘制。
 */
import { onBeforeUnmount, watch, type Ref } from 'vue'
import { useNoteFindStore } from '@/stores/noteFind'

interface FindEditor {
  highlightSearchTerm: (term: string, active?: number, splitWords?: boolean) => boolean
  clearSearchHighlight: () => void
}

export function useFindHighlight(
  editorRef: Ref<FindEditor | null>,
  noteId: () => string,
  /** 正文加载完成等需要重新高亮的附加依赖。 */
  extra?: () => unknown,
) {
  const noteFind = useNoteFindStore()
  /** 只清理自己画上的装饰，避免误伤全局搜索的一次性高亮。 */
  let applied = false

  function clear() {
    if (!applied) return
    editorRef.value?.clearSearchHighlight()
    applied = false
  }

  watch(
    () => [
      noteFind.open,
      noteFind.revision,
      noteFind.query,
      noteFind.activeIndex,
      noteFind.noteId,
      editorRef.value,
      noteId(),
      extra?.(),
    ],
    () => {
      if (!noteFind.open || noteFind.noteId !== noteId()) {
        clear()
        return
      }
      const term = noteFind.query.trim()
      if (!term) {
        clear()
        return
      }
      applied =
        editorRef.value?.highlightSearchTerm(
          term,
          noteFind.activeIndex,
          false,
        ) ?? false
    },
    { flush: 'post' },
  )

  onBeforeUnmount(clear)

  return { clearFindHighlight: clear }
}

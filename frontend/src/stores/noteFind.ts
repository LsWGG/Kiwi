/**
 * 当前笔记内的查找状态：Ctrl/⌘+F 唤起，命令面板也可调用。
 *
 * 计数与滚动由查找条直接扫描 DOM 完成；文档 / 链接面板监听本 store，
 * 把同一组关键词同步成 ProseMirror 装饰（Firefox 不在 contenteditable
 * 里绘制 CSS Custom Highlight，必须走装饰节点）。
 */
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

export const useNoteFindStore = defineStore('noteFind', () => {
  const open = ref(false)
  /** 当前查找所属笔记，避免切换笔记后旧面板继续命中。 */
  const noteId = ref<string | null>(null)
  const query = ref('')
  const activeIndex = ref(0)
  const total = ref(0)
  /** 命中数达到上限时提示「200+」，不阻塞继续滚动。 */
  const truncated = ref(false)
  /** 查询 / 当前项变化时自增，供查找条与编辑器重新绘制。 */
  const revision = ref(0)
  /** 请求聚焦输入框（Ctrl/⌘+F 再次按下时选中已有查询词）。 */
  const focusRevision = ref(0)

  const position = computed(() =>
    total.value ? activeIndex.value + 1 : 0,
  )

  function show(seed = '', id?: string) {
    if (!open.value || (id && noteId.value !== id)) {
      open.value = true
      noteId.value = id ?? noteId.value
      query.value = seed
      activeIndex.value = 0
      total.value = 0
      truncated.value = false
      revision.value += 1
    }
    focusRevision.value += 1
  }

  function close() {
    if (!open.value) return
    open.value = false
    noteId.value = null
    query.value = ''
    activeIndex.value = 0
    total.value = 0
    truncated.value = false
    revision.value += 1
  }

  function setQuery(value: string) {
    if (query.value === value) return
    query.value = value
    activeIndex.value = 0
    revision.value += 1
  }

  function report(count: number, capped = false) {
    total.value = count
    truncated.value = capped
    if (activeIndex.value >= count) activeIndex.value = 0
  }

  function step(delta: number) {
    if (!total.value) return
    activeIndex.value =
      (activeIndex.value + delta + total.value) % total.value
    revision.value += 1
  }

  return {
    open,
    noteId,
    query,
    activeIndex,
    total,
    truncated,
    revision,
    focusRevision,
    position,
    show,
    close,
    setQuery,
    report,
    step,
  }
})

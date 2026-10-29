<script setup lang="ts">
/**
 * 当前笔记内查找条（Ctrl/⌘+F）。
 *
 * 扫描范围由工作区传入，只覆盖当前笔记面板；命中计数、滚动与 CSS
 * 高亮都在这里完成。文档 / 链接面板另外监听 store，把同一关键词同步成
 * ProseMirror 装饰（Firefox 不绘制 contenteditable 里的 Highlight API）。
 */
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import KiwiIcon from '@/components/ui/KiwiIcon.vue'
import { useNoteFindStore } from '@/stores/noteFind'
import { toast } from '@/components/ui/toast'

const props = defineProps<{ scope: HTMLElement | null }>()

const noteFind = useNoteFindStore()
const inputRef = ref<HTMLInputElement | null>(null)
/** 替换行：默认收起，Ctrl/⌘+F 的查找行为保持不变。 */
const replaceOpen = ref(false)
const replaceQuery = ref('')
const replaceInputRef = ref<HTMLInputElement | null>(null)

const MAX_MATCHES = 200
const FIND_HIGHLIGHT = 'kiwi-note-find'
const FIND_ACTIVE_HIGHLIGHT = 'kiwi-note-find-active'
const SKIP_SELECTOR = [
  'button',
  'nav',
  '[role="button"]',
  'input',
  'textarea',
  'select',
  'script',
  'style',
  '[data-find-skip]',
  '.note-find-bar',
  '.kiwi-page-break',
].join(', ')

type HighlightRegistry = {
  set: (name: string, highlight: unknown) => void
  delete: (name: string) => void
}
type HighlightCtor = new (...ranges: Range[]) => unknown

const query = computed({
  get: () => noteFind.query,
  set: (value: string) => noteFind.setQuery(value),
})

const counter = computed(() => {
  if (!noteFind.query.trim()) return '0 / 0'
  return `${noteFind.position} / ${noteFind.total}${noteFind.truncated ? '+' : ''}`
})

let scanTimer: number | null = null
let scrollTimer: number | null = null
let selectionUsed = false
let observer: MutationObserver | null = null

function highlightRegistry(): HighlightRegistry | null {
  const css = window.CSS as unknown as { highlights?: HighlightRegistry } | undefined
  const HighlightImpl = (window as unknown as { Highlight?: HighlightCtor }).Highlight
  return css?.highlights && HighlightImpl ? css.highlights : null
}

function clearPaint() {
  const registry = highlightRegistry()
  registry?.delete(FIND_HIGHLIGHT)
  registry?.delete(FIND_ACTIVE_HIGHLIGHT)
  if (selectionUsed) {
    window.getSelection()?.removeAllRanges()
    selectionUsed = false
  }
}

function collectRanges(term: string): Range[] {
  const root = props.scope
  if (!root || !term) return []
  const needle = term.toLocaleLowerCase()
  const ranges: Range[] = []
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
    acceptNode(node) {
      const text = node as Text
      const parent = text.parentElement
      if (!parent || !text.nodeValue?.trim()) return NodeFilter.FILTER_REJECT
      if (parent.closest(SKIP_SELECTOR)) return NodeFilter.FILTER_REJECT
      if (parent.closest('[aria-hidden="true"]')) return NodeFilter.FILTER_REJECT
      // 提及、插件等原子节点不是可读正文；但阅读态的 ProseMirror 根节点
      // 本身就是 contenteditable=false，不能整体跳过。
      const readonlyRoot = parent.closest('[contenteditable="false"]')
      if (readonlyRoot && !readonlyRoot.classList.contains('ProseMirror')) {
        return NodeFilter.FILTER_REJECT
      }
      // 隐藏的工作表 / 折叠面板不参与计数，避免「3 处命中却只看得见 1 处」。
      if (!parent.getClientRects().length) return NodeFilter.FILTER_REJECT
      return NodeFilter.FILTER_ACCEPT
    },
  })
  while (walker.nextNode() && ranges.length < MAX_MATCHES) {
    const node = walker.currentNode as Text
    const haystack = (node.nodeValue || '').toLocaleLowerCase()
    let from = 0
    while (ranges.length < MAX_MATCHES) {
      const index = haystack.indexOf(needle, from)
      if (index < 0) break
      const range = document.createRange()
      range.setStart(node, index)
      range.setEnd(node, index + term.length)
      ranges.push(range)
      from = index + needle.length
    }
  }
  return ranges
}

function paint(ranges: Range[]) {
  clearPaint()
  const registry = highlightRegistry()
  const HighlightImpl = (window as unknown as { Highlight?: HighlightCtor }).Highlight
  if (!ranges.length) return
  if (registry && HighlightImpl) {
    registry.set(FIND_HIGHLIGHT, new HighlightImpl(...ranges))
    const active = ranges[noteFind.activeIndex]
    if (active) registry.set(FIND_ACTIVE_HIGHLIGHT, new HighlightImpl(active))
    return
  }
  // 旧浏览器退化为原生选区，至少能看见当前一项。
  const active = ranges[noteFind.activeIndex] || ranges[0]
  const selection = window.getSelection()
  selection?.removeAllRanges()
  selection?.addRange(active)
  selectionUsed = true
}

function scrollToActive(ranges: Range[]) {
  if (scrollTimer !== null) window.clearTimeout(scrollTimer)
  scrollTimer = window.setTimeout(() => {
    scrollTimer = null
    const range = ranges[noteFind.activeIndex]
    range?.startContainer.parentElement?.scrollIntoView({
      block: 'center',
      behavior: 'smooth',
    })
  }, 40)
}

async function scan() {
  if (!noteFind.open) {
    clearPaint()
    return
  }
  const term = noteFind.query.trim()
  if (!term || !props.scope) {
    noteFind.report(0)
    clearPaint()
    return
  }
  await nextTick()
  if (!noteFind.open) return
  // 输入法 / 快速连打时只保留最新一轮扫描结果。
  const expected = noteFind.query.trim()
  const ranges = collectRanges(expected)
  if (expected !== noteFind.query.trim()) return
  noteFind.report(ranges.length, ranges.length >= MAX_MATCHES)
  paint(ranges)
  if (ranges.length) scrollToActive(ranges)
}

function scheduleScan() {
  if (scanTimer !== null) window.clearTimeout(scanTimer)
  scanTimer = window.setTimeout(() => {
    scanTimer = null
    void scan()
  }, 80)
}

/**
 * 正文异步渲染 / 切换阅读态后需要重新计数。只监听子树与文本变化；
 * 装饰节点本身也是 DOM 变化，但重新扫描不会再改 DOM，不会形成循环。
 */
function startObserver() {
  observer?.disconnect()
  observer = null
  if (!noteFind.open || !props.scope) return
  observer = new MutationObserver(() => scheduleScan())
  observer.observe(props.scope, {
    subtree: true,
    childList: true,
    characterData: true,
  })
}

watch([() => noteFind.open, () => props.scope], startObserver, {
  immediate: true,
  flush: 'post',
})

function next() {
  noteFind.step(1)
}

function prev() {
  noteFind.step(-1)
}

function close() {
  noteFind.close()
}

async function toggleReplace() {
  if (!noteFind.replaceable) {
    toast.info('当前视图为只读，切换到编辑视图后再替换')
    return
  }
  replaceOpen.value = !replaceOpen.value
  if (!replaceOpen.value) return
  await nextTick()
  replaceInputRef.value?.focus()
  replaceInputRef.value?.select()
}

/** 执行替换：当前项或全部；替换后重新扫描计数并同步编辑器高亮。 */
function applyReplace(all: boolean) {
  const term = noteFind.query.trim()
  if (!term) {
    inputRef.value?.focus()
    return
  }
  const count = noteFind.runReplace(replaceQuery.value, all)
  if (count === null) {
    toast.info('当前视图为只读，切换到编辑视图后再替换')
    return
  }
  if (!count) {
    toast.info(`没有找到「${term}」`)
    return
  }
  noteFind.refresh()
  toast.success(all ? `已替换 ${count} 处` : '已替换当前一处')
}

function onReplaceKeydown(event: KeyboardEvent) {
  if (event.key === 'Enter') {
    event.preventDefault()
    applyReplace(event.ctrlKey || event.metaKey)
    return
  }
  if (event.key === 'Escape') {
    event.preventDefault()
    close()
  }
}

function onInputKeydown(event: KeyboardEvent) {
  if (event.key === 'Enter') {
    event.preventDefault()
    if (event.shiftKey) prev()
    else next()
    return
  }
  if (event.key === 'Escape') {
    event.preventDefault()
    close()
    return
  }
  if (event.key === 'F3') {
    event.preventDefault()
    if (event.shiftKey) prev()
    else next()
  }
}

watch(
  [
    () => noteFind.open,
    () => noteFind.query,
    () => noteFind.activeIndex,
    () => noteFind.revision,
    () => props.scope,
  ],
  scheduleScan,
  { immediate: true, flush: 'post' },
)

watch(
  () => noteFind.focusRevision,
  async () => {
    await nextTick()
    inputRef.value?.focus()
    inputRef.value?.select()
  },
)

watch(
  () => noteFind.open,
  (open) => {
    if (!open) {
      if (scanTimer !== null) window.clearTimeout(scanTimer)
      if (scrollTimer !== null) window.clearTimeout(scrollTimer)
      scanTimer = null
      scrollTimer = null
      observer?.disconnect()
      observer = null
      clearPaint()
      // 关闭查找即收起替换行，避免下次打开时误替换上次的替换词。
      replaceOpen.value = false
      replaceQuery.value = ''
    } else {
      startObserver()
    }
  },
)

onBeforeUnmount(() => {
  observer?.disconnect()
  observer = null
  if (scanTimer !== null) window.clearTimeout(scanTimer)
  if (scrollTimer !== null) window.clearTimeout(scrollTimer)
  clearPaint()
})
</script>

<template>
  <Transition name="find-bar">
    <div
      v-if="noteFind.open"
      class="note-find-bar absolute right-4 top-14 z-30 flex w-[min(430px,calc(100%-2rem))] flex-col gap-1 rounded-xl border border-slate-200/90 bg-white/95 px-2 py-1.5 shadow-lifted backdrop-blur-xl"
      :style="{ zoom: 'var(--ui-scale)' }"
      role="search"
      aria-label="在当前笔记中查找与替换"
      data-find-skip
    >
      <div class="flex items-center gap-1">
        <KiwiIcon name="search" :size="14" class="shrink-0 text-kiwi-500" />
        <input
          ref="inputRef"
          v-model="query"
          name="note-find"
          autocomplete="off"
          spellcheck="false"
          class="min-w-0 flex-1 bg-transparent px-0.5 text-[12px] text-slate-700 outline-none placeholder:text-slate-300"
          placeholder="在当前笔记中查找"
          @keydown="onInputKeydown"
        />
        <span
          class="shrink-0 whitespace-nowrap tabular-nums text-[10px]"
          :class="
            noteFind.query.trim() && !noteFind.total ? 'text-rose-400' : 'text-slate-400'
          "
        >
          {{ counter }}
        </span>
        <button
          type="button"
          class="grid h-6 w-6 shrink-0 place-items-center rounded-md text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-600 disabled:opacity-40"
          title="上一处（Shift + Enter）"
          :disabled="!noteFind.total"
          @mousedown.prevent
          @click="prev"
        >
          <KiwiIcon name="arrowUp" :size="12" />
        </button>
        <button
          type="button"
          class="grid h-6 w-6 shrink-0 place-items-center rounded-md text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-600 disabled:opacity-40"
          title="下一处（Enter）"
          :disabled="!noteFind.total"
          @mousedown.prevent
          @click="next"
        >
          <KiwiIcon name="arrowDown" :size="12" />
        </button>
        <button
          type="button"
          class="grid h-6 w-6 shrink-0 place-items-center rounded-md transition-colors disabled:opacity-40"
          :class="replaceOpen ? 'bg-kiwi-50 text-kiwi-600' : 'text-slate-400 hover:bg-slate-100 hover:text-slate-600'"
          :title="noteFind.replaceable ? '替换（展开替换行）' : '当前视图为只读，切换到编辑视图后可替换'"
          :aria-expanded="replaceOpen"
          @mousedown.prevent
          @click="toggleReplace"
        >
          <KiwiIcon name="refresh" :size="12" />
        </button>
        <span class="h-4 w-px shrink-0 bg-slate-200" />
        <button
          type="button"
          class="grid h-6 w-6 shrink-0 place-items-center rounded-md text-slate-400 transition-colors hover:bg-rose-50 hover:text-rose-500"
          title="关闭查找（Esc）"
          @mousedown.prevent
          @click="close"
        >
          <KiwiIcon name="close" :size="12" />
        </button>
      </div>

      <!-- 替换行：Enter 替换当前项，Ctrl/⌘+Enter 全部替换 -->
      <div
        v-if="replaceOpen"
        class="flex items-center gap-1 border-t border-slate-100 pt-1"
      >
        <KiwiIcon name="edit" :size="13" class="shrink-0 text-slate-400" />
        <input
          ref="replaceInputRef"
          v-model="replaceQuery"
          name="note-replace"
          autocomplete="off"
          spellcheck="false"
          class="min-w-0 flex-1 bg-transparent px-0.5 text-[12px] text-slate-700 outline-none placeholder:text-slate-300"
          placeholder="替换为（留空即删除）"
          @keydown="onReplaceKeydown"
        />
        <button
          type="button"
          class="shrink-0 rounded-md px-1.5 py-0.5 text-[10.5px] text-slate-500 transition-colors hover:bg-kiwi-50 hover:text-kiwi-700 disabled:pointer-events-none disabled:opacity-40"
          title="替换当前一处（Enter）"
          :disabled="!noteFind.total || !noteFind.replaceable"
          @mousedown.prevent
          @click="applyReplace(false)"
        >
          替换
        </button>
        <button
          type="button"
          class="shrink-0 rounded-md px-1.5 py-0.5 text-[10.5px] text-slate-500 transition-colors hover:bg-kiwi-50 hover:text-kiwi-700 disabled:pointer-events-none disabled:opacity-40"
          title="替换全部命中（Ctrl/⌘+Enter）"
          :disabled="!noteFind.total || !noteFind.replaceable"
          @mousedown.prevent
          @click="applyReplace(true)"
        >
          全部替换
        </button>
      </div>
    </div>
  </Transition>
</template>

<style scoped>
.find-bar-enter-active,
.find-bar-leave-active {
  transition:
    opacity 120ms ease,
    transform 120ms ease;
}
.find-bar-enter-from,
.find-bar-leave-to {
  opacity: 0;
  transform: translateY(-4px);
}
</style>

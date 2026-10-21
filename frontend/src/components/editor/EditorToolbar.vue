<script setup lang="ts">
/**
 * 编辑器工具栏：按模式裁剪，体现不同的编辑方式。
 * - 标准编辑：常用行内格式、列表、插入与 Agent 指令（语雀式）；
 * - DOCX：Word 风格（缩放、字体/字号、表格/图片/对齐 + 页面设置）。
 * 表格行列 / 合并 / 表头等操作只在表格上下文菜单中，不放在这里。
 */
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import type { Editor } from '@tiptap/core'
import KiwiIcon from '@/components/ui/KiwiIcon.vue'
import {
  CODE_LANGUAGES,
  CODE_THEMES,
  DEFAULT_CODE_PREFS,
  DEFAULT_DOCX_PREFS,
  DOCX_FONTS,
  DOCX_SIZES,
  type CodePrefs,
  type DocxFont,
  type DocxPrefs,
  type EditorMode,
} from './modes'
import {
  applyParagraphFormat,
  currentBlock,
  currentParagraphFormat,
  defaultBlockSize,
} from './extensions/paragraphFormat'
import { applyTextFormat } from './extensions/textFormat'
import { normalizeColor, normalizeTextStyleAttrs } from './extensions/textStyle'
import EditorColorPicker from './EditorColorPicker.vue'
import OrderedListStyleMenu from './OrderedListStyleMenu.vue'
import {
  DEFAULT_ORDERED_LIST_STYLE,
  resolveOrderedListStyle,
  type OrderedListStyleKey,
} from './orderedListStyles'

const props = withDefaults(
  defineProps<{
    editor: Editor | null
    mode?: EditorMode
    docxPrefs?: DocxPrefs | null
    zoom?: number
    /** 底部 AI 指令栏是否展开 */
    agentOpen?: boolean
    /** 选区变化计数：让工具栏的激活态随光标移动刷新 */
    revision?: number
    /** 代码块显示偏好（主题 / 行号 / 自动换行） */
    codePrefs?: CodePrefs | null
    /** 格式刷已复制格式，等待应用到目标内容 */
    painterActive?: boolean
    /** 当前笔记的多级有序列表编号预设 */
    orderedListStyle?: string | null
  }>(),
  {
    mode: 'simple',
    docxPrefs: null,
    zoom: 100,
    agentOpen: false,
    revision: 0,
    codePrefs: null,
    painterActive: false,
    orderedListStyle: null,
  },
)
/** 编号样式非默认时给合并按钮一个浅色提示，与扩展组件按钮的激活态一致。 */
const listStyleCustomized = computed(
  () => resolveOrderedListStyle(props.orderedListStyle) !== DEFAULT_ORDERED_LIST_STYLE,
)

const emit = defineEmits<{
  (e: 'image'): void
  (e: 'attach'): void
  (e: 'link'): void
  (e: 'table'): void
  (e: 'details'): void
  (e: 'youtube'): void
  (e: 'mention'): void
  (e: 'emoji'): void
  /** 插入扩展组件：date / formula / mermaid / gallery / columns2 / columns3 / note */
  (e: 'component', key: string): void
  (e: 'docx-prefs', prefs: DocxPrefs): void
  (e: 'page-break'): void
  (e: 'word-preview'): void
  (e: 'code-prefs', prefs: CodePrefs): void
  (e: 'run-code', payload: { language: string; code: string }): void
  (e: 'zoom', value: number): void
  (e: 'agent'): void
  /** 格式刷：复制当前格式，或把已复制的格式应用到当前选区 */
  (e: 'painter'): void
  /** 切换多级有序列表编号预设 */
  (e: 'ordered-list-style', key: OrderedListStyleKey): void
}>()

// 「插入组件」下拉：Simple / Agent 模式下也能发现斜杠菜单里的扩展块。
// 工具栏自身 overflow-x-auto 会裁掉绝对定位菜单，因此菜单 Teleport 到 body
// 并用 fixed 坐标锚定「+」按钮。
const componentMenuOpen = ref(false)
const componentMenuRoot = ref<HTMLElement | null>(null)
const componentMenuEl = ref<HTMLElement | null>(null)
const componentMenuPos = ref({ left: 0, top: 0 })
const COMPONENT_MENU_WIDTH = 240
/** 菜单实际高度约 350px；空间不足时向上展开。 */
const COMPONENT_MENU_HEIGHT = 360
let componentMenuFrame = 0

function componentMenuAnchor(): HTMLElement | null {
  return (componentMenuRoot.value?.querySelector('button') as HTMLElement | null) ?? null
}

function uiScale(): number {
  const raw = getComputedStyle(document.documentElement).getPropertyValue('--ui-scale')
  const value = Number.parseFloat(raw)
  return Number.isFinite(value) && value > 0 ? value : 1
}

function positionComponentMenu() {
  const anchor = componentMenuAnchor()
  if (!anchor) return
  const rect = anchor.getBoundingClientRect()
  // 外层 fixed 挂在 <html>（不受 body zoom 影响），内层自行按 --ui-scale 缩放。
  const scale = uiScale()
  const width = COMPONENT_MENU_WIDTH * scale
  const height = (componentMenuEl.value?.offsetHeight || COMPONENT_MENU_HEIGHT) * scale
  const margin = 8
  let left = rect.left
  if (left + width > window.innerWidth - margin) {
    left = Math.max(margin, rect.right - width)
  }
  let top = rect.bottom + 6
  if (top + height > window.innerHeight - margin) {
    top = Math.max(margin, rect.top - height - 6)
  }
  componentMenuPos.value = { left, top }
}

/** 工具栏可能横向滚动，锚点在下一帧才稳定，连排两次测量。 */
function scheduleComponentMenuPosition() {
  cancelAnimationFrame(componentMenuFrame)
  componentMenuFrame = requestAnimationFrame(() => {
    componentMenuFrame = requestAnimationFrame(positionComponentMenu)
  })
}

function toggleComponentMenu() {
  componentMenuOpen.value = !componentMenuOpen.value
  if (!componentMenuOpen.value) {
    cancelAnimationFrame(componentMenuFrame)
    return
  }
  const anchor = componentMenuAnchor()
  // 先让「+」完整进入工具栏可视区，再按最终位置展开菜单。
  anchor?.scrollIntoView({ block: 'nearest', inline: 'nearest' })
  positionComponentMenu()
  scheduleComponentMenuPosition()
  void nextTick(positionComponentMenu)
}

const COMPONENTS = [
  { key: 'date', label: '日期', hint: '可点击修改的日期胶囊', icon: 'calendar' },
  { key: 'formula', label: '公式', hint: 'KaTeX 数学公式', icon: 'hash' },
  { key: 'mermaid', label: '文本绘图', hint: 'Mermaid 流程图 / 时序图', icon: 'graph' },
  { key: 'gallery', label: '图册', hint: '多图网格 / 滑动展示', icon: 'gallery' },
  { key: 'columns2', label: '分栏卡片 · 2 栏', hint: '左右并排的富文本', icon: 'columns' },
  { key: 'columns3', label: '分栏卡片 · 3 栏', hint: '三栏并排的富文本', icon: 'columns' },
  { key: 'calendar', label: '日历', hint: '月视图，可为日期添加安排', icon: 'calendar' },
  { key: 'datatable', label: '数据表', hint: '可增删行列，支持批量粘贴', icon: 'table' },
  { key: 'taskProgress', label: '待办进度', hint: '绑定附近任务清单，实时统计完成度', icon: 'checkSquare' },
]

function pickComponent(key: string) {
  componentMenuOpen.value = false
  emit('component', key)
}

function onComponentOutside(event: MouseEvent) {
  if (!componentMenuOpen.value) return
  const target = event.target as Node
  if (componentMenuRoot.value?.contains(target)) return
  if (componentMenuEl.value?.contains(target)) return
  componentMenuOpen.value = false
}

/** 工具栏横向滚动 / 页面滚动 / 窗口缩放时重新贴住锚点，而不是直接收起。 */
function onComponentViewportChange() {
  if (componentMenuOpen.value) scheduleComponentMenuPosition()
}

onMounted(() => {
  document.addEventListener('mousedown', onComponentOutside)
  window.addEventListener('resize', onComponentViewportChange)
  window.addEventListener('scroll', onComponentViewportChange, true)
})
onBeforeUnmount(() => {
  cancelAnimationFrame(componentMenuFrame)
  document.removeEventListener('mousedown', onComponentOutside)
  window.removeEventListener('resize', onComponentViewportChange)
  window.removeEventListener('scroll', onComponentViewportChange, true)
})

// Simple / Notion / Agent 已合并为标准编辑
const simple = computed(() => props.mode !== 'docx')
const docx = computed(() => props.mode === 'docx')
const prefs = computed<DocxPrefs>(() => props.docxPrefs ?? DEFAULT_DOCX_PREFS)
const code = computed<CodePrefs>(() => props.codePrefs ?? DEFAULT_CODE_PREFS)
const codeLanguage = computed(
  () => (props.editor?.getAttributes('codeBlock').language as string) || 'plaintext',
)
/** 当前代码块能否运行：python 走后端，html / js 在预览 iframe 中渲染。 */
const codeRunKind = computed<'python' | 'html' | 'js' | null>(() => {
  const lang = codeLanguage.value.toLowerCase()
  if (lang === 'python' || lang === 'python3' || lang === 'py') return 'python'
  if (lang === 'html') return 'html'
  if (lang === 'javascript' || lang === 'js') return 'js'
  return null
})

/** 读取光标所在的代码块（语言 + 纯文本）。 */
function currentCodeBlock(): { language: string; code: string } | null {
  const ed = props.editor
  if (!ed) return null
  const { $from } = ed.state.selection
  for (let depth = $from.depth; depth > 0; depth -= 1) {
    const node = $from.node(depth)
    if (node.type.name === 'codeBlock') {
      return {
        language: String(node.attrs.language || '').toLowerCase(),
        code: node.textContent,
      }
    }
  }
  return null
}

function runCodeBlock() {
  const block = currentCodeBlock()
  if (block) emit('run-code', block)
}

function applyCodePrefs(patch: Partial<CodePrefs>) {
  emit('code-prefs', { ...code.value, ...patch })
}

function setCodeLanguage(e: Event) {
  const ed = props.editor
  if (!ed) return
  ed.chain()
    .focus()
    .updateAttributes('codeBlock', { language: (e.target as HTMLSelectElement).value })
    .run()
}

/** 工具栏复制按钮：只复制当前代码块的纯文本，不含行号与按钮标签。 */
const copied = ref(false)
let copiedTimer: number | undefined
async function copyCode() {
  const block = currentCodeBlock()
  if (!block) return
  try {
    await navigator.clipboard.writeText(block.code)
    copied.value = true
    window.clearTimeout(copiedTimer)
    copiedTimer = window.setTimeout(() => {
      copied.value = false
    }, 1400)
  } catch {
    /* 剪贴板不可用时忽略 */
  }
}

const ZOOM_STEPS = [70, 80, 90, 100, 110, 120, 130]

/** 光标所在段落的显式排版（随 revision 刷新）。 */
const paragraphFormat = computed(() => {
  void props.revision
  return currentParagraphFormat(props.editor)
})
/** 选区非空时，字体 / 字号以选区字符格式为准。 */
const textFormat = computed(() => {
  void props.revision
  const ed = props.editor
  if (!ed) return {}
  if (!ed.state.selection.empty) {
    return normalizeTextStyleAttrs(ed.getAttributes('textStyle'))
  }
  const stored = ed.state.storedMarks?.find((mark) => mark.type.name === 'textStyle')
  return stored ? normalizeTextStyleAttrs(stored.attrs) : {}
})
const currentFont = computed<DocxFont>(
  () => textFormat.value.font ?? paragraphFormat.value.font ?? prefs.value.font,
)
const currentTextColor = computed(
  () => textFormat.value.color ?? '#1F2937',
)
const currentSize = computed(() => {
  const selectionSize = textFormat.value.size
  if (typeof selectionSize === 'number') return selectionSize
  const explicit = paragraphFormat.value.size
  if (typeof explicit === 'number') return explicit
  return defaultBlockSize(currentBlock(props.editor)?.node ?? null, prefs.value)
})
const sizeOptions = computed(() =>
  DOCX_SIZES.includes(currentSize.value)
    ? DOCX_SIZES
    : [...DOCX_SIZES, currentSize.value].sort((a, b) => a - b),
)
/**
 * 点击工具栏下拉时，浏览器可能先把编辑器里的选区收起。
 * 在 pointerdown 阶段先记住选区，后续仍能只作用于选中的文字。
 */
let capturedRange: { from: number; to: number } | null = null
function captureSelection() {
  const ed = props.editor
  if (!ed) return
  const { selection } = ed.state
  capturedRange = selection.empty
    ? null
    : { from: selection.from, to: selection.to }
}

function applyToolbarTextFormat(patch: {
  font?: DocxFont
  size?: number
  color?: string | null
}): boolean {
  const ed = props.editor
  if (!ed) return false
  if (!ed.state.selection.empty) return applyTextFormat(ed, patch)
  if (capturedRange) {
    const { from, to } = capturedRange
    capturedRange = null
    if (from < to && to <= ed.state.doc.content.size) {
      ed.chain().focus().setTextSelection({ from, to }).run()
      return applyTextFormat(ed, patch)
    }
  }
  return false
}

/**
 * 有选区时只改选中的文字；Word 模式光标折叠才回退到整段设置。
 * 其他模式光标折叠时只影响接下来输入的文字。
 */
function onFont(e: Event) {
  const ed = props.editor
  if (!ed) return
  const font = (e.target as HTMLSelectElement).value as DocxFont
  if (applyToolbarTextFormat({ font })) return
  if (docx.value) applyParagraphFormat(ed, { font })
  else applyTextFormat(ed, { font })
}
function onTextColor(color: string) {
  const ed = props.editor
  if (!ed) return
  if (applyToolbarTextFormat({ color })) return
  // 无选区时设置为「后续输入」的颜色，与字体 / 字号行为一致
  applyTextFormat(ed, { color })
}

function clearTextColor() {
  applyToolbarTextFormat({ color: null })
}

function onSize(e: Event) {
  const ed = props.editor
  if (!ed) return
  const size = Number((e.target as HTMLSelectElement).value)
  if (applyToolbarTextFormat({ size })) return
  if (docx.value) applyParagraphFormat(ed, { size })
  else applyTextFormat(ed, { size })
}

function zoomBy(direction: -1 | 1) {
  const current = ZOOM_STEPS.indexOf(props.zoom)
  const index = current < 0 ? ZOOM_STEPS.indexOf(100) : current
  const next = ZOOM_STEPS[Math.min(ZOOM_STEPS.length - 1, Math.max(0, index + direction))]
  emit('zoom', next)
}

/** Word 模式只保留版式类段落样式，不提供代码块等扩展块。 */
const blockOptions = computed(() => {
  const options = [
    { value: 'paragraph', label: '正文' },
    { value: 'h1', label: '标题 1' },
    { value: 'h2', label: '标题 2' },
    { value: 'h3', label: '标题 3' },
    { value: 'blockquote', label: '引用' },
  ]
  if (!docx.value) options.push({ value: 'codeBlock', label: '代码块' })
  return options
})

const blockType = computed(() => {
  const ed = props.editor
  if (!ed) return 'paragraph'
  for (const level of [1, 2, 3] as const) {
    if (ed.isActive('heading', { level })) return `h${level}`
  }
  if (ed.isActive('codeBlock')) return 'codeBlock'
  if (ed.isActive('blockquote')) return 'blockquote'
  return 'paragraph'
})

function setBlock(e: Event) {
  const value = (e.target as HTMLSelectElement).value
  const ed = props.editor
  if (!ed) return
  const chain = ed.chain().focus()
  if (value === 'paragraph') chain.setParagraph().run()
  else if (value === 'codeBlock') chain.toggleCodeBlock().run()
  else if (value === 'blockquote') chain.toggleBlockquote().run()
  else chain.setHeading({ level: Number(value.slice(1)) as 1 | 2 | 3 }).run()
}

function run(fn: (ed: Editor) => void) {
  if (props.editor) fn(props.editor)
}

function toggleLink() {
  // 交给编辑器统一弹窗，支持「内容 / 标题超链接」两种展示方式
  emit('link')
}

const btn =
  'w-7 h-7 grid place-items-center rounded-lg text-slate-500 transition-colors hover:bg-kiwi-50 hover:text-kiwi-700'
const activeBtn = 'bg-kiwi-100/80 text-kiwi-700'
const group = 'flex items-center gap-0.5 shrink-0'
const sep = 'w-px h-4 bg-slate-200/80 mx-1 shrink-0'
</script>

<template>
  <div
    v-if="editor"
    class="kiwi-toolbar flex flex-nowrap items-center overflow-x-auto px-1.5 py-1.5 rounded-xl border backdrop-blur sticky top-0 z-20"
    :class="docx ? 'border-slate-300/70 bg-white/90' : 'border-slate-200/70 bg-white/70'"
    :data-revision="revision"
  >
    <!-- 页面缩放：所有模式共用（Word 风格缩放组件） -->
    <div :class="group">
      <button type="button" :class="btn" title="缩小页面" @click="zoomBy(-1)">
        <KiwiIcon name="minus" :size="14" />
      </button>
      <button
        type="button"
        class="h-7 min-w-[44px] rounded-md px-1 text-[10.5px] tabular-nums text-slate-500 transition-colors hover:bg-slate-100"
        title="恢复 100%"
        @click="emit('zoom', 100)"
      >
        {{ zoom }}%
      </button>
      <button type="button" :class="btn" title="放大页面" @click="zoomBy(1)">
        <KiwiIcon name="plus" :size="14" />
      </button>
    </div>
    <span :class="sep" />

    <!-- 块类型 -->
    <div :class="group">
      <select
        :value="blockType"
        class="h-7 rounded-lg border border-slate-200/80 bg-white/80 text-[11px] text-slate-600 px-1.5 outline-none focus:ring-2 focus:ring-kiwi-200"
        @change="setBlock"
      >
        <option v-for="option in blockOptions" :key="option.value" :value="option.value">
          {{ option.label }}
        </option>
      </select>
    </div>

    <!-- 代码块：语言 / 主题 / 行号 / 换行 / 复制（Word 模式不提供代码块） -->
    <template v-if="!docx && editor.isActive('codeBlock')">
      <span :class="sep" />
      <div :class="group">
        <select
          :value="codeLanguage"
          class="h-7 max-w-[104px] rounded-lg border border-slate-200/80 bg-white/80 text-[11px] text-slate-600 px-1.5 outline-none focus:ring-2 focus:ring-kiwi-200"
          title="代码语言"
          @change="setCodeLanguage"
        >
          <option v-for="lang in CODE_LANGUAGES" :key="lang.id" :value="lang.id">
            {{ lang.label }}
          </option>
        </select>
        <select
          :value="code.theme"
          class="h-7 rounded-lg border border-slate-200/80 bg-white/80 text-[11px] text-slate-600 px-1.5 outline-none focus:ring-2 focus:ring-kiwi-200"
          title="高亮主题"
          @change="applyCodePrefs({ theme: ($event.target as HTMLSelectElement).value as 'dark' | 'light' })"
        >
          <option v-for="theme in CODE_THEMES" :key="theme.id" :value="theme.id">
            {{ theme.label }}
          </option>
        </select>
        <button
          type="button"
          :class="[btn, 'font-mono !text-[12px]', code.lineNumbers ? activeBtn : '']"
          title="显示行号"
          @click="applyCodePrefs({ lineNumbers: !code.lineNumbers })"
        >
          #
        </button>
        <button
          type="button"
          :class="[btn, '!text-[13px]', code.wrap ? activeBtn : '']"
          title="长行自动换行"
          @click="applyCodePrefs({ wrap: !code.wrap })"
        >
          ↵
        </button>
        <button
          v-if="codeRunKind"
          type="button"
          :class="[btn, '!w-auto px-1.5 !text-[10.5px] !text-emerald-600 hover:!bg-emerald-50']"
          :title="codeRunKind === 'python' ? '运行 Python 代码' : '渲染代码预览'"
          @click="runCodeBlock"
        >
          <KiwiIcon name="play" :size="10" class="mr-0.5" />
          {{ codeRunKind === 'python' ? '运行' : '预览' }}
        </button>
        <button
          type="button"
          :class="[btn, '!w-auto px-1.5 !text-[10.5px]', copied ? 'text-emerald-600' : '']"
          :title="copied ? '已复制' : '复制当前代码块'"
          @click="copyCode"
        >
          {{ copied ? '已复制' : '复制' }}
        </button>
      </div>
    </template>

    <!-- 字体 / 字号：选中文字时只作用于选区，所有编辑模式一致 -->
    <template v-if="editor">
      <span :class="sep" />
      <div :class="group">
        <select
          :value="currentFont"
          class="h-7 max-w-[128px] rounded-lg border border-slate-200/80 bg-white/80 text-[11px] text-slate-600 px-1.5 outline-none focus:ring-2 focus:ring-kiwi-200"
          title="字体（选中文字生效；未选中时 Word 模式作用于整段，其他模式作用于后续输入）"
          @pointerdown="captureSelection"
          @change="onFont"
        >
          <option v-for="font in DOCX_FONTS" :key="font.id" :value="font.id">
            {{ font.label }}
          </option>
        </select>
        <select
          :value="currentSize"
          class="h-7 rounded-lg border border-slate-200/80 bg-white/80 text-[11px] text-slate-600 px-1.5 outline-none focus:ring-2 focus:ring-kiwi-200"
          title="字号（选中文字生效；未选中时 Word 模式作用于整段，其他模式作用于后续输入）"
          @pointerdown="captureSelection"
          @change="onSize"
        >
          <option v-for="size in sizeOptions" :key="size" :value="size">{{ size }}</option>
        </select>
      </div>
    </template>

    <span :class="sep" />

    <!-- 行内格式 -->
    <div :class="group">
      <button type="button" :class="[btn, editor.isActive('bold') ? activeBtn : '']" title="加粗" @click="run((e) => e.chain().focus().toggleBold().run())">
        <KiwiIcon name="bold" :size="14" />
      </button>
      <button type="button" :class="[btn, editor.isActive('italic') ? activeBtn : '']" title="斜体" @click="run((e) => e.chain().focus().toggleItalic().run())">
        <KiwiIcon name="italic" :size="14" />
      </button>
      <button type="button" :class="[btn, editor.isActive('underline') ? activeBtn : '']" title="下划线" @click="run((e) => e.chain().focus().toggleUnderline().run())">
        <KiwiIcon name="underline" :size="14" />
      </button>
      <button type="button" :class="[btn, editor.isActive('strike') ? activeBtn : '']" title="删除线" @click="run((e) => e.chain().focus().toggleStrike().run())">
        <KiwiIcon name="strike" :size="14" />
      </button>
      <button type="button" :class="[btn, editor.isActive('highlight') ? activeBtn : '']" title="高亮" @click="run((e) => e.chain().focus().toggleHighlight().run())">
        <KiwiIcon name="highlight" :size="14" />
      </button>
      <EditorColorPicker
        variant="toolbar"
        :value="currentTextColor"
        :active="!!textFormat.color"
        @pointerdown="captureSelection"
        @select="onTextColor"
        @clear="clearTextColor"
      />
      <button v-if="!docx" type="button" :class="[btn, editor.isActive('code') ? activeBtn : '']" title="行内代码" @click="run((e) => e.chain().focus().toggleCode().run())">
        <KiwiIcon name="code" :size="14" />
      </button>
      <button type="button" :class="[btn, editor.isActive('link') ? activeBtn : '']" title="链接" @click="toggleLink">
        <KiwiIcon name="link2" :size="14" />
      </button>
      <button
        type="button"
        :class="[
          btn,
          painterActive
            ? 'bg-amber-100/90 text-amber-700 ring-1 ring-inset ring-amber-300/70'
            : '',
        ]"
        :title="
          painterActive
            ? '格式刷已就绪：选择目标内容自动应用，Esc 取消'
            : '格式刷：复制当前格式（Ctrl+Shift+C / Ctrl+Alt+C）'
        "
        @mousedown.prevent
        @click="emit('painter')"
      >
        <KiwiIcon name="copy" :size="14" />
      </button>
    </div>

    <span :class="sep" />

    <!-- 列表 -->
    <div :class="group">
      <button type="button" :class="[btn, editor.isActive('bulletList') ? activeBtn : '']" title="无序列表" @click="run((e) => e.chain().focus().toggleBulletList().run())">
        <KiwiIcon name="list" :size="14" />
      </button>
      <!-- 有序列表 + 多级编号样式合并为一个按钮组：主按钮切换列表，箭头选择编号样式 -->
      <div
        class="flex h-7 shrink-0 items-center rounded-lg transition-colors"
        :class="
          editor.isActive('orderedList')
            ? 'bg-kiwi-100/80 text-kiwi-700'
            : listStyleCustomized
              ? 'bg-kiwi-50/70 text-kiwi-700'
              : 'text-slate-500 hover:bg-kiwi-50 hover:text-kiwi-700'
        "
      >
        <button
          type="button"
          class="grid h-7 w-7 place-items-center rounded-l-lg transition-colors"
          :class="editor.isActive('orderedList') ? '' : 'hover:bg-kiwi-50 hover:text-kiwi-700'"
          title="有序列表"
          @click="run((e) => e.chain().focus().toggleOrderedList().run())"
        >
          <KiwiIcon name="listOrdered" :size="14" />
        </button>
        <span
          class="h-3.5 w-px shrink-0"
          :class="editor.isActive('orderedList') ? 'bg-kiwi-300/70' : 'bg-slate-200/80'"
        />
        <OrderedListStyleMenu
          variant="chevron"
          :value="orderedListStyle"
          @change="emit('ordered-list-style', $event)"
        />
      </div>
      <button v-if="!docx" type="button" :class="[btn, editor.isActive('taskList') ? activeBtn : '']" title="任务列表" @click="run((e) => e.chain().focus().toggleTaskList().run())">
        <KiwiIcon name="checkSquare" :size="14" />
      </button>
      <button v-if="!docx" type="button" :class="[btn, editor.isActive('blockquote') ? activeBtn : '']" title="引用" @click="run((e) => e.chain().focus().toggleBlockquote().run())">
        <KiwiIcon name="quote" :size="14" />
      </button>
    </div>

    <span :class="sep" />
    <div :class="group">
      <button type="button" :class="btn" title="插入表格（可设置行列数）" @click="emit('table')">
        <KiwiIcon name="table" :size="14" />
      </button>
      <button type="button" :class="btn" title="插入图片" @click="emit('image')">
        <KiwiIcon name="image" :size="14" />
      </button>
      <button v-if="!docx" type="button" :class="btn" title="上传附件" @click="emit('attach')">
        <KiwiIcon name="paperclip" :size="14" />
      </button>
      <div v-if="!docx" ref="componentMenuRoot" class="relative">
        <button
          type="button"
          :class="[btn, componentMenuOpen ? activeBtn : '']"
          title="插入组件：日期 / 公式 / 绘图 / 图册 / 分栏 / 日历 / 数据表 / 待办进度"
          @mousedown.prevent
          @click="toggleComponentMenu"
        >
          <KiwiIcon name="plus" :size="14" />
        </button>
        <Teleport to="html">
          <Transition
            enter-active-class="transition duration-150 ease-out"
            enter-from-class="opacity-0 -translate-y-1"
            leave-active-class="transition duration-100 ease-in"
            leave-to-class="opacity-0 -translate-y-1"
          >
            <div
              v-if="componentMenuOpen"
              class="fixed z-[80]"
              :style="{ left: `${componentMenuPos.left}px`, top: `${componentMenuPos.top}px` }"
            >
              <div
                ref="componentMenuEl"
                class="w-60 rounded-xl border border-slate-200/90 bg-white/40 p-1.5 shadow-xl backdrop-blur-2xl"
                :style="{ zoom: 'var(--ui-scale)' }"
              >
                <p class="px-2 pb-1 pt-1 text-[10px] font-medium uppercase tracking-[0.12em] text-slate-400">
                  扩展组件
                </p>
                <button
                  v-for="item in COMPONENTS"
                  :key="item.key"
                  type="button"
                  class="flex w-full items-center gap-2.5 rounded-lg px-2 py-1.5 text-left transition-colors hover:bg-kiwi-50"
                  @mousedown.prevent
                  @click="pickComponent(item.key)"
                >
                  <span class="grid h-7 w-7 shrink-0 place-items-center rounded-lg bg-slate-100 text-slate-500">
                    <KiwiIcon :name="item.icon" :size="13" />
                  </span>
                  <span class="min-w-0">
                    <span class="block text-[12px] font-medium text-slate-700">{{ item.label }}</span>
                    <span class="block truncate text-[10px] text-slate-400">{{ item.hint }}</span>
                  </span>
                </button>
              </div>
            </div>
          </Transition>
        </Teleport>
      </div>
      <button v-if="!docx" type="button" :class="btn" title="折叠块" @click="emit('details')">
        <KiwiIcon name="chevron" :size="14" />
      </button>
      <button v-if="!docx" type="button" :class="btn" title="YouTube 视频" @click="emit('youtube')">
        <KiwiIcon name="video" :size="14" />
      </button>
      <button v-if="!docx" type="button" :class="btn" title="提及笔记或 Wiki（@）" @click="emit('mention')">
        <KiwiIcon name="at" :size="14" />
      </button>
      <button v-if="!docx" type="button" :class="btn" title="表情（:）" @click="emit('emoji')">
        <KiwiIcon name="smile" :size="14" />
      </button>
      <button type="button" :class="btn" title="分割线" @click="run((e) => e.chain().focus().setHorizontalRule().run())">
        <KiwiIcon name="columns" :size="14" />
      </button>
    </div>

    <!-- 光标位于折叠块内 -->
    <template v-if="!docx && editor.isActive('details')">
      <span :class="sep" />
      <div :class="group">
        <button type="button" :class="btn" title="展开 / 收起折叠块" @click="run((e) => e.chain().focus().toggleDetailsOpen().run())">
          <KiwiIcon name="chevron" :size="14" />
        </button>
        <button type="button" :class="[btn, 'hover:text-rose-600']" title="解除折叠" @click="run((e) => e.chain().focus().unsetDetails().run())">
          <KiwiIcon name="trash" :size="14" />
        </button>
      </div>
    </template>

    <!-- Word 模式的对齐收进「段落」对话框 -->
    <template v-if="!docx">
    <span :class="sep" />
    <div :class="group">
      <button type="button" :class="[btn, editor.isActive({ textAlign: 'left' }) ? activeBtn : '']" title="左对齐" @click="run((e) => e.chain().focus().setTextAlign('left').run())">
        <span class="text-[11px] font-semibold">L</span>
      </button>
      <button type="button" :class="[btn, editor.isActive({ textAlign: 'center' }) ? activeBtn : '']" title="居中" @click="run((e) => e.chain().focus().setTextAlign('center').run())">
        <span class="text-[11px] font-semibold">C</span>
      </button>
      <button type="button" :class="[btn, editor.isActive({ textAlign: 'right' }) ? activeBtn : '']" title="右对齐" @click="run((e) => e.chain().focus().setTextAlign('right').run())">
        <span class="text-[11px] font-semibold">R</span>
      </button>
      <button type="button" :class="[btn, editor.isActive({ textAlign: 'justify' }) ? activeBtn : '']" title="两端对齐" @click="run((e) => e.chain().focus().setTextAlign('justify').run())">
        <span class="text-[11px] font-semibold">J</span>
      </button>
    </div>
    </template>

    <!-- DOCX 段落排版：正文右击「段落设置…」，工具栏只显示当前段落字体 / 字号 -->

    <!-- DOCX 专属：分页符与 Word 版式预览 -->
    <template v-if="docx">
      <span :class="sep" />
      <div :class="group">
        <button
          type="button"
          :class="[btn, '!w-auto gap-1 px-1.5 !text-[10.5px]']"
          title="插入分页符（Ctrl+Enter）"
          @click="emit('page-break')"
        >
          <KiwiIcon name="pageBreak" :size="13" />
          分页符
        </button>
        <button
          type="button"
          :class="[btn, '!w-auto gap-1 px-1.5 !text-[10.5px]']"
          title="按导出效果预览分页"
          @click="emit('word-preview')"
        >
          <KiwiIcon name="fileText" :size="13" />
          Word 预览
        </button>
      </div>
    </template>

    <!-- Simple：Agent 组件（靠左、无边框），点击展开下方 AI 指令栏 -->
    <template v-if="simple">
      <span :class="sep" />
      <button
        type="button"
        class="inline-flex h-7 shrink-0 items-center gap-1 rounded-lg px-2 text-[11px] font-medium transition-colors"
        :class="
          agentOpen
            ? 'bg-kiwi-100/80 text-kiwi-700'
            : 'text-kiwi-600 hover:bg-kiwi-50 hover:text-kiwi-700'
        "
        :aria-pressed="agentOpen"
        :title="agentOpen ? '收起 AI 指令栏' : '展开 AI 指令栏'"
        @click="emit('agent')"
      >
        <KiwiIcon name="sparkle" :size="13" />
        Agent
      </button>
    </template>

    <div class="flex-1 min-w-2" />
    <div :class="group">
      <button type="button" :class="btn" title="撤销" @click="run((e) => e.chain().focus().undo().run())">
        <KiwiIcon name="undo" :size="14" />
      </button>
      <button type="button" :class="btn" title="重做" @click="run((e) => e.chain().focus().redo().run())">
        <KiwiIcon name="redo" :size="14" />
      </button>
    </div>

  </div>
</template>

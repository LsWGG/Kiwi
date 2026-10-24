<script setup lang="ts">
/**
 * Kiwi 编辑器：Tiptap v2 + Markdown 双向往返。
 * 两种模式：标准编辑（语雀式工具栏 + 斜杠命令 + 气泡菜单）/ DOCX（纸张排版）。
 * 历史 Simple / Notion / Agent 数据统一按标准编辑打开，共用「灰色画布 + 白色纸张」。
 * 块能力：标题/列表/任务/引用/提示块/代码高亮/表格/图片/视频/附件/链接/高亮/对齐。
 */
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { BubbleMenu, EditorContent, useEditor } from '@tiptap/vue-3'
import type { Editor } from '@tiptap/core'
import { EditorState, NodeSelection, TextSelection } from '@tiptap/pm/state'
import StarterKit from '@tiptap/starter-kit'
import Underline from '@tiptap/extension-underline'
import Placeholder from '@tiptap/extension-placeholder'
import Link from '@tiptap/extension-link'
import { KiwiImage } from './extensions/kiwiImage'
import TextAlign from '@tiptap/extension-text-align'
import Highlight from '@tiptap/extension-highlight'
import TableRow from '@tiptap/extension-table-row'
import { KiwiTaskList } from './extensions/emptyTaskList'
import TaskItem from '@tiptap/extension-task-item'
import DetailsSummary from '@tiptap/extension-details-summary'
import DetailsContent from '@tiptap/extension-details-content'
import CharacterCount from '@tiptap/extension-character-count'
import GlobalDragHandle from 'tiptap-extension-global-drag-handle'
import { common, createLowlight } from 'lowlight'
import { Markdown } from 'tiptap-markdown'
import EditorToolbar from './EditorToolbar.vue'
import EditorColorPicker from './EditorColorPicker.vue'
import MarkdownIt from 'markdown-it'
import TableInsertDialog from './TableInsertDialog.vue'
import InsertEmbedDialog, { type EmbedTab } from './InsertEmbedDialog.vue'
import SourceQuoteDialog from './SourceQuoteDialog.vue'
import KnowledgePointDialog from './KnowledgePointDialog.vue'
import { createSlashCommand } from './slashCommands'
import { KiwiDate, todayISO } from './extensions/date'
import { KiwiFormula } from './extensions/formula'
import { KiwiMermaid } from './extensions/mermaid'
import { KiwiGallery } from './extensions/gallery'
import { KiwiColumn, KiwiColumns } from './extensions/columns'
import { KiwiNoteEmbed } from './extensions/noteEmbed'
import { KiwiCalendar } from './extensions/calendar'
import { KiwiDataTable } from './extensions/dataTable'
import type { NoteSummary } from '@/stores/notes'
import { Callout } from './extensions/callout'
import { MarkdownSerializerFix } from './extensions/markdownSerializerFix'
import { Video } from './extensions/video'
import { KiwiDetails } from './extensions/details'
import { KiwiYoutube } from './extensions/youtube'
import { KiwiEmoji } from './extensions/emoji'
import {
  createMentionExtension,
  normalizeMentionDisplay,
  type MentionDisplay,
} from './extensions/mention'
import type { MentionWikiPage } from './extensions/mention'
import { MENTION_DISPLAY_OPTIONS } from './extensions/mentionTypes'
import {
  KiwiTable,
  KiwiTableCell,
  KiwiTableHeader,
} from './extensions/table'
import { createCodeBlock } from './extensions/codeBlock'
import { CodeOutput, formatRunResult, upsertCodeOutput } from './extensions/codeOutput'
import { buildPreviewDocument } from './extensions/preview'
import { TrailingParagraph } from './extensions/trailingParagraph'
import { KiwiTaskProgress } from './extensions/taskProgress'
import { KiwiPluginBlock } from './extensions/pluginBlock'
import { EmbedBlock, embedAttrs } from './extensions/embed'
import { PageBreak } from './extensions/pageBreak'
import { PagedDoc } from './extensions/pagedDoc'
import {
  SearchHighlight,
  clearSearchHighlight,
  highlightSearchTerm,
} from './extensions/searchHighlight'
import {
  applyParagraphFormat,
  applyParagraphFormats,
  clearParagraphFormat,
  collectParagraphFormats,
  currentParagraphFormat,
  KiwiHeading,
  KiwiParagraph,
  type ParagraphFormatPatch,
} from './extensions/paragraphFormat'
import {
  KiwiTextStyle,
  normalizeColor,
  normalizeTextStyleAttrs,
} from './extensions/textStyle'
import {
  applyTextFormat,
  applyTextFormats,
  collectTextFormats,
} from './extensions/textFormat'
import { orderedListStyleClass, type OrderedListStyleKey } from './orderedListStyles'
import DocxParagraphDialog from './DocxParagraphDialog.vue'
import type { LinkMeta } from '@/api/links'
import {
  DEFAULT_CODE_PREFS,
  DEFAULT_DOCX_PREFS,
  DEFAULT_PAGE_PREFS,
  docxBackgroundColor,
  docxFontStack,
  docxPaperLabel,
  docxPaperSize,
  pageBackgroundColor,
  pageWidthMax,
  resolveCodePrefs,
  resolveDocxPrefs,
  resolvePagePrefs,
  type CodePrefs,
  type DocxFont,
  type DocxPrefs,
  type EditorMode,
  type PagePrefs,
} from './modes'
import KiwiIcon from '@/components/ui/KiwiIcon.vue'
import { request, upload } from '@/api/client'
import { runPython, type RunCodeResult } from '@/api/run'
import { useKbsStore } from '@/stores/kbs'
import { useNotesStore } from '@/stores/notes'
import { usePluginsStore, type PluginBlock } from '@/stores/plugins'
import { useExtensionsStore } from '@/stores/extensions'
import { toast } from '@/components/ui/toast'

const props = withDefaults(
  defineProps<{
    content: string
    readonly?: boolean
    noteId?: string | null
    placeholder?: string
    mode?: EditorMode
    docxPrefs?: DocxPrefs | null
    pagePrefs?: PagePrefs | null
    /** DOCX 段落级排版（随 props_json.paragraph_formats 持久化） */
    paragraphFormats?: unknown
    /** 字符级字体 / 字号（随 props_json.text_formats 持久化） */
    textFormats?: unknown
    /** 多级有序列表编号预设（随 props_json.ordered_list_style 持久化） */
    orderedListStyle?: string | null
    docTitle?: string
    showOutline?: boolean
    /** Simple 模式下底部 AI 指令栏是否展开 */
    agentOpen?: boolean
    /** 把工具栏 Teleport 到页面上的容器（Word 预览分栏时让工具栏横跨两栏） */
    toolbarHost?: string | null
  }>(),
  {
    readonly: false,
    noteId: null,
    mode: 'simple',
    docxPrefs: null,
    pagePrefs: null,
    orderedListStyle: null,
    docTitle: '',
    showOutline: false,
    agentOpen: false,
    toolbarHost: null,
    placeholder: '开始写作… 输入 / 唤起命令，@ 提及笔记或 Wiki',
  },
)

const emit = defineEmits<{
  (e: 'update', markdown: string): void
  (e: 'docx-prefs', prefs: DocxPrefs): void
  (e: 'paragraph-formats', formats: ReturnType<typeof collectParagraphFormats>): void
  (e: 'text-formats', formats: ReturnType<typeof collectTextFormats>): void
  (e: 'word-preview'): void
  (e: 'toggle-agent'): void
  (e: 'ordered-list-style', key: OrderedListStyleKey): void
}>()

const kbs = useKbsStore()
const notesStore = useNotesStore()
const pluginsStore = usePluginsStore()
const extensionsStore = useExtensionsStore()
const router = useRouter()
const lowlight = createLowlight(common)

/** 编号预设只在非默认值时生成 class，默认样式保持原样。 */
const orderedListClass = computed(() => orderedListStyleClass(props.orderedListStyle))

/**
 * 待办收件箱的来源链接：优先用链接里的 ?note= 直接跳转；
 * 旧版收件箱没有该参数，再用待办镜像 API 解析来源笔记。
 */
async function openTodoSource(href: string) {
  const mirrorId = /^kiwi:\/\/todo\/([0-9a-fA-F-]{36})/.exec(href)?.[1]
  if (!mirrorId) return
  const noteId = /[?&]note=([0-9a-fA-F-]{36})/.exec(href)?.[1]
  if (noteId) {
    // 带上镜像 id：来源笔记打开后定位并高亮对应任务项。
    void router.push({ path: `/notes/${noteId}`, query: { todo: mirrorId } })
    return
  }
  const kbId = kbs.currentKbId
  if (!kbId) return
  try {
    const data = await request<{ source_note_id: string }>(
      `/kbs/${kbId}/todos/${mirrorId}`,
    )
    if (data?.source_note_id) void router.push(`/notes/${data.source_note_id}`)
  } catch (e: any) {
    toast.error(e.message || '找不到来源笔记')
  }
}

/** 点击块手柄：选中当前整块，便于复制、删除或直接开始输入。 */
function onDragHandleClick(event: MouseEvent) {
  const ed = editor.value
  if (!ed || props.readonly) return
  const rect = (event.currentTarget as HTMLElement).getBoundingClientRect()
  const hit = ed.view.posAtCoords({
    left: rect.right + 8,
    top: rect.top + rect.height / 2,
  })
  if (!hit) return
  const $pos = ed.state.doc.resolve(hit.pos)
  if ($pos.depth < 1) return
  try {
    const selection = NodeSelection.create(ed.state.doc, $pos.before(1))
    ed.view.dispatch(ed.state.tr.setSelection(selection))
    ed.view.focus()
  } catch {
    // 位于文档边界或原子节点内部时忽略，不影响正常拖动。
  }
}

/** @ 提及候选：当前知识库的笔记（排除正在编辑的这一篇）。 */
function mentionNotes() {
  return notesStore.notes.map((note) => ({
    id: note.id,
    title: note.title || '无标题',
    kind: note.kind,
  }))
}

/** @ 提及候选中的 Wiki 页面：当前知识库已编译页面。 */
const wikiPages = ref<MentionWikiPage[]>([])
let wikiPagesKb = ''

async function loadWikiPages() {
  const kbId = kbs.currentKbId
  if (!kbId) {
    wikiPages.value = []
    return
  }
  wikiPagesKb = kbId
  try {
    const pages = await request<MentionWikiPage[]>('/wiki', { kbId })
    if (wikiPagesKb === kbId) wikiPages.value = pages
  } catch {
    if (wikiPagesKb === kbId) wikiPages.value = []
  }
}

watch(
  () => kbs.currentKbId,
  () => void loadWikiPages(),
)
const imageInput = ref<HTMLInputElement | null>(null)
const chars = ref(0)
/** 选区变化计数：工具栏激活态与表格上下文按钮随光标移动刷新 */
const editorRevision = ref(0)

/** 表格上下文菜单的底色预设（与语雀一致的低饱和色）。 */
const TABLE_BG_COLORS = [
  { label: '浅黄', value: '#FEF3C7' },
  { label: '浅绿', value: '#DCFCE7' },
  { label: '浅蓝', value: '#DBEAFE' },
  { label: '浅粉', value: '#FCE7F3' },
  { label: '浅紫', value: '#EDE9FE' },
  { label: '浅灰', value: '#F1F5F9' },
]

/**
 * 气泡菜单始终保持挂载：随只读切换卸载会与 Teleport 的锚点冲突，
 * 导致 Vue 更新表格外的节点时丢失插入位置。只读时仅隐藏浮层。
 */
function shouldShowFormatBubble({ editor: ed }: { editor: Editor }): boolean {
  if (props.readonly || ed.isActive('table')) return false
  // 只在选中文本时展示格式气泡；光标停在空处时不打扰阅读与输入。
  const { selection } = ed.state
  return (
    selection instanceof TextSelection &&
    !selection.empty &&
    ed.state.doc.textBetween(selection.from, selection.to).length > 0
  )
}

function shouldShowTableBubble({ editor: ed }: { editor: Editor }): boolean {
  return !props.readonly && ed.isActive('table')
}

/**
 * Tiptap 气泡由 tippy 定位，默认挂在 body 下。body 带 --ui-scale 的 zoom，
 * tippy 写入的布局坐标会被再放大一次，4K 下气泡偏离选区且重叠正文。
 * 改挂到未缩放的 <html>，再给气泡本体补上 zoom，位置按视口坐标即正确。
 */
function bubbleTippyOptions(placement: 'top' | 'top-start') {
  return {
    duration: 120,
    placement,
    appendTo: () => document.documentElement,
    // tippy 默认 350px 上限按未缩放内容估算，zoom 后会把气泡裁窄。
    maxWidth: 'none',
  }
}

// Agent 已合并进 Simple：历史 agent 模式也按 Simple 渲染
const simple = computed(() => props.mode !== 'docx')
const isDocx = computed(() => props.mode === 'docx')

const placeholderText = computed(() => {
  if (props.readonly) return ''
  if (isDocx.value) return '在 A4 纸张上开始写作…'
  return '开始写作… 输入 / 插入块，选中文字呼出气泡菜单'
})

const footerHint = computed(() => {
  if (isDocx.value) return 'DOCX 模式 · 点击纸张上的页眉 / 页脚可直接编辑'
  return '输入 / 插入块 · 拖动左侧手柄调整块顺序 · 选中文字呼出气泡菜单'
})

// ---------- 页面偏好 ----------
const docxPrefs = ref<DocxPrefs>(
  props.docxPrefs ? resolveDocxPrefs(props.docxPrefs) : { ...DEFAULT_DOCX_PREFS },
)
const pagePrefs = ref<PagePrefs>(
  props.pagePrefs ? resolvePagePrefs(props.pagePrefs) : { ...DEFAULT_PAGE_PREFS },
)

watch(
  () => props.docxPrefs,
  (value) => {
    if (value) docxPrefs.value = resolveDocxPrefs(value)
  },
  { deep: true },
)
watch(
  () => props.pagePrefs,
  (value) => {
    if (value) pagePrefs.value = resolvePagePrefs(value)
  },
  { deep: true },
)

function onDocxPrefs(next: DocxPrefs) {
  docxPrefs.value = resolveDocxPrefs(next)
  emit('docx-prefs', docxPrefs.value)
}

// ---------- 代码块显示偏好（主题 / 行号 / 换行，按浏览器记忆） ----------
const CODE_PREFS_KEY = 'kiwi.editor.code-prefs.v1'

function loadCodePrefs(): CodePrefs {
  try {
    const raw = localStorage.getItem(CODE_PREFS_KEY)
    return raw ? resolveCodePrefs(JSON.parse(raw)) : { ...DEFAULT_CODE_PREFS }
  } catch {
    return { ...DEFAULT_CODE_PREFS }
  }
}

const codePrefs = ref<CodePrefs>(loadCodePrefs())
watch(
  codePrefs,
  (value) => {
    try {
      localStorage.setItem(CODE_PREFS_KEY, JSON.stringify(value))
    } catch {
      /* 隐私模式下忽略 */
    }
  },
  { deep: true },
)
function onCodePrefs(next: CodePrefs) {
  codePrefs.value = resolveCodePrefs(next)
}

// ---------- 代码块运行：Python 走后端，HTML / JS 在沙箱 iframe 中渲染 ----------
type RunKind = 'python' | 'html' | 'js'

interface CodeRunPayload {
  language: RunKind
  source: string
  code: string
}

const runOpen = ref(false)
const runPayload = ref<CodeRunPayload | null>(null)
const runResult = ref<RunCodeResult | null>(null)
const runLoading = ref(false)
const runError = ref('')
const previewNonce = ref(0)

const isPreviewRun = computed(
  () => runPayload.value?.language === 'html' || runPayload.value?.language === 'js',
)

function normalizeRunPayload(payload: { language?: string; code?: string }): CodeRunPayload | null {
  const source = String(payload.language || '').toLowerCase()
  const code = payload.code || ''
  if (!code.trim()) return null
  if (source === 'python' || source === 'python3' || source === 'py') {
    return { language: 'python', source, code }
  }
  if (source === 'html') return { language: 'html', source, code }
  if (source === 'javascript' || source === 'js') return { language: 'js', source, code }
  return null
}

const previewDocument = computed(() => {
  const payload = runPayload.value
  if (!payload) return ''
  if (payload.language === 'html' || payload.language === 'js') {
    return buildPreviewDocument(payload.language, payload.code)
  }
  return ''
})

async function executePython(code: string) {
  runLoading.value = true
  runError.value = ''
  runResult.value = null
  try {
    runResult.value = await runPython(code)
  } catch (e: any) {
    runError.value = e?.message || '运行失败'
  } finally {
    runLoading.value = false
  }
}

async function openCodeRun(payload: { language?: string; code?: string }) {
  const normalized = normalizeRunPayload(payload)
  if (!normalized) {
    toast.info('该语言暂不支持运行，可选择 Python / HTML / JavaScript')
    return
  }
  runPayload.value = normalized
  runResult.value = null
  runError.value = ''
  previewNonce.value += 1
  runOpen.value = true
  if (normalized.language === 'python') await executePython(normalized.code)
}

/** 工具栏「预览」：HTML/JS 切换光标所在代码块的正文内嵌预览。 */
function toggleInlineCodePreview(): boolean {
  const instance = editor.value
  if (!instance) return false
  const { state, view } = instance
  const { $from } = state.selection
  for (let depth = $from.depth; depth > 0; depth -= 1) {
    const node = $from.node(depth)
    if (node.type.name !== 'codeBlock') continue
    const pos = $from.before(depth)
    view.dispatch(
      view.state.tr.setNodeMarkup(pos, undefined, {
        ...node.attrs,
        preview: node.attrs.preview === false,
      }),
    )
    return true
  }
  return false
}

/** 工具栏运行：Python 结果直接插入当前代码块下方的正文结果块。 */
async function runPythonAtCursor(): Promise<boolean> {
  const instance = editor.value
  if (!instance) return false
  const { state } = instance
  const { $from } = state.selection
  for (let depth = $from.depth; depth > 0; depth -= 1) {
    const node = $from.node(depth)
    if (node.type.name !== 'codeBlock') continue
    const source = String(node.attrs.language || '').toLowerCase()
    if (!['python', 'python3', 'py'].includes(source)) return false
    const pos = $from.before(depth)
    const code = node.textContent
    let output: string
    try {
      output = formatRunResult(await runPython(code))
    } catch (e: any) {
      output = `运行失败：${e?.message || '无法连接运行服务'}`
    }
    upsertCodeOutput(instance, pos, code, output)
    return true
  }
  return false
}

function onToolbarRunCode(payload: { language?: string; code?: string }) {
  const normalized = normalizeRunPayload(payload)
  if (!normalized) {
    toast.info('该语言暂不支持运行，可选择 Python / HTML / JavaScript')
    return
  }
  if (normalized.language === 'python') {
    void runPythonAtCursor().then((handled) => {
      if (!handled) void openCodeRun(payload)
    })
    return
  }
  if (!toggleInlineCodePreview()) {
    toast.info('请把光标放在代码块内再切换预览')
  }
}

function rerunCode() {
  const payload = runPayload.value
  if (!payload) return
  if (payload.language === 'python') void executePython(payload.code)
  else previewNonce.value += 1
}

function closeCodeRun() {
  runOpen.value = false
}

function onRunCodeEvent(event: Event) {
  const detail = (event as CustomEvent).detail as { language?: string; code?: string } | null
  if (detail) void openCodeRun(detail)
}

function onCodeRunKeydown(event: KeyboardEvent) {
  if (runOpen.value && event.key === 'Escape') closeCodeRun()
}

function onCodeRunMessage(event: MessageEvent) {
  if (event.data === 'kiwi-code-run-close') closeCodeRun()
}

onMounted(() => {
  void loadWikiPages()
  void pluginsStore.ensureBlocks()
  // 组件插件只在编辑器 / 工作区阅读态按需执行脚本；设置页不会自动加载。
  void pluginsStore.ensureComponentBlocks()
  void extensionsStore.ensure().catch(() => {})
  window.addEventListener('kiwi-run-code', onRunCodeEvent)
  window.addEventListener('keydown', onCodeRunKeydown)
  window.addEventListener('keydown', onParagraphMenuKeydown)
  window.addEventListener('keydown', onFormatPainterKeydown)
  window.addEventListener('message', onCodeRunMessage)
  window.addEventListener('kiwi:word-preview-rendered', onPreviewRendered)
  // scroll 不冒泡，捕获阶段才能覆盖正文与 Word 预览两个滚动容器。
  document.addEventListener('scroll', onAnyScroll, true)
  scheduleHeadingSpy()
})
onBeforeUnmount(() => {
  window.removeEventListener('kiwi-run-code', onRunCodeEvent)
  window.removeEventListener('keydown', onCodeRunKeydown)
  window.removeEventListener('keydown', onParagraphMenuKeydown)
  window.removeEventListener('keydown', onFormatPainterKeydown)
  window.removeEventListener('message', onCodeRunMessage)
  window.clearTimeout(painterTimer)
  window.removeEventListener('kiwi:word-preview-rendered', onPreviewRendered)
  document.removeEventListener('scroll', onAnyScroll, true)
  cancelAnimationFrame(headingFrame)
})

const paper = computed(() =>
  docxPaperSize(docxPrefs.value.paper, docxPrefs.value.orientation),
)

/** 首页不同时使用首页专用页眉页脚（留空则不显示）。 */
const pageHeaderText = computed(() => {
  const prefs = docxPrefs.value
  if (prefs.differentFirstPage) return prefs.firstHeaderText.trim()
  return prefs.headerText.trim() || props.docTitle || '无标题文档'
})
const pageFooterText = computed(() => {
  const prefs = docxPrefs.value
  const template = prefs.differentFirstPage
    ? prefs.firstFooterText.trim()
    : prefs.footerText.trim()
  if (!template) {
    return prefs.differentFirstPage
      ? ''
      : `${docxPaperLabel(prefs)}  ·  第 ${docxPages.value} 页`
  }
  // 页脚位于纸张最底部，页码按最后一页显示；导出时由服务端逐页替换
  return template
    .replace(/\{page\}/gi, String(docxPages.value))
    .replace(/\{pages\}/gi, String(docxPages.value))
    .replace(/\{total\}/gi, String(docxPages.value))
})

/** 页眉/页脚距纸张边缘的距离（cm）与左右边距对齐。 */
const pageHeadStyle = computed(() => ({
  top: `${docxPrefs.value.headerDistance}cm`,
  left: `${docxPrefs.value.margins.left}cm`,
  right: `${docxPrefs.value.margins.right}cm`,
}))
const pageFootStyle = computed(() => ({
  bottom: `${docxPrefs.value.footerDistance}cm`,
  left: `${docxPrefs.value.margins.left}cm`,
  right: `${docxPrefs.value.margins.right}cm`,
}))

// ---------- 页眉 / 页脚：直接在纸张上编辑 ----------
const headerEditing = ref(false)
const footerEditing = ref(false)
const headerEditor = ref<HTMLElement | null>(null)
const footerEditor = ref<HTMLElement | null>(null)

/** 首页不同时，纸张上编辑的是「首页页眉 / 首页页脚」 */
const activeHeaderValue = computed(() =>
  docxPrefs.value.differentFirstPage
    ? docxPrefs.value.firstHeaderText
    : docxPrefs.value.headerText,
)
const activeFooterValue = computed(() =>
  docxPrefs.value.differentFirstPage
    ? docxPrefs.value.firstFooterText
    : docxPrefs.value.footerText,
)

const headerVisible = computed(
  () => isDocx.value && docxPrefs.value.showHeader && (!!pageHeaderText.value || !props.readonly),
)
const footerVisible = computed(
  () => isDocx.value && docxPrefs.value.showFooter && (!!pageFooterText.value || !props.readonly),
)

function focusEditable(el: HTMLElement, value: string) {
  el.textContent = value
  el.focus()
  const range = document.createRange()
  range.selectNodeContents(el)
  range.collapse(false)
  const selection = window.getSelection()
  selection?.removeAllRanges()
  selection?.addRange(range)
}

async function startHeaderEdit() {
  if (!isDocx.value || props.readonly) return
  headerEditing.value = true
  await nextTick()
  if (!headerEditor.value) return
  // 非「首页不同」时，空页眉默认显示文档标题，编辑时也从标题开始
  const value = docxPrefs.value.differentFirstPage
    ? activeHeaderValue.value
    : docxPrefs.value.headerText || props.docTitle || ''
  focusEditable(headerEditor.value, value)
}

async function startFooterEdit() {
  if (!isDocx.value || props.readonly) return
  footerEditing.value = true
  await nextTick()
  if (!footerEditor.value) return
  // 没有自定义页脚时从默认版式开始编辑，页码占位符可直接保留
  const value =
    activeFooterValue.value ||
    `${docxPaperLabel(docxPrefs.value)}  ·  第 {page} 页`
  focusEditable(footerEditor.value, value)
}

function normalizeLine(text: string) {
  return text
    .replace(/\s*\n+\s*/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
    .slice(0, 160)
}

function commitHeader() {
  if (!headerEditing.value) return
  const text = normalizeLine(headerEditor.value?.innerText ?? '')
  headerEditing.value = false
  if (text === activeHeaderValue.value.trim()) return
  onDocxPrefs({
    ...docxPrefs.value,
    ...(docxPrefs.value.differentFirstPage
      ? { firstHeaderText: text }
      : { headerText: text }),
  })
}

function commitFooter() {
  if (!footerEditing.value) return
  const text = normalizeLine(footerEditor.value?.innerText ?? '')
  footerEditing.value = false
  if (text === activeFooterValue.value.trim()) return
  onDocxPrefs({
    ...docxPrefs.value,
    ...(docxPrefs.value.differentFirstPage
      ? { firstFooterText: text }
      : { footerText: text }),
  })
}

function cancelHeaderEdit() {
  headerEditing.value = false
}

function cancelFooterEdit() {
  footerEditing.value = false
}

/** 页眉页脚只接受纯文本，粘贴时去掉 HTML 与换行 */
function pastePlain(event: ClipboardEvent) {
  event.preventDefault()
  const text = (event.clipboardData?.getData('text/plain') || '').replace(/\s+/g, ' ')
  document.execCommand('insertText', false, text)
}

/** 页面缩放（所有模式可用，仅屏幕预览，不影响导出） */
const docxZoom = ref(100)
const ZOOM_STEPS = [70, 80, 90, 100, 110, 120, 130]
/** 分页排版后的总页数（页脚在纸张底部，页码即最后一页） */
const docxPages = ref(1)

function zoomBy(direction: -1 | 1) {
  const current = ZOOM_STEPS.indexOf(docxZoom.value)
  const index = current < 0 ? ZOOM_STEPS.indexOf(100) : current
  docxZoom.value =
    ZOOM_STEPS[Math.min(ZOOM_STEPS.length - 1, Math.max(0, index + direction))]
}

const sheetStyle = computed(() => {
  if (isDocx.value) {
    const prefs = docxPrefs.value
    const margins = prefs.margins
    const indent = prefs.firstLineIndent
    const fixedLine = prefs.lineHeightMode === 'fixed'
    return {
      width: `${paper.value.width}cm`,
      maxWidth: '100%',
      minHeight: `${paper.value.height}cm`,
      padding: `${margins.top}cm ${margins.right}cm ${margins.bottom}cm ${margins.left}cm`,
      background: docxBackgroundColor(prefs.background),
      '--doc-bg': docxBackgroundColor(prefs.background),
      '--doc-font': docxFontStack(prefs.font),
      '--doc-size': `${prefs.size}px`,
      '--doc-line': fixedLine ? `${(prefs.lineHeightFixed * 4) / 3}px` : String(prefs.lineHeight),
      '--doc-space-before': `${prefs.spaceBefore}px`,
      '--doc-space-after': `${prefs.spaceAfter}px`,
      '--doc-indent-left': `${prefs.indentLeft}em`,
      '--doc-indent-right': `${prefs.indentRight}em`,
      '--doc-first': `${prefs.hangingIndent ? -indent : indent}em`,
      '--doc-hang': prefs.hangingIndent ? `${indent}em` : '0em',
      '--doc-letter': `${prefs.letterSpacing}px`,
      zoom: `${docxZoom.value}%`,
    }
  }
  return {
    width: '100%',
    maxWidth: `${pageWidthMax(pagePrefs.value.width)}px`,
    background: pageBackgroundColor(pagePrefs.value.background),
    '--doc-bg': pageBackgroundColor(pagePrefs.value.background),
    '--doc-size': `${pagePrefs.value.fontSize}px`,
    '--doc-line': String(pagePrefs.value.lineHeight),
    zoom: `${docxZoom.value}%`,
  }
})

const canvasStyle = computed(() =>
  isDocx.value ? { padding: `${docxPrefs.value.pageGap}px` } : undefined,
)

const footerIcon = computed(() => (props.mode === 'docx' ? 'bookOpen' : 'sparkle'))

// ---------- 文档目录（标题大纲） ----------
interface OutlineItem {
  level: number
  text: string
  pos: number
}
const headings = ref<OutlineItem[]>([])

// ---------- 目录浮层高度：按视口实际可用空间计算，确保不越过页面底部 ----------
const outlineSlot = ref<HTMLElement | null>(null)
const outlineMaxHeight = ref('')
let outlineHeightFrame = 0
let outlineResizeObserver: ResizeObserver | null = null

function uiScale(): number {
  const raw = getComputedStyle(document.documentElement).getPropertyValue('--ui-scale')
  const value = Number.parseFloat(raw)
  return Number.isFinite(value) && value > 0 ? value : 1
}

function updateOutlineHeight() {
  const slot = outlineSlot.value
  if (!slot) {
    outlineMaxHeight.value = ''
    return
  }
  // getBoundingClientRect / innerHeight 都是缩放后的视口坐标；max-height 处于
  // body zoom 的布局坐标中，需要除以 --ui-scale 才不会在 4K 下超出页面。
  const scale = uiScale()
  const top = slot.getBoundingClientRect().top
  // 以实际滚动容器底部为准（可能被底部工具条压缩），再收敛到视口
  let bottom = window.innerHeight
  let parent = slot.parentElement
  while (parent) {
    const overflowY = getComputedStyle(parent).overflowY
    if (/(auto|scroll)/.test(overflowY)) {
      bottom = Math.min(bottom, parent.getBoundingClientRect().bottom)
      break
    }
    parent = parent.parentElement
  }
  // 留出 16px 底部呼吸空间；可视区过矮时至少保留可用高度
  const available = Math.max(220, Math.round((bottom - top) / scale - 16))
  outlineMaxHeight.value = `${available}px`
}

function scheduleOutlineHeight() {
  cancelAnimationFrame(outlineHeightFrame)
  outlineHeightFrame = requestAnimationFrame(updateOutlineHeight)
}

function detachOutlineHeightListeners() {
  window.removeEventListener('scroll', scheduleOutlineHeight, true)
  window.removeEventListener('resize', scheduleOutlineHeight)
  outlineResizeObserver?.disconnect()
  outlineResizeObserver = null
  cancelAnimationFrame(outlineHeightFrame)
}

function attachOutlineHeightListeners() {
  detachOutlineHeightListeners()
  window.addEventListener('scroll', scheduleOutlineHeight, true)
  window.addEventListener('resize', scheduleOutlineHeight)
  if (typeof ResizeObserver !== 'undefined') {
    outlineResizeObserver = new ResizeObserver(scheduleOutlineHeight)
    const canvas = outlineSlot.value?.closest('.editor-canvas')
    if (canvas) outlineResizeObserver.observe(canvas)
  }
  updateOutlineHeight()
}

/** 当前滚动位置对应的目录项；-1 表示尚未定位。 */
const activeHeading = ref(-1)
let headingFrame = 0

// ---------- 目录层级：展开 / 折叠与最大展示级别 ----------
const OUTLINE_DEPTH_KEY = 'kiwi.outline.depth'
const outlineDepth = ref<number>(6)
try {
  const saved = Number(window.localStorage.getItem(OUTLINE_DEPTH_KEY))
  if (Number.isFinite(saved) && saved >= 1 && saved <= 6) outlineDepth.value = saved
} catch {
  /* localStorage 不可用时使用默认值 */
}
watch(outlineDepth, (value) => {
  try {
    window.localStorage.setItem(OUTLINE_DEPTH_KEY, String(value))
  } catch {
    /* ignore */
  }
})

const collapsedHeadings = ref<Set<number>>(new Set())

const outlineParents = computed<number[]>(() => {
  const items = headings.value
  const parents: number[] = new Array(items.length).fill(-1)
  const stack: number[] = []
  items.forEach((item, index) => {
    while (stack.length && items[stack[stack.length - 1]].level >= item.level) stack.pop()
    parents[index] = stack.length ? stack[stack.length - 1] : -1
    stack.push(index)
  })
  return parents
})

interface OutlineRow {
  item: OutlineItem
  index: number
  hasChildren: boolean
}

/** 当前深度内带子标题的目录项，用于折叠切换与“展开/收起全部”。 */
const outlineChildIndexes = computed<number[]>(() => {
  const items = headings.value
  const parents = outlineParents.value
  const withinDepth = items.map((item) => item.level <= outlineDepth.value)
  const parentsWithChildren = new Set<number>()
  parents.forEach((parent, index) => {
    if (parent < 0 || !withinDepth[index]) return
    let cursor: number = parent
    while (cursor >= 0) {
      if (withinDepth[cursor]) parentsWithChildren.add(cursor)
      cursor = parents[cursor]
    }
  })
  return [...parentsWithChildren].sort((a, b) => a - b)
})

const outlineRows = computed<OutlineRow[]>(() => {
  const items = headings.value
  const parents = outlineParents.value
  const withinDepth = items.map((item) => item.level <= outlineDepth.value)
  const withChildren = new Set(outlineChildIndexes.value)
  const rows: OutlineRow[] = []
  items.forEach((item, index) => {
    if (!withinDepth[index]) return
    let cursor = parents[index]
    while (cursor >= 0) {
      if (collapsedHeadings.value.has(cursor)) return
      cursor = parents[cursor]
    }
    rows.push({ item, index, hasChildren: withChildren.has(index) })
  })
  return rows
})

const hasExpandedGroups = computed(() =>
  outlineChildIndexes.value.some((index) => !collapsedHeadings.value.has(index)),
)

function toggleAllHeadings() {
  collapsedHeadings.value = hasExpandedGroups.value
    ? new Set(outlineChildIndexes.value)
    : new Set()
}

/** 被折叠时高亮最近的可见祖先，保证滚动位置仍有反馈。 */
const activeOutlineIndex = computed(() => {
  if (activeHeading.value < 0) return -1
  const rowIndexes = new Set(outlineRows.value.map((row) => row.index))
  if (rowIndexes.has(activeHeading.value)) return activeHeading.value
  let cursor = outlineParents.value[activeHeading.value] ?? -1
  while (cursor >= 0) {
    if (rowIndexes.has(cursor)) return cursor
    cursor = outlineParents.value[cursor] ?? -1
  }
  return -1
})

function toggleHeading(index: number) {
  const next = new Set(collapsedHeadings.value)
  if (next.has(index)) next.delete(index)
  else next.add(index)
  collapsedHeadings.value = next
}

watch(
  () => props.noteId,
  () => {
    collapsedHeadings.value = new Set()
  },
)

function syncOutline() {
  const ed = editor.value
  if (!ed) {
    headings.value = []
    return
  }
  const items: OutlineItem[] = []
  ed.state.doc.descendants((node, pos) => {
    if (node.type.name === 'heading') {
      const text = node.textContent.trim()
      if (text) items.push({ level: Number(node.attrs.level) || 1, text, pos })
    }
  })
  headings.value = items
  void nextTick(() => scheduleHeadingSpy())
}

function nearestScrollParent(el: HTMLElement | null): HTMLElement | null {
  let node = el?.parentElement ?? null
  while (node) {
    const style = window.getComputedStyle(node)
    if (/(auto|scroll)/.test(style.overflowY) && node.scrollHeight > node.clientHeight + 4) {
      return node
    }
    node = node.parentElement
  }
  return (document.scrollingElement as HTMLElement | null) ?? null
}

/**
 * 收集目录项对应的 DOM。
 * Word 预览打开时以预览中的导出标题为准——用户此刻看到的就是分页后的文档。
 */
function outlineAnchors(): Array<{ el: HTMLElement; index: number }> {
  const preview = document.querySelector<HTMLElement>('.word-preview-pane')
  if (preview && preview.offsetParent !== null) {
    const previewHeads = Array.from(
      preview.querySelectorAll<HTMLElement>('[class*="kiwi-docx_heading"]'),
    ).filter((el) => (el.textContent || '').trim())
    if (previewHeads.length) {
      const normalize = (value: string) => value.replace(/\s+/g, '')
      const anchors: Array<{ el: HTMLElement; index: number }> = []
      previewHeads.forEach((el, previewIndex) => {
        const text = normalize(el.textContent || '')
        // 导出文档与正文的标题顺序一致；数量不一致时按文本匹配。
        if (headings.value[previewIndex] && normalize(headings.value[previewIndex].text) === text) {
          anchors.push({ el, index: previewIndex })
        } else {
          const index = headings.value.findIndex((item) => normalize(item.text) === text)
          if (index >= 0) anchors.push({ el, index })
        }
      })
      if (anchors.length) return anchors
    }
  }
  const ed = editor.value
  if (!ed) return []
  return headings.value.flatMap((item, index) => {
    const dom = ed.view.nodeDOM(item.pos)
    return dom instanceof HTMLElement ? [{ el: dom, index }] : []
  })
}

/** 以滚动容器可视区顶部为基准，取最后一个越过分界线的标题。 */
function updateActiveHeading() {
  const anchors = outlineAnchors()
  if (!anchors.length) {
    activeHeading.value = -1
    return
  }
  const scroller = nearestScrollParent(anchors[0].el)
  const boundary = (scroller?.getBoundingClientRect().top ?? 0) + 84
  let active = anchors[0].index
  for (const anchor of anchors) {
    if (anchor.el.getBoundingClientRect().top <= boundary) active = anchor.index
    else break
  }
  activeHeading.value = active
}

function scheduleHeadingSpy() {
  cancelAnimationFrame(headingFrame)
  headingFrame = requestAnimationFrame(updateActiveHeading)
}

function onAnyScroll() {
  if (props.showOutline) scheduleHeadingSpy()
}

function onPreviewRendered() {
  void nextTick(() => scheduleHeadingSpy())
}

function scrollToHeading(item: OutlineItem) {
  const ed = editor.value
  if (!ed) return
  const preview = document.querySelector<HTMLElement>('.word-preview-pane')
  if (preview && preview.offsetParent !== null) {
    const target = outlineAnchors().find((anchor) => anchor.index === headings.value.indexOf(item))
    if (target) {
      target.el.scrollIntoView({ behavior: 'smooth', block: 'start' })
      activeHeading.value = headings.value.indexOf(item)
      return
    }
  }
  ed.chain().focus().setTextSelection(item.pos + 1).run()
  const dom = ed.view.nodeDOM(item.pos)
  if (dom instanceof HTMLElement) {
    dom.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }
  activeHeading.value = headings.value.indexOf(item)
}

watch(
  () => props.showOutline,
  async (show) => {
    if (show) {
      syncOutline()
      await nextTick()
      attachOutlineHeightListeners()
    } else {
      detachOutlineHeightListeners()
    }
  },
)

onMounted(() => {
  if (props.showOutline) {
    void nextTick(() => attachOutlineHeightListeners())
  }
})

onBeforeUnmount(detachOutlineHeightListeners)

// ---------- 文件上传 ----------
interface AttachmentOut {
  id: string
  filename: string
  url: string
  content_type: string
  size: number
}

async function uploadFile(file: File): Promise<AttachmentOut> {
  if (!props.noteId) throw new Error('请先保存笔记后再插入文件')
  const fd = new FormData()
  fd.append('file', file)
  return upload<AttachmentOut>(
    `/attachments?note_id=${encodeURIComponent(props.noteId)}`,
    fd,
    kbs.currentKbId,
  )
}

/** 上传并插入图片（粘贴 / 拖拽图片走这里） */
async function uploadAndInsert(file: File, asImage: boolean) {
  try {
    const att = await uploadFile(file)
    const ed = editor.value
    if (!ed) return
    if (asImage && att.content_type.startsWith('image/')) {
      ed.chain().focus().setImage({ src: att.url, alt: att.filename }).run()
    } else {
      ed.chain()
        .focus()
        .insertContent({
          type: 'text',
          text: att.filename,
          marks: [{ type: 'link', attrs: { href: att.url } }],
        })
        .run()
    }
  } catch (e: any) {
    toast.error(e.message || '上传失败')
  }
}

function pickImage() {
  imageInput.value?.click()
}

function onPick(e: Event) {
  const input = e.target as HTMLInputElement
  const files = Array.from(input.files || [])
  for (const file of files) void uploadAndInsert(file, true)
  input.value = ''
}

// ---------- 插入链接 / 附件（展示方式选择） ----------
const embedDialogOpen = ref(false)
const embedDialogTab = ref<EmbedTab>('file')
const embedDialogUrl = ref('')
const embedDialogFiles = ref<File[]>([])
const embedSelectionText = ref('')
const embedRange = ref<{ from: number; to: number } | null>(null)

function captureSelection() {
  const ed = editor.value
  if (!ed) return { text: '', from: 0, to: 0 }
  const sel = ed.state.selection
  // 原子块（如已插入的内嵌卡）被 NodeSelection 选中时，直接把插入点放到块后，
  // 否则 insertContent 会把选中的块替换掉。
  if (sel instanceof NodeSelection) {
    return { text: '', from: sel.to, to: sel.to }
  }
  const { from, to } = sel
  return { text: ed.state.doc.textBetween(from, to, ' '), from, to }
}

/** 插入内嵌块并把光标折叠到块后，避免连续插入时相互替换。 */
function insertEmbedNode(ed: Editor, attrs: Record<string, any>) {
  const sel = ed.state.selection
  const chain = ed.chain().focus()
  if (sel instanceof NodeSelection) chain.setTextSelection(sel.to)
  chain.insertContent({ type: 'embedBlock', attrs }).run()
  if (ed.state.selection instanceof NodeSelection) {
    ed.chain().setTextSelection(ed.state.selection.to).run()
  }
}

function openEmbedDialog(tab: EmbedTab, files: File[] = [], url = '') {
  const selection = captureSelection()
  embedDialogTab.value = tab
  embedDialogUrl.value = url
  embedDialogFiles.value = files
  embedSelectionText.value = selection.text
  embedRange.value = { from: selection.from, to: selection.to }
  embedDialogOpen.value = true
}

function pickAttachment() {
  openEmbedDialog('file')
}

/** 气泡菜单文字颜色：模板内联箭头函数无法收窄 editor，统一在脚本里判空。 */
function applyBubbleTextColor(color: string | null) {
  if (!editor.value) return
  applyTextFormat(editor.value, { color })
}

function openLinkDialog(ed: Editor) {
  const existing = ed.getAttributes('link').href || ''
  openEmbedDialog('link', [], existing)
}

function closeEmbedDialog() {
  embedDialogOpen.value = false
  embedDialogFiles.value = []
}

function applyLinkRange(ed: Editor) {
  const range = embedRange.value
  if (range) ed.chain().focus().setTextSelection(range)
  else ed.chain().focus()
}

function insertLinkEmbed(payload: {
  url: string
  title: string
  meta: LinkMeta | null
}) {
  const ed = editor.value
  if (!ed) return
  const meta = payload.meta
  const attrs = embedAttrs({
    kind: 'link',
    url: meta?.final_url || payload.url,
    title: payload.title,
    site: meta?.site ?? '',
    excerpt: meta?.excerpt ?? '',
    favicon: meta?.favicon ?? '',
    display: 'content',
  })
  applyLinkRange(ed)
  insertEmbedNode(ed, attrs)
  closeEmbedDialog()
}

async function insertAttachmentEmbeds(payload: { files: File[] }) {
  closeEmbedDialog()
  for (const file of payload.files) {
    try {
      const att = await uploadFile(file)
      const ed = editor.value
      if (!ed) return
      insertEmbedNode(
        ed,
        embedAttrs({
          kind: 'file',
          url: att.url,
          title: att.filename,
          filename: att.filename,
          contentType: att.content_type,
          size: att.size,
          display: 'content',
        }),
      )
    } catch (e: any) {
      toast.error(e.message || `${file.name} 上传失败`)
    }
  }
}

function promptVideo(ed: Editor) {
  const url = window.prompt('视频地址（mp4 / webm / /media/…）', '')
  if (url === null) return
  const src = url.trim()
  if (!src) return
  if (!/^(https?:\/\/|\/media\/)/i.test(src)) {
    toast.error('请输入 http(s) 或 /media 开头的视频地址')
    return
  }
  ed.chain().focus().setVideo({ src }).run()
}

function promptYoutube(ed: Editor) {
  const url = window.prompt('YouTube 视频链接', 'https://www.youtube.com/watch?v=')
  if (url === null) return
  const src = url.trim()
  if (!src) return
  const ok = ed.chain().focus().setYoutubeVideo({ src }).run()
  if (!ok) toast.error('请输入有效的 YouTube 链接')
}

/** 工具栏：光标在折叠块内则解除，否则插入新的折叠块 */
function toggleDetailsBlock(ed: Editor) {
  if (ed.isActive('details')) ed.chain().focus().unsetDetails().run()
  else ed.chain().focus().insertDetails().run()
}

/** 工具栏：插入触发字符，交给 @ / : 建议菜单选择 */
function insertSuggestionChar(char: '@' | ':') {
  editor.value?.chain().focus().insertContent(char).run()
}

// ---------- 插入表格（可设置行列数） ----------
const tableDialogOpen = ref(false)
let tableInsertPos: number | null = null

/** 记录当前插入点，打开行列设置弹窗（斜杠命令会先删除 /query 文本）。 */
function openTableDialog(ed: Editor) {
  tableInsertPos = ed.state.selection.from
  tableDialogOpen.value = true
}

function insertTable(size: { rows: number; cols: number }) {
  const ed = editor.value
  tableDialogOpen.value = false
  if (!ed) return
  const chain = ed.chain().focus()
  if (tableInsertPos != null) chain.setTextSelection(tableInsertPos)
  chain.insertTable({ ...size, withHeaderRow: true }).run()
  tableInsertPos = null
}

function closeTableDialog() {
  tableDialogOpen.value = false
  tableInsertPos = null
}

function openTableFromToolbar() {
  if (editor.value) openTableDialog(editor.value)
}

// ---------- 插入来源引用块 ----------
const sourceQuoteOpen = ref(false)
const sourceQuoteSeed = ref('')
const quoteMarkdown = new MarkdownIt({ html: false, breaks: false })

/** 打开素材选择弹窗；若编辑器里有选中文字，作为默认引用片段。 */
function openSourceQuote(ed: Editor) {
  const { from, to } = ed.state.selection
  sourceQuoteSeed.value = from !== to ? ed.state.doc.textBetween(from, to, '\n') : ''
  sourceQuoteOpen.value = true
}

function insertSourceQuote(payload: { markdown: string }) {
  const ed = editor.value
  sourceQuoteOpen.value = false
  if (!ed) return
  ed.chain().focus().insertContent(quoteMarkdown.render(payload.markdown)).run()
  toast.success('已插入来源引用块')
}

// ---------- 关联知识点块 ----------
const knowledgePointOpen = ref(false)
const knowledgePointSeed = ref('')

function openKnowledgePoint(ed: Editor) {
  const { from, to } = ed.state.selection
  knowledgePointSeed.value = from !== to ? ed.state.doc.textBetween(from, to, '\n') : ''
  knowledgePointOpen.value = true
}

function insertKnowledgePoint(payload: { html: string }) {
  const ed = editor.value
  knowledgePointOpen.value = false
  if (!ed) return
  ed.chain().focus().insertContent(payload.html).run()
  toast.success('已插入知识点关联块')
}

/** 插入今天的日期胶囊（斜杠菜单「日期」）。 */
function insertToday() {
  editor.value?.chain().focus().insertDate({ date: todayISO() }).run()
}

/** 工具栏「插入组件」：与斜杠菜单共用同一批扩展块。 */
function insertComponent(key: string) {
  const ed = editor.value
  if (!ed) return
  const chain = ed.chain().focus()
  // 选中的是原子块时先折叠到块后，避免 insertContent 直接替换掉它。
  if (ed.state.selection instanceof NodeSelection) {
    chain.setTextSelection(ed.state.selection.to)
  }
  if (key === 'date') chain.insertDate({ date: todayISO() })
  else if (key === 'formula') chain.insertFormula()
  else if (key === 'mermaid') chain.insertMermaid()
  else if (key === 'gallery') chain.insertGallery()
  else if (key === 'columns2') chain.insertColumns({ count: 2 })
  else if (key === 'columns3') chain.insertColumns({ count: 3 })
  else if (key === 'calendar') chain.insertCalendar()
  else if (key === 'datatable') chain.insertDataTable()
  else if (key === 'taskProgress') chain.insertTaskProgress()
  chain.run()
  if (ed.state.selection instanceof NodeSelection) {
    ed.chain().setTextSelection(ed.state.selection.to).run()
  }
}

/** 第三方组件插件：插入通用插件节点，由运行时组件渲染。 */
function insertPluginBlockEntry(ed: Editor, block: PluginBlock) {
  void pluginsStore.ensureComponentBlocks()
  const chain = ed.chain().focus()
  // 选中的是原子块时先折叠到块后，避免 insertContent 直接替换掉它。
  if (ed.state.selection instanceof NodeSelection) {
    chain.setTextSelection(ed.state.selection.to)
  }
  chain
    .insertPluginBlock({
      pluginKey: block.plugin_key,
      blockType: block.type,
      props: { ...(block.default_props || {}) },
    })
    .run()
  if (ed.state.selection instanceof NodeSelection) {
    ed.chain().setTextSelection(ed.state.selection.to).run()
  }
}

/** DOCX 模式：在光标处插入分页符 */
function insertPageBreak() {
  editor.value?.chain().focus().insertContent({ type: 'pageBreak' }).run()
}

// ---------- DOCX 段落排版：右击正文打开，作用于光标 / 选中的段落 ----------
interface ParagraphMenuState {
  x: number
  y: number
  range: { from: number; to: number }
}

const paragraphMenu = ref<ParagraphMenuState | null>(null)
const paragraphDialogOpen = ref(false)
const paragraphRange = ref<{ from: number; to: number } | null>(null)
let applyingSavedFormats = false
let contextMenuDom: HTMLElement | null = null

interface MentionMenuState {
  x: number
  y: number
  pos: number
  size: number
  id: string
  label: string
  target: 'note' | 'wiki'
  display: MentionDisplay
}
const mentionMenu = ref<MentionMenuState | null>(null)

function closeParagraphMenu() {
  paragraphMenu.value = null
}

function closeMentionMenu() {
  mentionMenu.value = null
}

function closeContextMenus() {
  closeParagraphMenu()
  closeMentionMenu()
}

/** 从右击的 mention DOM 找回文档位置与节点。 */
function mentionAtDom(
  view: {
    state: any
    posAtCoords: (coords: { left: number; top: number }) => any
    posAtDOM?: (node: Node, offset: number) => number
  },
  element: HTMLElement,
): { pos: number; node: any } | null {
  const id = element.getAttribute('data-id') || ''
  const { doc } = view.state

  // 卡片 / 嵌入是块级节点视图，直接由 DOM 反查位置最可靠
  if (view.posAtDOM) {
    try {
      const domPos = view.posAtDOM(element, 0)
      const node = doc.nodeAt(domPos)
      if (node?.type.name === 'mention') {
        return { pos: domPos, node }
      }
    } catch {
      /* 节点视图不在文档中时回退到坐标命中 */
    }
  }

  const rect = element.getBoundingClientRect()
  const coords = view.posAtCoords({
    left: rect.left + rect.width / 2,
    top: rect.top + rect.height / 2,
  })
  const candidates: { pos: number; node: any }[] = []
  if (coords) {
    const $pos = doc.resolve(coords.pos)
    if ($pos.nodeBefore?.type.name === 'mention') {
      candidates.push({ pos: coords.pos - $pos.nodeBefore.nodeSize, node: $pos.nodeBefore })
    }
    if ($pos.nodeAfter?.type.name === 'mention') {
      candidates.push({ pos: coords.pos, node: $pos.nodeAfter })
    }
    doc.nodesBetween(
      Math.max(0, coords.pos - 2),
      Math.min(doc.content.size, coords.pos + 2),
      (node: any, pos: number) => {
        if (node.type.name === 'mention') candidates.push({ pos, node })
      },
    )
  }
  const hit = candidates.find((item) => String(item.node.attrs.id) === id) ?? candidates[0]
  if (hit) return hit

  // 最末兜底：按 data-id 全文档查找（同名提及可能取第一个）
  if (id) {
    let found: { pos: number; node: any } | null = null
    doc.descendants((node: any, pos: number) => {
      if (!found && node.type.name === 'mention' && String(node.attrs.id) === id) {
        found = { pos, node }
      }
      return !found
    })
    if (found) return found
  }
  return null
}

/**
 * @ 提及节点是 contenteditable=false 的 NodeView，ProseMirror 不会把
 * handleDOMEvents 里的 contextmenu 派发进来；在编辑器根节点上原生监听。
 */
function onEditorContextMenu(event: MouseEvent) {
  if (props.readonly) return
  const ed = editor.value
  if (!ed) return
  const target = event.target as HTMLElement | null
  const mentionEl = target?.closest?.('[data-type="mention"]') as HTMLElement | null
  if (!mentionEl) return
  event.preventDefault()
  event.stopPropagation()
  const found = mentionAtDom(ed.view, mentionEl)
  if (!found) return
  closeParagraphMenu()
  const x = Math.min(event.clientX, Math.max(8, window.innerWidth - 240))
  const y = Math.min(event.clientY, Math.max(8, window.innerHeight - 250))
  mentionMenu.value = {
    x,
    y,
    pos: found.pos,
    size: found.node.nodeSize,
    id: String(found.node.attrs.id ?? ''),
    label: String(found.node.attrs.label ?? ''),
    target: found.node.attrs.target === 'wiki' ? 'wiki' : 'note',
    display: normalizeMentionDisplay(found.node.attrs.display),
  }
}

function openMentionNote() {
  const menu = mentionMenu.value
  if (menu?.id) {
    void router.push(menu.target === 'wiki' ? `/wiki/${menu.id}` : `/notes/${menu.id}`)
  }
  closeMentionMenu()
}

function setMentionDisplay(display: MentionDisplay) {
  const menu = mentionMenu.value
  const ed = editor.value
  if (menu && ed) {
    const node = ed.state.doc.nodeAt(menu.pos)
    if (node?.type.name === 'mention') {
      const tr = ed.state.tr.setNodeMarkup(menu.pos, undefined, {
        ...node.attrs,
        display,
      })
      const afterPos = menu.pos + node.nodeSize
      const after = tr.doc.nodeAt(afterPos)
      if (display === 'mention') {
        // 从独占一行的卡片切回行内时补一个空格，避免与后文粘连
        if (after?.isText && after.text && !/^\s/.test(after.text)) {
          tr.insertText(' ', afterPos)
        }
      } else if (after?.isText && after.text?.startsWith(' ')) {
        // 卡片 / 嵌入自带外边距，去掉插入时留下的空格
        tr.delete(afterPos, afterPos + 1)
      }
      ed.view.dispatch(tr)
    }
  }
  closeMentionMenu()
}

function removeMention() {
  const menu = mentionMenu.value
  const ed = editor.value
  if (menu && ed) {
    const node = ed.state.doc.nodeAt(menu.pos)
    if (node?.type.name === 'mention') {
      ed.view.dispatch(ed.state.tr.delete(menu.pos, menu.pos + node.nodeSize))
    }
  }
  closeMentionMenu()
}

function openParagraphDialog() {
  const menu = paragraphMenu.value
  paragraphRange.value = menu?.range ?? null
  closeParagraphMenu()
  paragraphDialogOpen.value = true
}

function closeParagraphDialog() {
  paragraphDialogOpen.value = false
  paragraphRange.value = null
}

function applyParagraphFromDialog(patch: ParagraphFormatPatch) {
  const ed = editor.value
  if (ed) applyParagraphFormat(ed, patch, paragraphRange.value)
  closeParagraphDialog()
}

function resetParagraphFormat() {
  const ed = editor.value
  if (ed) clearParagraphFormat(ed, paragraphMenu.value?.range ?? null)
  closeParagraphMenu()
}

function onParagraphMenuKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape') closeContextMenus()
}

/** 加载 / 外部替换正文后重新套用已保存的段落格式。 */
function applySavedParagraphFormats(target?: Editor | null) {
  const ed = target ?? editor.value
  if (!ed || applyingSavedFormats) return
  applyingSavedFormats = true
  try {
    applyParagraphFormats(ed, props.paragraphFormats)
    applyTextFormats(ed, props.textFormats)
  } finally {
    applyingSavedFormats = false
  }
}

// ---------- 格式刷：复制当前字符 / 段落格式，应用到下一个选区 ----------
interface FormatPainterState {
  bold: boolean
  italic: boolean
  underline: boolean
  strike: boolean
  code: boolean
  /** null 表示来源没有高亮；空字符串表示默认高亮色 */
  highlight: string | null
  textStyle: { font?: DocxFont; size?: number; color?: string }
  /** 段落排版的完整快照（未显式设置的字段为 null） */
  block: ParagraphFormatPatch
  /** 来源选区；用于避免把格式重复套回来源位置 */
  sourceRange: { from: number; to: number } | null
}

const PARAGRAPH_FORMAT_KEYS: Array<keyof ParagraphFormatPatch> = [
  'font',
  'size',
  'lineHeight',
  'lineHeightMode',
  'lineHeightFixed',
  'spaceBefore',
  'spaceAfter',
  'indentLeft',
  'indentRight',
  'firstLineIndent',
  'hangingIndent',
  'align',
]

const formatPainter = ref<FormatPainterState | null>(null)
let painterApplying = false
let painterTimer: number | undefined

function cancelFormatPainter(notify = false) {
  window.clearTimeout(painterTimer)
  painterTimer = undefined
  const had = !!formatPainter.value
  formatPainter.value = null
  if (notify && had) toast.info('已取消格式刷')
}

/** 读取来源位置的格式；未设置的段落属性也记成 null，应用时才能完整覆盖目标。 */
function captureFormatPainterState(ed: Editor): FormatPainterState {
  const { from, to, empty } = ed.state.selection
  const block: ParagraphFormatPatch = {}
  const current = currentParagraphFormat(ed)
  for (const key of PARAGRAPH_FORMAT_KEYS) {
    ;(block as Record<string, unknown>)[key] = current[key] ?? null
  }
  const highlight = ed.getAttributes('highlight')
  return {
    bold: ed.isActive('bold'),
    italic: ed.isActive('italic'),
    underline: ed.isActive('underline'),
    strike: ed.isActive('strike'),
    code: ed.isActive('code'),
    highlight: ed.isActive('highlight') ? String(highlight.color ?? '') : null,
    textStyle: normalizeTextStyleAttrs(ed.getAttributes('textStyle')),
    block,
    sourceRange: empty ? null : { from, to },
  }
}

function armFormatPainter() {
  const ed = editor.value
  if (!ed || props.readonly) return
  formatPainter.value = captureFormatPainterState(ed)
  toast.info('格式已复制：选择目标内容应用，Esc 取消')
}

function applyFormatPainter(ed: Editor): boolean {
  const formats = formatPainter.value
  if (!formats || painterApplying) return false
  painterApplying = true
  try {
    const chain = ed.chain().focus()
    // 代码块内没有行内 mark，只同步段落排版。
    if (!ed.isActive('codeBlock')) {
      if (formats.bold) chain.setBold()
      else chain.unsetBold()
      if (formats.italic) chain.setItalic()
      else chain.unsetItalic()
      if (formats.underline) chain.setUnderline()
      else chain.unsetUnderline()
      if (formats.strike) chain.setStrike()
      else chain.unsetStrike()
      if (formats.code) chain.setCode()
      else chain.unsetCode()
      if (formats.highlight !== null) {
        chain.setHighlight({ color: formats.highlight })
      } else {
        chain.unsetHighlight()
      }
      if (
        formats.textStyle.font ||
        formats.textStyle.size ||
        formats.textStyle.color
      ) {
        chain.setMark('textStyle', formats.textStyle)
      } else {
        chain.unsetMark('textStyle')
      }
    }
    chain.run()
    applyParagraphFormat(ed, formats.block)
    return true
  } finally {
    painterApplying = false
    window.clearTimeout(painterTimer)
    painterTimer = undefined
    formatPainter.value = null
  }
}

/**
 * 复制格式后，用户下一次在正文中完成选区（或单击定位）时自动套用。
 * 180ms 防抖可避开拖选过程中的连续 selectionUpdate。
 */
function scheduleFormatPainterApply() {
  const ed = editor.value
  if (!ed || !formatPainter.value || painterApplying || props.readonly) return
  const { selection } = ed.state
  const source = formatPainter.value.sourceRange
  if (!selection.empty && source && selection.from === source.from && selection.to === source.to) {
    return
  }
  window.clearTimeout(painterTimer)
  painterTimer = window.setTimeout(() => {
    painterTimer = undefined
    const current = editor.value
    if (!current || !formatPainter.value || props.readonly) return
    if (!current.isFocused) return
    // 图注输入框等 NodeView 内部控件获得焦点时不自动套用。
    const active = document.activeElement as HTMLElement | null
    if (active && ['INPUT', 'TEXTAREA', 'SELECT'].includes(active.tagName)) return
    applyFormatPainter(current)
  }, 180)
}

/** 工具栏按钮：未就绪时复制格式；就绪后再次点击可立即应用或取消。 */
function toggleFormatPainter() {
  const ed = editor.value
  if (!ed) return
  if (!formatPainter.value) {
    armFormatPainter()
    return
  }
  const { selection } = ed.state
  const source = formatPainter.value.sourceRange
  const sameSource =
    !!source && !selection.empty && selection.from === source.from && selection.to === source.to
  if (sameSource) cancelFormatPainter(true)
  else applyFormatPainter(ed)
}

/** Ctrl/Cmd+Shift+C 复制格式，Ctrl/Cmd+Shift+V 应用；同时兼容 Ctrl/Cmd+Alt+C/V。 */
function onFormatPainterKeydown(event: KeyboardEvent) {
  if (props.readonly) return
  const ed = editor.value
  if (!ed) return
  if (event.key === 'Escape' && formatPainter.value) {
    event.preventDefault()
    cancelFormatPainter(true)
    return
  }
  if (!(event.ctrlKey || event.metaKey)) return
  // 只接受 Shift 或 Alt 修饰，避免占用普通复制 / 粘贴
  if (!(event.shiftKey || event.altKey) || (event.shiftKey && event.altKey)) return
  const key = event.key.toLowerCase()
  if (key !== 'c' && key !== 'v') return
  if (!ed.isFocused) return
  if (key === 'c') {
    event.preventDefault()
    armFormatPainter()
    return
  }
  // 没有复制格式时保留浏览器默认的「无格式粘贴」。
  if (!formatPainter.value) return
  event.preventDefault()
  applyFormatPainter(ed)
}

const editor = useEditor({
  // 初始内容直接交给编辑器创建，避免 setContent 产生可撤销事务
  content: props.content,
  extensions: [
    StarterKit.configure({ codeBlock: false, paragraph: false, heading: false }),
    KiwiParagraph,
    KiwiHeading,
    Underline,
    KiwiTextStyle,
    Placeholder.configure({ placeholder: placeholderText.value }),
    Link.configure({
      openOnClick: false,
      autolink: true,
      linkOnPaste: true,
      // 收件箱的来源链接使用 kiwi://todo/<镜像 id>；默认协议白名单会把它
      // 当成不安全链接丢弃，导致勾选后无法回写来源。
      protocols: ['kiwi'],
      HTMLAttributes: { rel: 'noopener noreferrer', target: '_blank' },
    }),
    KiwiImage.configure({
      inline: false,
      allowBase64: false,
      upload: async (file: File) => {
        const att = await uploadFile(file)
        return { url: att.url, filename: att.filename }
      },
    }),
    TextAlign.configure({ types: ['heading', 'paragraph'] }),
    Highlight.configure({ multicolor: true }),
    KiwiTable.configure({ resizable: true, lastColumnResizable: false }),
    TableRow,
    KiwiTableHeader,
    KiwiTableCell,
    KiwiTaskList,
    TaskItem.configure({ nested: true }),
    KiwiTaskProgress,
    createCodeBlock(lowlight),
    CodeOutput,
    EmbedBlock,
    PageBreak,
    PagedDoc.configure({
      enabled: () => isDocx.value,
      metrics: () => {
        const prefs = docxPrefs.value
        const paper = docxPaperSize(prefs.paper, prefs.orientation)
        const px = (cm: number) => (cm * 96) / 2.54
        const pageHeight = px(paper.height)
        const topMargin = px(prefs.margins.top)
        const bottomMargin = px(prefs.margins.bottom)
        return {
          pageHeight,
          contentHeight: Math.max(160, pageHeight - topMargin - bottomMargin),
          topMargin,
          bottomMargin,
          leftMargin: px(prefs.margins.left),
          rightMargin: px(prefs.margins.right),
          gap: Math.max(14, prefs.pageGap),
        }
      },
      onPages: (pages) => {
        docxPages.value = pages
      },
    }),
    SearchHighlight,
    CharacterCount,
    Callout,
    Video,
    KiwiDetails,
    DetailsSummary,
    DetailsContent,
    KiwiYoutube,
    KiwiEmoji,
    KiwiDate,
    KiwiFormula,
    KiwiMermaid,
    KiwiGallery.configure({ upload: uploadFile }),
    KiwiColumn,
    KiwiColumns,
    KiwiNoteEmbed,
    KiwiCalendar,
    KiwiDataTable,
    KiwiPluginBlock,
    createMentionExtension(
      mentionNotes,
      () => props.noteId ?? null,
      () => wikiPages.value,
    ),
    TrailingParagraph,
    ...(props.mode !== 'docx'
      ? [
          GlobalDragHandle.configure({
            dragHandleWidth: 24,
            scrollTreshold: 100,
            customNodes: [
              'callout',
              'video',
              'details',
              'youtube',
              'kiwiFormula',
              'kiwiMermaid',
              'kiwiGallery',
              'kiwiColumns',
              'kiwiNoteEmbed',
              'kiwiCalendar',
              'kiwiDataTable',
              'kiwiPluginBlock',
            ],
            dragHandleSelector: '#kiwi-drag-handle',
          }),
          createSlashCommand({
            onImage: pickImage,
            onAttachment: pickAttachment,
            onLink: openLinkDialog,
            onVideo: promptVideo,
            onYoutube: promptYoutube,
            onTable: openTableDialog,
            onSourceQuote: openSourceQuote,
            onKnowledgePoint: openKnowledgePoint,
            onDate: insertToday,
            onAI: () => emit('toggle-agent'),
            pluginBlocks: () => pluginsStore.blocks,
            onPluginBlock: (editorInstance, block) =>
              insertPluginBlockEntry(editorInstance, block),
            extensionEnabled: (key) => extensionsStore.isEnabled(key),
          }),
        ]
      : []),
    Markdown.configure({
      // 允许原始 HTML：语雀 / Notion 粘贴的表格、带 colspan 的复杂表格
      // 需要先按 HTML 解析成编辑器节点。解析结果仍受 ProseMirror schema
      // 约束，未知标签和脚本会被丢弃。
      html: true,
      tightLists: true,
      linkify: false,
      breaks: false,
      // 从「复制 Markdown」或其他笔记复制来的正文按 Markdown 解析成富文本；
      // 需要原样粘贴源码时按住 Shift 再粘贴（ProseMirror 会走纯文本分支）。
      transformPastedText: true,
    }),
    // 必须排在 Markdown 之后（priority 40），修正引用块/提示块中
    // 行首加粗、斜体的 Markdown 序列化错位。
    MarkdownSerializerFix,
  ],
  editable: !props.readonly,
  editorProps: {
    // 浏览器拼写检查会在中文正文下画红色波浪线；编辑器自带 Markdown / 术语，
    // 不需要原生拼写检查，统一关闭。
    attributes: { spellcheck: 'false' },
    handleDOMEvents: {
      /**
       * 收件箱来源链接是文本上的 link mark，ProseMirror 的 handleClickOn
       * 只会拿到所在段落（mark 信息不在 node 上），因此直接在 DOM 层拦截。
       */
      click: (_view, event) => {
        const anchor = (event.target as HTMLElement | null)?.closest?.(
          'a[href^="kiwi://todo/"]',
        ) as HTMLAnchorElement | null
        if (!anchor) return false
        event.preventDefault()
        event.stopPropagation()
        void openTodoSource(anchor.getAttribute('href') || '')
        return true
      },
      /** Word 模式：正文右击打开段落菜单（段落工具不放在工具栏）。 */
      contextmenu: (view, event) => {
        if (props.readonly) return false
        const target = event.target as HTMLElement | null
        const mentionEl = target?.closest?.('[data-type="mention"]') as HTMLElement | null
        if (mentionEl) {
          event.preventDefault()
          const found = mentionAtDom(view, mentionEl)
          if (found) {
            closeParagraphMenu()
            const x = Math.min(event.clientX, Math.max(8, window.innerWidth - 240))
            const y = Math.min(event.clientY, Math.max(8, window.innerHeight - 250))
            mentionMenu.value = {
              x,
              y,
              pos: found.pos,
              size: found.node.nodeSize,
              id: String(found.node.attrs.id ?? ''),
              label: String(found.node.attrs.label ?? ''),
              target: found.node.attrs.target === 'wiki' ? 'wiki' : 'note',
              display: normalizeMentionDisplay(found.node.attrs.display),
            }
          }
          return true
        }
        if (!isDocx.value) return false
        const coords = view.posAtCoords({ left: event.clientX, top: event.clientY })
        if (!coords) return false
        event.preventDefault()
        closeMentionMenu()
        const { from, to } = view.state.selection
        // 右击位置在选区外时，先把光标移到该段落；选区内的右击保留选区
        if (coords.pos < from || coords.pos > to) {
          const selection = TextSelection.near(view.state.doc.resolve(coords.pos))
          view.dispatch(view.state.tr.setSelection(selection))
        }
        const selection = view.state.selection
        const x = Math.min(event.clientX, Math.max(8, window.innerWidth - 260))
        const y = Math.min(event.clientY, Math.max(8, window.innerHeight - 140))
        paragraphMenu.value = { x, y, range: { from: selection.from, to: selection.to } }
        return true
      },
      mousedown: () => {
        if (paragraphMenu.value || mentionMenu.value) closeContextMenus()
        return false
      },
    },
    /** 待办收件箱里的来源链接：跳回来源笔记（旧链接通过镜像 API 兜底解析）。 */
    handleClickOn: (_view, _pos, node) => {
      const todoHref = node.marks
        .map((mark) => String(mark.attrs?.href || ''))
        .find((href) => href.startsWith('kiwi://todo/'))
      if (todoHref) {
        void openTodoSource(todoHref)
        return true
      }
      if (node.type.name !== 'mention') return false
      // 卡片 / 嵌入在节点视图内部自行处理点击，避免误跳转正文里的链接
      if (node.attrs.display === 'card' || node.attrs.display === 'embed') return false
      const id = node.attrs.id
      if (id) {
        void router.push(node.attrs.target === 'wiki' ? `/wiki/${id}` : `/notes/${id}`)
      }
      return true
    },
    handlePaste: (_view, event) => {
      const files = Array.from(event.clipboardData?.files || []).filter((f) =>
        f.type.startsWith('image/'),
      )
      if (!files.length) return false
      event.preventDefault()
      for (const file of files) void uploadAndInsert(file, true)
      return true
    },
    handleDrop: (_view, event) => {
      const files = Array.from(event.dataTransfer?.files || [])
      if (!files.length) return false
      event.preventDefault()
      const images = files.filter((file) => file.type.startsWith('image/'))
      const others = files.filter((file) => !file.type.startsWith('image/'))
      for (const file of images) void uploadAndInsert(file, true)
      // 非图片文件交给插入弹窗，由用户选择“内容 / 标题超链接”
      if (others.length) openEmbedDialog('file', others)
      return true
    },
  },
  onUpdate: ({ editor: ed }) => {
    // 套用持久化格式时不要把「没有内容变化」的更新回传，避免自动保存循环
    if (applyingSavedFormats) return
    chars.value = ed.storage.characterCount.characters()
    editorRevision.value += 1
    syncOutline()
    emit('update', (ed.storage.markdown as any)?.getMarkdown?.() ?? '')
    emit('paragraph-formats', collectParagraphFormats(ed))
    emit('text-formats', collectTextFormats(ed))
  },
  onSelectionUpdate: () => {
    editorRevision.value += 1
    scheduleFormatPainterApply()
  },
  onCreate: ({ editor: ed }) => {
    chars.value = ed.storage.characterCount.characters()
    syncOutline()
    applySavedParagraphFormats(ed)
    // NodeView 内的右击不会走 ProseMirror 的 handleDOMEvents
    contextMenuDom = ed.view.dom
    contextMenuDom.addEventListener('contextmenu', onEditorContextMenu)
  },
  onDestroy: () => {
    contextMenuDom?.removeEventListener('contextmenu', onEditorContextMenu)
    contextMenuDom = null
    cancelFormatPainter()
  },
})

/** 外部内容替换后清空撤销栈，避免 Ctrl+Z 把正文退回旧版本。 */
function resetHistory() {
  const ed = editor.value
  if (!ed) return
  const { state } = ed
  ed.view.updateState(
    EditorState.create({
      doc: state.doc,
      selection: state.selection,
      plugins: state.plugins,
    }),
  )
}

watch(
  () => props.content,
  (val) => {
    const ed = editor.value
    if (!ed) return
    if (val !== currentMarkdown()) {
      cancelFormatPainter()
      ed.commands.setContent(val, false)
      resetHistory()
      // 外部 setContent 不触发 onUpdate，手动同步字数与目录
      chars.value = ed.storage.characterCount.characters()
      syncOutline()
      applySavedParagraphFormats()
    }
  },
)

watch(
  () => props.readonly,
  (r) => {
    editor.value?.setEditable(!r)
    if (r) cancelFormatPainter()
  },
)

// 切换笔记时丢弃尚未应用的格式，避免把上一篇的格式刷到新笔记里。
watch(
  () => props.noteId,
  () => cancelFormatPainter(),
)

// 纸张 / 页边距 / 页间距变化后重新分页
watch(
  docxPrefs,
  () => {
    ;(editor.value?.storage as any)?.pagedDoc?.refresh?.()
  },
  { deep: true },
)

function currentMarkdown(): string {
  return (editor.value?.storage.markdown as any)?.getMarkdown?.() ?? ''
}

/** 当前选区纯文本（AI 面板读取）。 */
function getSelectionText(): string {
  const ed = editor.value
  if (!ed) return ''
  const { from, to } = ed.state.selection
  if (from === to) return ''
  return ed.state.doc.textBetween(from, to, '\n').trim()
}

/** 当前选区范围；无选区返回 null。生成时捕获，应用结果时更可靠。 */
function getSelectionRange(): { from: number; to: number } | null {
  const ed = editor.value
  if (!ed) return null
  const { from, to } = ed.state.selection
  return from === to ? null : { from, to }
}

/** 全文纯文本，作为 AI 上下文。 */
function getDocumentText(): string {
  return editor.value?.getText() ?? ''
}

/** 光标处插入 Markdown；传入 range 时替换该范围。 */
function insertMarkdown(md: string, range?: { from: number; to: number } | null) {
  const ed = editor.value
  const text = (md || '').trim()
  if (!ed || !text) return
  const storage = ed.storage.markdown as any
  const html = storage?.parser?.parse?.(text) ?? text
  if (range) {
    ed.chain().focus().insertContentAt(range, html).run()
  } else {
    ed.chain().focus().insertContent(html).run()
  }
}

defineExpose({
  getMarkdown: currentMarkdown,
  focus: () => editor.value?.commands.focus(),
  getSelectionText,
  getSelectionRange,
  getDocumentText,
  insertMarkdown,
  /** 搜索结果定位：在正文中标记关键词并滚动到第一处命中。 */
  highlightSearchTerm: (term: string, active = -1, splitWords = true) => {
    const ed = editor.value
    return ed ? highlightSearchTerm(ed, term, active, splitWords) : false
  },
  clearSearchHighlight: () => {
    const ed = editor.value
    if (ed) clearSearchHighlight(ed)
  },
  /** 在纸张上直接进入页眉 / 页脚编辑（页面设置里的快捷按钮使用） */
  startHeaderEdit,
  startFooterEdit,
})
</script>

<template>
  <div
    class="kiwi-editor flex min-h-0 flex-col"
    :class="{
      [orderedListClass]: orderedListClass,
      'kiwi-editor-docx': isDocx,
      'is-readonly': readonly,
      'code-theme-dark': codePrefs.theme === 'dark',
      'code-theme-light': codePrefs.theme === 'light',
      'code-linenos': codePrefs.lineNumbers,
      'code-wrap': codePrefs.wrap,
    }"
  >
    <!-- 块拖动手柄挂到 <html> 下：body 的 4K zoom 会把 fixed 坐标再次放大，导致手柄偏移 -->
    <Teleport to="html">
      <div
        v-if="simple && !readonly"
        id="kiwi-drag-handle"
        class="drag-handle hide"
        aria-hidden="true"
        @click="onDragHandleClick"
      />
    </Teleport>
    <input
      ref="imageInput"
      type="file"
      accept="image/png,image/jpeg,image/gif,image/webp,image/bmp,image/avif"
      class="hidden"
      multiple
      @change="onPick"
    />

    <Teleport
      v-if="editor && !readonly"
      :to="toolbarHost || 'body'"
      :disabled="!toolbarHost"
    >
    <EditorToolbar
      :editor="editor"
      :mode="mode"
      :docx-prefs="docxPrefs"
      :zoom="docxZoom"
      :agent-open="agentOpen"
      :revision="editorRevision"
      :code-prefs="codePrefs"
      :painter-active="!!formatPainter"
      :ordered-list-style="orderedListStyle"
      @ordered-list-style="emit('ordered-list-style', $event)"
      @painter="toggleFormatPainter"
      @code-prefs="onCodePrefs"
      @run-code="onToolbarRunCode"
      @image="pickImage"
      @attach="pickAttachment"
      @link="editor && openLinkDialog(editor)"
      @docx-prefs="onDocxPrefs"
      @page-break="insertPageBreak"
      @word-preview="emit('word-preview')"
      @zoom="docxZoom = $event"
      @agent="emit('toggle-agent')"
      @table="openTableFromToolbar"
      @details="editor && toggleDetailsBlock(editor)"
      @youtube="editor && promptYoutube(editor)"
      @mention="insertSuggestionChar('@')"
      @emoji="insertSuggestionChar(':')"
      @component="insertComponent"
      @plugin-block="editor && insertPluginBlockEntry(editor, $event)"
    />
    </Teleport>

    <BubbleMenu
      v-if="editor"
      :editor="editor"
      :should-show="shouldShowFormatBubble"
      :tippy-options="bubbleTippyOptions('top')"
      :data-rev="editorRevision"
      :style="{ zoom: 'var(--ui-scale)' }"
      class="flex items-center gap-0.5 rounded-xl border border-slate-200/80 bg-white/95 backdrop-blur-xl shadow-lifted px-1 py-1"
    >
      <button type="button" class="ed-bubble" :class="{ 'is-active': editor.isActive('bold') }" @click="editor.chain().focus().toggleBold().run()">
        <KiwiIcon name="bold" :size="13" />
      </button>
      <button type="button" class="ed-bubble" :class="{ 'is-active': editor.isActive('italic') }" @click="editor.chain().focus().toggleItalic().run()">
        <KiwiIcon name="italic" :size="13" />
      </button>
      <button type="button" class="ed-bubble" :class="{ 'is-active': editor.isActive('underline') }" @click="editor.chain().focus().toggleUnderline().run()">
        <KiwiIcon name="underline" :size="13" />
      </button>
      <button type="button" class="ed-bubble" :class="{ 'is-active': editor.isActive('strike') }" @click="editor.chain().focus().toggleStrike().run()">
        <KiwiIcon name="strike" :size="13" />
      </button>
      <button type="button" class="ed-bubble" :class="{ 'is-active': editor.isActive('code') }" @click="editor.chain().focus().toggleCode().run()">
        <KiwiIcon name="code" :size="13" />
      </button>
      <button type="button" class="ed-bubble" :class="{ 'is-active': editor.isActive('highlight') }" @click="editor.chain().focus().toggleHighlight().run()">
        <KiwiIcon name="highlight" :size="13" />
      </button>
      <EditorColorPicker
        variant="bubble"
        :value="normalizeColor(editor.getAttributes('textStyle').color) || '#1F2937'"
        :active="!!normalizeColor(editor.getAttributes('textStyle').color)"
        @select="applyBubbleTextColor"
        @clear="applyBubbleTextColor(null)"
      />
      <button type="button" class="ed-bubble" :class="{ 'is-active': editor.isActive('link') }" @click="openLinkDialog(editor)">
        <KiwiIcon name="link2" :size="13" />
      </button>
      <button
        type="button"
        class="ed-bubble"
        :class="{ 'is-active': !!formatPainter }"
        :title="
          formatPainter
            ? '格式刷已就绪：选择目标内容自动应用，Esc 取消'
            : '格式刷：复制当前格式（Ctrl+Shift+C / Ctrl+Alt+C）'
        "
        @mousedown.prevent
        @click="toggleFormatPainter"
      >
        <KiwiIcon name="copy" :size="13" />
      </button>
    </BubbleMenu>

    <!-- 表格上下文菜单：光标在表格内时出现，行列 / 表头 / 合并 / 底色都在这里，不占常驻工具栏 -->
    <BubbleMenu
      v-if="editor"
      :editor="editor"
      :should-show="shouldShowTableBubble"
      :tippy-options="bubbleTippyOptions('top-start')"
      :data-rev="editorRevision"
      :style="{ zoom: 'var(--ui-scale)' }"
      class="flex flex-col gap-1 rounded-xl border border-slate-200/80 bg-white/95 px-1.5 py-1.5 shadow-lifted backdrop-blur-xl"
    >
      <div class="flex items-center gap-0.5">
        <button type="button" class="ed-bubble" title="在上方插入行" @mousedown.prevent @click="editor.chain().focus().addRowBefore().run()">
          <KiwiIcon name="plus" :size="13" />
        </button>
        <button type="button" class="ed-bubble" title="在下方插入行" @mousedown.prevent @click="editor.chain().focus().addRowAfter().run()">
          <KiwiIcon name="plus" :size="13" class="rotate-90" />
        </button>
        <button type="button" class="ed-bubble" title="删除当前行" @mousedown.prevent @click="editor.chain().focus().deleteRow().run()">
          <KiwiIcon name="minus" :size="13" />
        </button>
        <span class="mx-0.5 h-4 w-px bg-slate-200" />
        <button type="button" class="ed-bubble" title="在左侧插入列" @mousedown.prevent @click="editor.chain().focus().addColumnBefore().run()">
          <KiwiIcon name="columns" :size="13" class="rotate-90" />
        </button>
        <button type="button" class="ed-bubble" title="在右侧插入列" @mousedown.prevent @click="editor.chain().focus().addColumnAfter().run()">
          <KiwiIcon name="columns" :size="13" />
        </button>
        <button type="button" class="ed-bubble" title="删除当前列" @mousedown.prevent @click="editor.chain().focus().deleteColumn().run()">
          <KiwiIcon name="minus" :size="13" class="rotate-90" />
        </button>
        <span class="mx-0.5 h-4 w-px bg-slate-200" />
        <button type="button" class="ed-bubble !w-auto px-1.5 text-[11px]" title="合并单元格" @mousedown.prevent @click="editor.chain().focus().mergeCells().run()">
          合并
        </button>
        <button type="button" class="ed-bubble !w-auto px-1.5 text-[11px]" title="拆分单元格" @mousedown.prevent @click="editor.chain().focus().splitCell().run()">
          拆分
        </button>
        <button type="button" class="ed-bubble hover:!text-rose-600" title="删除表格" @mousedown.prevent @click="editor.chain().focus().deleteTable().run()">
          <KiwiIcon name="trash" :size="13" />
        </button>
      </div>
      <div class="flex items-center gap-0.5">
        <button
          type="button"
          class="ed-bubble !w-auto px-1.5 text-[11px]"
          :class="{ 'is-active': editor.isActive('tableHeader') }"
          title="把首行设为表头 / 取消表头"
          @mousedown.prevent
          @click="editor.chain().focus().toggleHeaderRow().run()"
        >
          首行表头
        </button>
        <button
          type="button"
          class="ed-bubble !w-auto px-1.5 text-[11px]"
          :class="{ 'is-active': editor.isActive('tableHeader') }"
          title="把首列设为表头 / 取消表头"
          @mousedown.prevent
          @click="editor.chain().focus().toggleHeaderColumn().run()"
        >
          首列表头
        </button>
        <span class="mx-0.5 h-4 w-px bg-slate-200" />
        <button
          v-for="color in TABLE_BG_COLORS"
          :key="color.value"
          type="button"
          class="h-5 w-5 rounded-md border border-slate-200 transition-transform hover:scale-110"
          :style="{ background: color.value }"
          :title="color.label"
          @mousedown.prevent
          @click="editor.chain().focus().setCellAttribute('background', color.value).run()"
        />
        <button
          type="button"
          class="ed-bubble"
          title="清除单元格底色"
          @mousedown.prevent
          @click="editor.chain().focus().setCellAttribute('background', null).run()"
        >
          <KiwiIcon name="eraser" :size="13" />
        </button>
        <span class="mx-0.5 h-4 w-px bg-slate-200" />
        <button type="button" class="ed-bubble" :class="{ 'is-active': editor.isActive({ textAlign: 'left' }) }" title="左对齐" @mousedown.prevent @click="editor.chain().focus().setTextAlign('left').run()">
          <span class="text-[11px] font-semibold">L</span>
        </button>
        <button type="button" class="ed-bubble" :class="{ 'is-active': editor.isActive({ textAlign: 'center' }) }" title="居中" @mousedown.prevent @click="editor.chain().focus().setTextAlign('center').run()">
          <span class="text-[11px] font-semibold">C</span>
        </button>
        <button type="button" class="ed-bubble" :class="{ 'is-active': editor.isActive({ textAlign: 'right' }) }" title="右对齐" @mousedown.prevent @click="editor.chain().focus().setTextAlign('right').run()">
          <span class="text-[11px] font-semibold">R</span>
        </button>
      </div>
    </BubbleMenu>

    <!-- 统一编辑区域：灰色画布 + 白色纸张，高度铺满剩余视口 -->
    <div class="editor-canvas" :style="canvasStyle">
      <div class="editor-canvas-inner" :class="{ 'has-outline': showOutline }">
        <div class="editor-page-stack" :class="{ 'is-docx': isDocx }">
          <!-- Word 模式：笔记标题等元信息放在纸张外，纸张只排版正文 -->
          <div v-if="isDocx" class="docx-doc-header" :style="{ width: `${paper.width}cm` }">
            <slot name="header" />
          </div>

        <div class="editor-sheet" :style="sheetStyle">
          <div
            v-if="headerVisible"
            class="docx-page-head"
            :class="{ 'is-editable': !readonly, 'is-editing': headerEditing }"
            :style="pageHeadStyle"
          >
            <span
              v-if="headerEditing"
              ref="headerEditor"
              class="docx-page-edit"
              contenteditable="true"
              spellcheck="false"
              data-placeholder="输入页眉，留空显示文档标题"
              @keydown.enter.prevent="commitHeader"
              @keydown.esc.prevent="cancelHeaderEdit"
              @blur="commitHeader"
              @paste="pastePlain"
            />
            <button
              v-else
              type="button"
              class="docx-page-edit-text truncate"
              :class="{ 'is-placeholder': !pageHeaderText, 'is-static': readonly }"
              :title="readonly ? '' : '点击编辑页眉'"
              @click="startHeaderEdit"
            >
              {{ pageHeaderText || '点击添加页眉' }}
            </button>
            <span class="docx-brand">
              <KiwiIcon name="bookOpen" :size="10" />
              KIWI DOCX
            </span>
          </div>

          <slot v-if="!isDocx" name="header" />

          <EditorContent :editor="editor" class="max-w-none flex-1 focus:outline-none" />

          <div
            v-if="footerVisible"
            class="docx-page-footer"
            :class="{ 'is-editable': !readonly, 'is-editing': footerEditing }"
            :style="pageFootStyle"
          >
            <span
              v-if="footerEditing"
              ref="footerEditor"
              class="docx-page-edit"
              contenteditable="true"
              spellcheck="false"
              data-placeholder="输入页脚，支持 {page} / {pages}"
              @keydown.enter.prevent="commitFooter"
              @keydown.esc.prevent="cancelFooterEdit"
              @blur="commitFooter"
              @paste="pastePlain"
            />
            <button
              v-else
              type="button"
              class="docx-page-edit-text truncate"
              :class="{ 'is-placeholder': !pageFooterText, 'is-static': readonly }"
              :title="readonly ? '' : '点击编辑页脚，支持 {page} / {pages}'"
              @click="startFooterEdit"
            >
              {{ pageFooterText || '点击添加页脚' }}
            </button>
          </div>

          <div v-if="editor && !readonly && !isDocx" class="editor-meta-bar">
            <span class="flex items-center gap-1">
              <KiwiIcon :name="footerIcon" :size="11" />
              {{ footerHint }}
            </span>
            <span class="tabular-nums">{{ chars }} 字</span>
          </div>
        </div>
        </div>

        <!-- 文档目录：浮动在编辑区域右侧，不挤压正文 -->
        <div v-if="showOutline" ref="outlineSlot" class="editor-outline-slot">
        <aside class="editor-outline" :style="{ maxHeight: outlineMaxHeight || undefined }">
          <div class="flex items-center justify-between gap-1 px-0.5 pb-2">
            <span class="flex shrink-0 items-center gap-1.5 text-[10.5px] font-medium text-slate-500">
              <KiwiIcon name="listTree" :size="12" />
              文档目录
            </span>
            <span class="flex min-w-0 items-center gap-1">
              <button
                v-if="outlineChildIndexes.length"
                type="button"
                class="grid h-4 w-4 place-items-center rounded text-slate-400 transition-colors hover:bg-kiwi-50 hover:text-kiwi-600"
                :title="hasExpandedGroups ? '折叠全部子标题' : '展开全部子标题'"
                @click="toggleAllHeadings"
              >
                <KiwiIcon :name="hasExpandedGroups ? 'chevronsUp' : 'chevronsDown'" :size="11" />
              </button>
              <select
                v-model.number="outlineDepth"
                class="max-w-[74px] cursor-pointer rounded border border-slate-200/80 bg-white/80 px-1 py-0.5 text-[9.5px] text-slate-500 outline-none hover:border-kiwi-200 focus:border-kiwi-300"
                title="展示到第几级标题"
              >
                <option :value="6">全部层级</option>
                <option v-for="n in 5" :key="n" :value="n">至 {{ n }} 级</option>
              </select>
              <span class="tabular-nums text-[10px] text-slate-300">
                {{ outlineRows.length }}<template v-if="outlineRows.length !== headings.length"> / {{ headings.length }}</template>
              </span>
            </span>
          </div>
          <div v-if="outlineRows.length" class="space-y-0.5">
            <div
              v-for="row in outlineRows"
              :key="`${row.item.pos}-${row.index}`"
              class="group/outline relative"
            >
              <button
                v-if="row.hasChildren"
                type="button"
                class="absolute top-1/2 z-[1] grid h-4 w-4 -translate-y-1/2 place-items-center rounded text-slate-400 transition-colors hover:bg-kiwi-100/60 hover:text-kiwi-600"
                :style="{ left: `${(row.item.level - 1) * 10 + 1}px` }"
                :title="collapsedHeadings.has(row.index) ? '展开子标题' : '收起子标题'"
                :aria-expanded="!collapsedHeadings.has(row.index)"
                @click.stop="toggleHeading(row.index)"
              >
                <KiwiIcon
                  name="chevronRight"
                  :size="10"
                  class="transition-transform"
                  :class="collapsedHeadings.has(row.index) ? '' : 'rotate-90'"
                />
              </button>
              <button
                type="button"
                class="relative block w-full truncate rounded-md py-1 pr-2 text-left text-[11px] leading-snug transition-colors"
                :class="
                  row.index === activeOutlineIndex
                    ? 'bg-kiwi-50 font-medium text-kiwi-700'
                    : 'text-slate-500 hover:bg-kiwi-50 hover:text-kiwi-700'
                "
                :style="{ paddingLeft: `${(row.item.level - 1) * 10 + 17}px` }"
                :title="row.item.text"
                :aria-current="row.index === activeOutlineIndex ? 'location' : undefined"
                @click="scrollToHeading(row.item)"
              >
                <span
                  v-if="row.index === activeOutlineIndex"
                  class="absolute left-0 top-1/2 h-3 w-[2px] -translate-y-1/2 rounded-full bg-kiwi-500"
                />
                {{ row.item.text }}
              </button>
            </div>
          </div>
          <p v-else class="rounded-lg border border-dashed border-slate-200 px-3 py-6 text-center text-[10.5px] text-slate-400">
            <template v-if="headings.length">
              当前展示级别内没有标题
              <br />
              试试「全部层级」
            </template>
            <template v-else>
              还没有标题
              <br />
              用「标题 1/2/3」组织文档
            </template>
          </p>
        </aside>
        </div>
      </div>
    </div>

    <TableInsertDialog
      :open="tableDialogOpen"
      @close="closeTableDialog"
      @insert="insertTable"
    />

    <InsertEmbedDialog
      :open="embedDialogOpen"
      :tab="embedDialogTab"
      :initial-url="embedDialogUrl"
      :initial-files="embedDialogFiles"
      :selection-text="embedSelectionText"
      @close="closeEmbedDialog"
      @insert-link="insertLinkEmbed"
      @insert-files="insertAttachmentEmbeds"
    />

    <SourceQuoteDialog
      :open="sourceQuoteOpen"
      :initial-quote="sourceQuoteSeed"
      @close="sourceQuoteOpen = false"
      @insert="insertSourceQuote"
    />

    <KnowledgePointDialog
      :open="knowledgePointOpen"
      :initial-text="knowledgePointSeed"
      @close="knowledgePointOpen = false"
      @insert="insertKnowledgePoint"
    />

    <!-- DOCX 正文右击菜单：挂到 <html> 下，避免 4K zoom 放大坐标 -->
    <Teleport to="html">
      <div v-if="paragraphMenu" class="fixed inset-0 z-[90]" @mousedown="closeParagraphMenu" @contextmenu.prevent="closeParagraphMenu">
        <div
          class="absolute"
          :style="{ left: `${paragraphMenu.x}px`, top: `${paragraphMenu.y}px` }"
          @mousedown.stop
        >
          <div
            class="w-[196px] overflow-hidden rounded-xl border border-slate-200/90 bg-white/97 p-1 shadow-xl backdrop-blur-xl"
            :style="{ zoom: 'var(--ui-scale)' }"
            role="menu"
            aria-label="段落菜单"
          >
            <p class="px-2.5 pb-1 pt-1.5 text-[10px] font-medium uppercase tracking-[0.12em] text-slate-400">
              段落
            </p>
            <button
              type="button"
              class="flex w-full items-center gap-2 rounded-lg px-2.5 py-1.5 text-left text-[11.5px] text-slate-600 hover:bg-kiwi-50 hover:text-kiwi-700"
              role="menuitem"
              @click="openParagraphDialog"
            >
              <KiwiIcon name="alignLeft" :size="13" />
              段落设置…
            </button>
            <button
              type="button"
              class="flex w-full items-center gap-2 rounded-lg px-2.5 py-1.5 text-left text-[11.5px] text-slate-600 hover:bg-rose-50 hover:text-rose-600"
              role="menuitem"
              @click="resetParagraphFormat"
            >
              <KiwiIcon name="trash" :size="13" />
              清除段落格式
            </button>
          </div>
        </div>
      </div>
    </Teleport>

    <!-- @ 提及右击菜单：展示方式与打开 / 移除 -->
    <Teleport to="html">
      <div v-if="mentionMenu" class="fixed inset-0 z-[90]" @mousedown="closeMentionMenu" @contextmenu.prevent="closeMentionMenu">
        <div
          class="absolute"
          :style="{ left: `${mentionMenu.x}px`, top: `${mentionMenu.y}px` }"
          @mousedown.stop
        >
          <div
            class="w-[212px] overflow-hidden rounded-xl border border-slate-200/90 bg-white/97 p-1 shadow-xl backdrop-blur-xl"
            :style="{ zoom: 'var(--ui-scale)' }"
            role="menu"
            aria-label="提及菜单"
          >
            <p class="px-2.5 pb-0.5 pt-1.5 text-[10px] font-medium uppercase tracking-[0.12em] text-slate-400">
              {{ mentionMenu.target === 'wiki' ? 'Wiki 提及' : '笔记提及' }}
            </p>
            <p class="truncate px-2.5 pb-1 text-[11.5px] font-medium text-slate-700">
              {{ mentionMenu.label || mentionMenu.id }}
            </p>
            <button
              type="button"
              class="flex w-full items-center gap-2 rounded-lg px-2.5 py-1.5 text-left text-[11.5px] text-slate-600 hover:bg-kiwi-50 hover:text-kiwi-700"
              role="menuitem"
              @click="openMentionNote"
            >
              <KiwiIcon name="external" :size="13" />
              {{ mentionMenu.target === 'wiki' ? '打开页面' : '打开笔记' }}
            </button>
            <div class="my-1 h-px bg-slate-100" />
            <p class="px-2.5 pb-1 pt-0.5 text-[10px] font-medium text-slate-400">展示方式</p>
            <button
              v-for="mode in MENTION_DISPLAY_OPTIONS"
              :key="mode.id"
              type="button"
              class="flex w-full items-center gap-2 rounded-lg px-2.5 py-1.5 text-left text-[11.5px] transition-colors"
              :class="
                mentionMenu.display === mode.id
                  ? 'bg-kiwi-50 text-kiwi-700'
                  : 'text-slate-600 hover:bg-slate-50'
              "
              role="menuitemradio"
              :aria-checked="mentionMenu.display === mode.id"
              @click="setMentionDisplay(mode.id)"
            >
              <span class="grid w-3.5 shrink-0 place-items-center">
                <KiwiIcon v-if="mentionMenu.display === mode.id" name="check" :size="12" />
              </span>
              <span class="flex-1">{{ mode.label }}</span>
              <span class="text-[10px] text-slate-400">{{ mode.hint }}</span>
            </button>
            <div class="my-1 h-px bg-slate-100" />
            <button
              type="button"
              class="flex w-full items-center gap-2 rounded-lg px-2.5 py-1.5 text-left text-[11.5px] text-slate-500 hover:bg-rose-50 hover:text-rose-600"
              role="menuitem"
              @click="removeMention"
            >
              <KiwiIcon name="trash" :size="13" />
              移除提及
            </button>
          </div>
        </div>
      </div>
    </Teleport>

    <DocxParagraphDialog
      v-if="isDocx"
      :open="paragraphDialogOpen"
      :prefs="docxPrefs"
      :editor="editor ?? null"
      :range="paragraphRange"
      @close="closeParagraphDialog"
      @apply="applyParagraphFromDialog"
    />

    <!-- 代码块运行 / 预览：挂到 <html> 下，避免 4K zoom 影响 fixed 定位 -->
    <Teleport to="html">
      <div
        v-if="runOpen"
        class="fixed inset-0 z-[999] flex items-center justify-center bg-slate-900/45 p-6"
        @click.self="closeCodeRun"
      >
        <div
          class="flex max-h-[88vh] w-full max-w-5xl flex-col overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-2xl"
        >
          <header class="flex shrink-0 items-center gap-2.5 border-b border-slate-200/80 px-4 py-3">
            <span class="grid h-7 w-7 place-items-center rounded-lg bg-emerald-50 text-emerald-600">
              <KiwiIcon :name="isPreviewRun ? 'image' : 'terminal'" :size="14" />
            </span>
            <div class="min-w-0">
              <p class="text-[12.5px] font-semibold text-slate-700">
                {{ isPreviewRun ? '代码预览' : '运行 Python' }}
              </p>
              <p class="text-[10px] text-slate-400">
                {{
                  isPreviewRun
                    ? '在隔离的 iframe 中渲染，不会影响笔记正文'
                    : '在本机受限子进程中执行，最多 10 秒'
                }}
              </p>
            </div>
            <div class="flex-1" />
            <button
              type="button"
              class="kiwi-btn-ghost !py-1 !px-2 !text-[11px]"
              :disabled="runLoading"
              @click="rerunCode"
            >
              <KiwiIcon name="refresh" :size="12" :spin="runLoading" />
              {{ isPreviewRun ? '重新渲染' : '重新运行' }}
            </button>
            <button
              type="button"
              class="grid h-7 w-7 place-items-center rounded-lg text-slate-400 transition hover:bg-slate-100 hover:text-slate-600"
              title="关闭"
              @click="closeCodeRun"
            >
              <KiwiIcon name="close" :size="13" />
            </button>
          </header>

          <div class="min-h-0 flex-1 overflow-auto bg-slate-50 p-4">
            <template v-if="isPreviewRun">
              <iframe
                :key="previewNonce"
                :srcdoc="previewDocument"
                sandbox="allow-scripts allow-forms allow-modals allow-popups"
                class="h-[62vh] w-full rounded-xl border border-slate-200 bg-white"
                title="代码预览"
              />
            </template>

            <template v-else>
              <div
                v-if="runLoading"
                class="flex h-40 items-center justify-center gap-2 text-[12px] text-slate-400"
              >
                <KiwiIcon name="loader" :size="16" spin />
                正在运行…
              </div>
              <div
                v-else-if="runError"
                class="rounded-xl border border-rose-200 bg-rose-50 p-4 text-[12px] text-rose-600"
              >
                {{ runError }}
              </div>
              <div v-else-if="runResult" class="space-y-3">
                <div class="flex flex-wrap items-center gap-2 text-[11px]">
                  <span
                    class="rounded-md px-2 py-0.5"
                    :class="
                      runResult.ok
                        ? 'bg-emerald-50 text-emerald-600'
                        : 'bg-rose-50 text-rose-600'
                    "
                  >
                    {{
                      runResult.ok
                        ? '运行成功'
                        : runResult.timed_out
                          ? '运行超时'
                          : '运行失败'
                    }}
                  </span>
                  <span class="text-slate-400">退出码 {{ runResult.exit_code ?? '—' }}</span>
                  <span class="text-slate-400">{{ runResult.duration_ms }} ms</span>
                  <span v-if="runResult.truncated" class="text-amber-500">输出已截断</span>
                </div>

                <div
                  v-if="runResult.stdout"
                  class="overflow-hidden rounded-xl border border-slate-200 bg-white"
                >
                  <div class="border-b border-slate-100 px-3 py-1.5 text-[10.5px] font-medium text-slate-400">
                    标准输出
                  </div>
                  <pre class="max-h-[46vh] overflow-auto whitespace-pre-wrap break-words p-3 font-mono text-[12px] leading-relaxed text-slate-700">{{ runResult.stdout }}</pre>
                </div>

                <div
                  v-if="runResult.stderr"
                  class="overflow-hidden rounded-xl border border-rose-200 bg-white"
                >
                  <div class="border-b border-rose-100 px-3 py-1.5 text-[10.5px] font-medium text-rose-400">
                    错误输出
                  </div>
                  <pre class="max-h-[32vh] overflow-auto whitespace-pre-wrap break-words p-3 font-mono text-[12px] leading-relaxed text-rose-600">{{ runResult.stderr }}</pre>
                </div>

                <p
                  v-if="!runResult.stdout && !runResult.stderr"
                  class="rounded-xl border border-dashed border-slate-200 px-4 py-10 text-center text-[12px] text-slate-400"
                >
                  代码执行完成，没有输出
                </p>
              </div>
            </template>
          </div>

          <footer class="shrink-0 border-t border-slate-100 px-4 py-2 text-[10px] text-slate-400">
            {{
              isPreviewRun
                ? 'HTML / JavaScript 在沙箱 iframe 中直接渲染；脚本仅能访问该 iframe。'
                : 'Python 使用独立临时目录运行；无法访问网络的限制由运行环境决定。'
            }}
          </footer>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<style scoped>
.ed-bubble {
  @apply w-6 h-6 grid place-items-center rounded-md text-slate-500 transition-colors hover:bg-kiwi-50 hover:text-kiwi-700;
}
.ed-bubble.is-active {
  @apply bg-kiwi-100/80 text-kiwi-700;
}

/* ---------- 四种模式共用：灰色画布 + 白色纸张 ---------- */
.editor-canvas {
  @apply relative flex min-h-0 flex-1 flex-col rounded-2xl border border-slate-200/60 p-5 transition-colors;
  /* 冷灰底 + 左上紫罗兰环境光 + 右下青蓝环境光 + 细点阵，让纸张浮起来 */
  background-color: #eef1f7;
  background-image:
    radial-gradient(900px 420px at 8% -10%, rgb(var(--kiwi-500) / 0.16), transparent 62%),
    radial-gradient(820px 380px at 100% 108%, rgba(94, 183, 214, 0.09), transparent 66%),
    radial-gradient(circle at 1px 1px, rgba(100, 116, 139, 0.17) 1px, transparent 0);
  background-size: auto, auto, 18px 18px;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.7);
}
.editor-canvas-inner {
  @apply flex w-full flex-1 items-stretch justify-center gap-3;
}
.editor-page-stack {
  @apply flex min-w-0 flex-1 flex-col items-center;
}
/* 普通模式：纸张在空内容时也向下铺满画布；Word 模式保持真实纸张高度 */
.editor-page-stack:not(.is-docx) > .editor-sheet {
  flex: 1 1 auto;
}
.docx-doc-header {
  @apply mb-3 w-full shrink-0 self-center;
  max-width: 100%;
}
.editor-sheet {
  @apply relative flex min-w-0 flex-col rounded-[10px] border border-white/70 px-8 py-8;
  box-shadow:
    0 0 0 1px rgba(226, 232, 240, 0.55),
    0 1px 2px rgba(15, 23, 42, 0.04),
    0 12px 28px -20px rgba(15, 23, 42, 0.26),
    0 46px 90px -56px rgba(15, 23, 42, 0.4);
}
/* 文档 / 笔记模式：更从容的页边距与顶部品牌细线 */
.kiwi-editor:not(.kiwi-editor-docx) .editor-sheet {
  padding: 2.4rem 2.6rem 2.2rem;
}
/* 窄屏收窄纸张内边距，避免正文每行只剩几个字。 */
@media (max-width: 767px) {
  .kiwi-editor:not(.kiwi-editor-docx) .editor-sheet {
    padding: 1.25rem 1rem 1.5rem;
  }
}
.kiwi-editor:not(.kiwi-editor-docx) .editor-sheet::before {
  content: '';
  position: absolute;
  top: 0;
  left: 16%;
  right: 16%;
  height: 2px;
  border-radius: 0 0 4px 4px;
  background: linear-gradient(90deg, rgb(var(--kiwi-400) / 0), rgb(var(--kiwi-500) / 0.7), rgb(var(--kiwi-400) / 0));
  pointer-events: none;
}
.editor-sheet :deep(.ProseMirror) {
  @apply flex-1;
  /* 阻止首尾段落的外边距与纸张发生折叠，保证分页测量与纸张高度一致 */
  display: flow-root;
  font-family: var(--doc-font, inherit);
  font-size: var(--doc-size, 15px);
  line-height: var(--doc-line, 1.8);
}
.kiwi-editor.is-readonly .editor-sheet :deep(.ProseMirror) {
  min-height: 240px;
}
/* 阅读模式只保留代码块的复制（常显），隐藏运行 / 预览控制 / 运行结果复制与删除等操作 */
.kiwi-editor.is-readonly :deep(.code-tools) {
  display: inline-flex;
  opacity: 0.55;
}
.kiwi-editor.is-readonly :deep(.code-block-node:hover .code-tools) {
  opacity: 1;
}
.kiwi-editor.is-readonly :deep(.code-run-btn),
.kiwi-editor.is-readonly :deep(.code-preview-actions),
.kiwi-editor.is-readonly :deep(.code-output-actions) {
  display: none !important;
}
.kiwi-editor.is-readonly :deep(.ProseMirror input[type='checkbox']) {
  pointer-events: none;
}

/* 目录 */
/* 零宽 sticky 槽位 + 绝对定位面板：目录浮在画布上，不占正文宽度 */
.editor-outline-slot {
  flex: 0 0 0;
  align-self: flex-start;
  width: 0;
  height: 0;
  position: sticky;
  /* 吸顶时给上方工具栏留出高度，避免被工具栏遮挡 */
  top: 3.25rem;
  z-index: 20;
  pointer-events: none;
}
.editor-outline {
  @apply absolute right-0 top-0 w-52 rounded-xl border border-slate-200/70 bg-white/95 p-2.5 backdrop-blur-xl;
  box-shadow: 0 8px 24px -18px rgba(15, 23, 42, 0.35);
  /* 高度不超过可见页面，超出时目录内部滚动 */
  max-height: calc(100dvh - 14rem);
  overflow-y: auto;
  overscroll-behavior: contain;
  pointer-events: auto;
}
.editor-canvas-inner.has-outline .editor-page-stack {
  padding-right: 14rem;
}

/* ---------- DOCX 纸张细节 ---------- */
.docx-page-head {
  @apply absolute flex items-center justify-between gap-4 border-b border-dashed border-slate-300/70 pb-3 text-[11px] text-slate-400;
}
.docx-brand {
  @apply flex shrink-0 items-center gap-1 text-[9px] font-medium uppercase tracking-[0.18em] text-slate-300;
}
.docx-page-footer {
  @apply absolute flex items-center justify-center border-t border-dashed border-slate-200/80 pt-3 text-[10px] text-slate-300;
}
/* 页眉 / 页脚点击即编辑 */
.docx-page-head.is-editable:hover,
.docx-page-footer.is-editable:hover {
  border-color: rgba(139, 140, 232, 0.55);
}
.docx-page-head.is-editing,
.docx-page-footer.is-editing {
  border-color: rgba(139, 140, 232, 0.7);
}
.docx-page-edit-text {
  @apply min-w-0 flex-1 truncate text-left text-[11px] text-slate-400;
}
.docx-page-footer .docx-page-edit-text {
  @apply text-center;
}
.docx-page-edit-text.is-placeholder {
  @apply text-slate-300;
}
.docx-page-edit-text.is-static {
  @apply cursor-default;
}
.docx-page-edit-text:not(.is-static) {
  @apply cursor-text;
}
.docx-page-edit-text:not(.is-static):hover {
  @apply text-kiwi-600;
}
.docx-page-edit {
  @apply block min-w-0 flex-1 truncate text-[11px] text-slate-500 outline-none;
  border-bottom: 1px dashed rgb(var(--kiwi-500) / 0.55);
  caret-color: rgb(var(--kiwi-500));
}
.docx-page-footer .docx-page-edit {
  @apply text-center;
}
.docx-page-edit:empty::before {
  content: attr(data-placeholder);
  color: #cbd5e1;
}
.kiwi-editor-docx .editor-sheet :deep(.ProseMirror h1) {
  font-size: 1.6em;
  letter-spacing: -0.01em;
}
.kiwi-editor-docx .editor-sheet :deep(.ProseMirror h2) {
  font-size: 1.28em;
}
.kiwi-editor-docx .editor-sheet :deep(.ProseMirror) {
  letter-spacing: var(--doc-letter, 0);
}
.kiwi-editor-docx .editor-sheet :deep(.ProseMirror > p) {
  margin-top: var(--doc-space-before, 0px);
  margin-bottom: var(--doc-space-after, 8px);
  margin-left: var(--doc-indent-left, 0em);
  margin-right: var(--doc-indent-right, 0em);
  padding-left: var(--doc-hang, 0em);
  text-indent: var(--doc-first, 0em);
}
/* ---------- DOCX 分页占位：纸张下边距 + 灰色页缝 + 下一页上边距 ---------- */
.kiwi-editor :deep(.kiwi-page-gap) {
  display: block;
  box-sizing: border-box;
  position: relative;
  overflow: hidden;
  user-select: none;
  pointer-events: none;
}
.kiwi-editor :deep(.kiwi-page-gap-paper) {
  background: var(--doc-bg, #fff);
}
.kiwi-editor :deep(.kiwi-page-gap-band) {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: flex-end;
  background: #eef2f7;
  padding-right: 14px;
  box-shadow:
    inset 0 9px 14px -12px rgba(15, 23, 42, 0.28),
    inset 0 -9px 14px -12px rgba(15, 23, 42, 0.2);
}
.kiwi-editor :deep(.kiwi-page-gap-band span) {
  color: #94a3b8;
  font-size: 10px;
  letter-spacing: 0.06em;
}
/* 分页符：编辑区用虚线 + 标签标记，导出 Word 时转换为真实分页 */
.kiwi-editor :deep(.kiwi-page-break) {
  position: relative;
  height: 34px;
  margin: 18px 0;
  cursor: default;
  user-select: none;
}
.kiwi-editor :deep(.kiwi-page-break::before) {
  content: '';
  position: absolute;
  left: 0;
  right: 0;
  top: 50%;
  border-top: 1px dashed #cbd5e1;
}
.kiwi-editor :deep(.kiwi-page-break::after) {
  content: '分页符';
  position: absolute;
  left: 50%;
  top: 50%;
  transform: translate(-50%, -50%);
  padding: 0 8px;
  background: var(--doc-bg, #fff);
  color: #94a3b8;
  font-size: 10px;
  letter-spacing: 0.08em;
  white-space: nowrap;
}
.kiwi-editor :deep(.kiwi-page-break.ProseMirror-selectednode::before) {
  border-top-color: rgb(var(--kiwi-500));
}
.kiwi-editor :deep(.kiwi-page-break.ProseMirror-selectednode::after) {
  color: rgb(var(--kiwi-500));
}

/* 通用页脚 */
.editor-meta-bar {
  @apply mt-6 flex items-center justify-between border-t border-slate-200/60 pt-3 text-[10.5px] text-slate-400;
  letter-spacing: 0.01em;
}

@media (max-width: 1100px) {
  .editor-outline {
    @apply hidden;
  }
}
</style>

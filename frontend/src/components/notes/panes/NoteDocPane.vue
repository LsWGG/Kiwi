<script setup lang="ts">
/** 文档 / 导入笔记主面板：标题、自动保存、编辑/阅读、导入进度、反向链接。 */
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useNotesStore, type NoteOut, type NoteSummary } from '@/stores/notes'
import { useKbsStore } from '@/stores/kbs'
import KiwiEditor from '@/components/editor/KiwiEditor.vue'
import type { ParagraphFormatRecord } from '@/components/editor/extensions/paragraphFormat'
import type { TextFormatRecord } from '@/components/editor/extensions/textFormat'
import EditorModeMenu from '@/components/editor/EditorModeMenu.vue'
import EditorPageSettings from '@/components/editor/EditorPageSettings.vue'
import NoteAgentPanel from '@/components/editor/NoteAgentPanel.vue'
import NoteReadingTools from '@/components/notes/reading/NoteReadingTools.vue'
import WordPreview from '@/components/editor/WordPreview.vue'
import MarkdownView from '@/components/editor/MarkdownView.vue'
import KiwiIcon from '@/components/ui/KiwiIcon.vue'
import KiwiProgress from '@/components/ui/KiwiProgress.vue'
import NoteTitleBreadcrumb from '@/components/notes/NoteTitleBreadcrumb.vue'
import NoteEmojiButton from '@/components/notes/NoteEmojiButton.vue'
import NoteTagButton from '@/components/notes/NoteTagButton.vue'
import { useAutosave } from '@/composables/useAutosave'
import { useSaveShortcut } from '@/composables/useSaveShortcut'
import { useSyncedScroll } from '@/composables/useSyncedScroll'
import { stripLeadingTitleHeading } from '@/lib/wikiMarkdown'
import {
  resolveDocxPrefs,
  resolveEditorMode,
  resolvePagePrefs,
  type DocxPrefs,
  type EditorMode,
  type PagePrefs,
} from '@/components/editor/modes'
import { downloadNoteDocx } from '@/components/editor/docx'
import { toast } from '@/components/ui/toast'

const props = defineProps<{ note: NoteOut }>()
const emit = defineEmits<{
  (e: 'open-info'): void
  (e: 'open-backlink', noteId: string, mentionId?: string): void
}>()
const notes = useNotesStore()
const kbs = useKbsStore()
const router = useRouter()
const route = useRoute()
const paneRef = ref<HTMLElement | null>(null)

const title = ref(props.note.title)
const body = ref(props.note.body_md || '')

// ---------- 多视图：编辑 / 大纲 / 分屏 / 阅读（按笔记 ID 持久化） ----------
type DocView = 'edit' | 'outline' | 'split' | 'read'

const VIEW_KEY = `kiwi.note.view.${props.note.id}`
const DOC_VIEWS: { id: DocView; label: string; icon: string; hint: string }[] = [
  { id: 'edit', label: '编辑', icon: 'edit', hint: '全宽编辑，聚焦写作' },
  { id: 'outline', label: '大纲', icon: 'listTree', hint: '左侧大纲，滚动高亮、点击跳转' },
  { id: 'split', label: '分屏', icon: 'columns', hint: '左编辑 / 右实时预览' },
  { id: 'read', label: '阅读', icon: 'bookOpen', hint: '纯渲染阅读，适合长文回顾' },
]

function initialView(): DocView {
  try {
    const saved = localStorage.getItem(VIEW_KEY)
    if (saved === 'edit' || saved === 'outline' || saved === 'split' || saved === 'read') {
      return saved
    }
  } catch {
    /* 隐私模式下忽略 */
  }
  return props.note.view_mode === 'read' ? 'read' : 'edit'
}

const viewMode = ref<DocView>(initialView())
const readMode = computed(() => viewMode.value === 'read')
const showOutline = computed(() => viewMode.value === 'outline')
const splitMode = computed(() => viewMode.value === 'split')

// 头部已经展示标题，阅读态与分屏预览不再重复渲染正文的首个同名一级标题。
const previewBody = computed(() => stripLeadingTitleHeading(body.value, title.value))
const readBody = computed(() => (readMode.value ? previewBody.value : body.value))

function setView(mode: DocView) {
  if (viewMode.value === mode) return
  try {
    localStorage.setItem(VIEW_KEY, mode)
  } catch {
    /* 隐私模式下忽略 */
  }
  viewMode.value = mode
  agentOpen.value = false
  if (mode !== 'read') {
    readZoom.value = 1
    readZen.value = false
    showPageSettings.value = false
  }
  void autosave.flushNow()
}

const backlinks = ref<NoteSummary[]>([])
const editorRef = ref<InstanceType<typeof KiwiEditor> | null>(null)

// ---------- 反向链接浮层：直接展示列表，不再打开右侧信息面板 ----------
const backlinkOpen = ref(false)
const backlinkTrigger = ref<HTMLElement | null>(null)
const backlinkPos = ref({ left: '0px', top: '0px' })

/**
 * 浮层挂到 <html> 下：外层用视口坐标定位，内层单独应用 --ui-scale。
 * 若把 zoom 加在定位元素本身，left/top 会一起被放大，在 4K 下会飘到右下方。
 */
function backlinkScale(): number {
  const raw = getComputedStyle(document.documentElement).getPropertyValue('--ui-scale')
  const value = Number.parseFloat(raw)
  return Number.isFinite(value) && value > 0 ? value : 1
}

function placeBacklinks() {
  if (!backlinkOpen.value) return
  const rect = backlinkTrigger.value?.getBoundingClientRect()
  if (!rect) return
  const scale = backlinkScale()
  const width = 320 * scale
  const height = 340 * scale
  backlinkPos.value = {
    left: `${Math.max(8, Math.min(rect.right - width, window.innerWidth - width - 8))}px`,
    top: `${Math.max(8, Math.min(rect.bottom + 6, window.innerHeight - height))}px`,
  }
}

function toggleBacklinks() {
  backlinkOpen.value = !backlinkOpen.value
}

function closeBacklinks() {
  backlinkOpen.value = false
}

function onBacklinkKey(event: KeyboardEvent) {
  if (event.key === 'Escape') closeBacklinks()
}

function openBacklink(link: NoteSummary) {
  closeBacklinks()
  emit('open-backlink', link.id, props.note.id)
}

/** 引用上下文是正文切片，去掉 Markdown 标记后只保留可读摘要。 */
function backlinkContext(raw?: string): string {
  if (!raw) return ''
  const text = raw
    .replace(/!\[([^\]]*)\]\([^)\n]*(?:\)|$)/g, '$1')
    .replace(/\[@([^\]]+)\]\([^)\n]*(?:\)|$)/g, '@$1')
    .replace(/\[([^\]]+)\]\([^)\n]*(?:\)|$)/g, '$1')
    .replace(/\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?/g, ' ')
    .replace(/(^|\s)[-+]\s+/g, ' ')
    .replace(/[#>*_`|]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
  return text.length > 150 ? `${text.slice(0, 150)}…` : text
}

watch(backlinkOpen, (value) => {
  if (value) {
    placeBacklinks()
    window.addEventListener('keydown', onBacklinkKey)
  } else {
    window.removeEventListener('keydown', onBacklinkKey)
  }
})

onBeforeUnmount(() => {
  window.removeEventListener('keydown', onBacklinkKey)
})

// ---------- 阅读演示层 ----------
const readingAreaRef = ref<HTMLElement | null>(null)
/** 阅读模式下的实际滚动容器：演示层覆盖其上，需要把滚轮事件转发给它。 */
const readingScrollRef = ref<HTMLElement | null>(null)
/** 分屏右侧实时预览的滚动容器。 */
const previewScrollRef = ref<HTMLElement | null>(null)
const readZoom = ref(1)
const readZen = ref(false)

useSyncedScroll(readingScrollRef, previewScrollRef, splitMode)

// ---------- 编辑器模式 ----------
const modeOverride = ref<EditorMode | null>(null)
const editorMode = computed(
  () => modeOverride.value ?? resolveEditorMode(props.note.kind, props.note.props_json),
)
// Agent 底部指令栏：Simple 由工具栏 Agent 按钮控制，Notion 通过 /ai 唤起
const agentOpen = ref(false)
const agentMode = computed(
  () =>
    (editorMode.value === 'simple' || editorMode.value === 'notion') &&
    agentOpen.value &&
    !readMode.value,
)
watch(editorMode, () => {
  agentOpen.value = false
})
const exporting = ref(false)
const docxPrefs = computed(() => resolveDocxPrefs(props.note.props_json?.docx_prefs))
const pagePrefs = computed(() => resolvePagePrefs(props.note.props_json?.page_prefs))

/** DOCX 段落级排版：编辑器回传、随自动保存写入 props_json.paragraph_formats。 */
const paragraphFormats = ref<ParagraphFormatRecord[]>(
  Array.isArray(props.note.props_json?.paragraph_formats)
    ? (props.note.props_json?.paragraph_formats as ParagraphFormatRecord[])
    : [],
)
/** 字符级字体 / 字号：只记录选中的文字片段。 */
const textFormats = ref<TextFormatRecord[]>(
  Array.isArray(props.note.props_json?.text_formats)
    ? (props.note.props_json?.text_formats as TextFormatRecord[])
    : [],
)

const showPageSettings = ref(false)

// 退出阅读模式时收起演示工具与页面设置
watch(readMode, (on) => {
  if (on) return
  readZoom.value = 1
  readZen.value = false
  showPageSettings.value = false
})

async function onDocxPrefs(prefs: DocxPrefs) {
  try {
    await notes.updateNote(props.note.id, { props_json: { docx_prefs: prefs } })
  } catch (e: any) {
    toast.error(e.message || '保存页面设置失败')
  }
}

async function onPagePrefs(prefs: PagePrefs) {
  try {
    await notes.updateNote(props.note.id, { props_json: { page_prefs: prefs } })
  } catch (e: any) {
    toast.error(e.message || '保存页面设置失败')
  }
}

/** 页面设置里的快捷入口：关闭侧栏后直接把光标放到纸张页眉 / 页脚 */
async function editHeaderOnPage() {
  showPageSettings.value = false
  await nextTick()
  editorRef.value?.startHeaderEdit()
}

async function editFooterOnPage() {
  showPageSettings.value = false
  await nextTick()
  editorRef.value?.startFooterEdit()
}

async function setEditorMode(mode: EditorMode) {
  modeOverride.value = mode
  try {
    await notes.updateNote(props.note.id, { props_json: { editor_mode: mode } })
  } catch (e: any) {
    modeOverride.value = null
    toast.error(e.message || '保存编辑器模式失败')
  }
}

function onAgentApply(payload: {
  text: string
  range: { from: number; to: number } | null
}) {
  editorRef.value?.insertMarkdown(payload.text, payload.range)
}

async function exportDocx() {
  exporting.value = true
  try {
    await downloadNoteDocx(props.note.id, kbs.currentKbId, title.value)
    toast.success('Word 文档已导出')
  } catch (e: any) {
    toast.error(e.message || '导出失败')
  } finally {
    exporting.value = false
  }
}

let lastSentTitle = ''
let lastSentBody = ''

const autosave = useAutosave(async () => {
  const patch = {
    title: title.value.trim() || '无标题文档',
    body_md: body.value,
    view_mode: readMode.value ? 'read' : 'edit',
    props_json: {
      paragraph_formats: paragraphFormats.value,
      text_formats: textFormats.value,
    },
  }
  lastSentTitle = patch.title
  lastSentBody = patch.body_md
  await notes.updateNote(props.note.id, patch)
  void loadBacklinks()
})

useSaveShortcut(() => autosave.flushNow())

const liveStatus = computed(() =>
  notes.importNoteId === props.note.id ? notes.importStatus : null,
)
interface ImportMeta {
  status?: string
  progress?: number
  error?: string | null
}
const importInfo = computed<ImportMeta | null>(() => {
  const fromNote = (props.note.props_json?.import as ImportMeta | undefined) ?? null
  return liveStatus.value ?? fromNote
})
const isImport = computed(() => props.note.kind === 'import')
const importing = computed(() => {
  if (!isImport.value) return false
  const status = importInfo.value?.status
  return status === 'parsing' || status === 'importing' || (!status && !body.value)
})
const importFailed = computed(() => isImport.value && importInfo.value?.status === 'failed')
const progressPct = computed(() =>
  Math.round((importInfo.value?.progress ?? 0) * 100),
)

const updatedText = computed(() => {
  const raw = props.note.updated_at
  if (!raw) return ''
  const d = new Date(raw)
  return `更新于 ${d.toLocaleDateString('zh-CN')} ${d.toLocaleTimeString('zh-CN', {
    hour: '2-digit',
    minute: '2-digit',
  })}`
})

watch(
  () => props.note.body_md,
  (val) => {
    if (val === body.value || val === lastSentBody) return
    if (autosave.saving.value) return
    body.value = val
  },
)
watch(
  () => props.note.title,
  (val) => {
    if (val === title.value || val === lastSentTitle) return
    if (autosave.saving.value) return
    title.value = val
  },
)

function onBody(md: string) {
  body.value = md
  autosave.schedule()
}
function onParagraphFormats(formats: ParagraphFormatRecord[]) {
  paragraphFormats.value = formats
  autosave.schedule()
}
function onTextFormats(formats: TextFormatRecord[]) {
  textFormats.value = formats
  autosave.schedule()
}
function onTitleInput() {
  autosave.schedule()
}

// ---------- Word 预览（DOCX 模式，右侧分栏展示导出后的分页效果） ----------
const wordPreview = ref(false)
const wordPreviewVersion = ref(0)
const wordPreviewRef = ref<InstanceType<typeof WordPreview> | null>(null)
/** Word 分栏时工具栏移到分栏上方，横跨正文与预览两栏。 */
const docxToolbarExternal = computed(
  () => !readMode.value && editorMode.value === 'docx' && !agentMode.value,
)
/** 预览页与正文纸张顶部对齐：按正文纸张在滚动内容中的偏移计算。 */
const previewTop = ref(24)
let previewResizeObserver: ResizeObserver | null = null

/** 4K 缩放下 getBoundingClientRect 被放大，换算成未缩放的 CSS 像素。 */
function uiScale(): number {
  const raw = getComputedStyle(document.documentElement).getPropertyValue('--ui-scale')
  const value = Number.parseFloat(raw)
  return Number.isFinite(value) && value > 0 ? value : 1
}

function syncPreviewTop() {
  const area = readingAreaRef.value
  const scroller = readingScrollRef.value
  const pane = area?.querySelector('.word-preview-pane') as HTMLElement | null
  const sheet = scroller?.querySelector('.editor-sheet') as HTMLElement | null
  if (!area || !scroller || !sheet || !pane) {
    previewTop.value = 24
    return
  }
  const header = pane.querySelector('header') as HTMLElement | null
  const wrapper = pane.querySelector('.kiwi-docx-wrapper') as HTMLElement | null
  const sheetOffset =
    (sheet.getBoundingClientRect().top - scroller.getBoundingClientRect().top) / uiScale() +
    scroller.scrollTop
  const chrome =
    (header?.offsetHeight ?? 0) +
    (wrapper ? Number.parseFloat(getComputedStyle(wrapper).paddingTop) || 0 : 0)
  previewTop.value = Math.max(0, Math.round(sheetOffset - chrome))
}

/* ---------- 正文与预览同步滚动（按可滚动高度比例对齐） ---------- */
let scrollSyncLock = 0

function scrollRatio(el: HTMLElement): number {
  const max = el.scrollHeight - el.clientHeight
  return max > 0 ? el.scrollTop / max : 0
}

function syncScrollTo(el: HTMLElement | null | undefined, ratio: number) {
  if (!el) return
  const max = el.scrollHeight - el.clientHeight
  if (max <= 0) return
  const target = ratio * max
  if (Math.abs(el.scrollTop - target) < 2) return
  scrollSyncLock = Date.now() + 120
  el.scrollTop = target
}

function onEditorScroll() {
  if (!wordPreview.value || Date.now() < scrollSyncLock) return
  const preview = wordPreviewRef.value?.scrollEl
  if (!preview) return
  syncScrollTo(preview, scrollRatio(readingScrollRef.value as HTMLElement))
}

function onPreviewScroll(ratio: number) {
  if (!wordPreview.value || Date.now() < scrollSyncLock) return
  syncScrollTo(readingScrollRef.value, ratio)
}

function onPreviewRendered() {
  void nextTick(() => {
    syncPreviewTop()
    // 打开预览时按正文当前位置对齐
    const preview = wordPreviewRef.value?.scrollEl
    if (preview && readingScrollRef.value) {
      const ratio = scrollRatio(readingScrollRef.value)
      const max = preview.scrollHeight - preview.clientHeight
      if (max > 0) preview.scrollTop = ratio * max
    }
  })
}

async function toggleWordPreview() {
  if (wordPreview.value) {
    wordPreview.value = false
    return
  }
  await autosave.flushNow()
  wordPreview.value = true
  wordPreviewVersion.value += 1
}

// 预览打开后按正文纸张顶部对齐；窗口尺寸变化时重新对齐。
watch(wordPreview, async (open) => {
  previewResizeObserver?.disconnect()
  previewResizeObserver = null
  if (!open) return
  await nextTick()
  syncPreviewTop()
  const area = readingAreaRef.value
  if (area && typeof ResizeObserver !== 'undefined') {
    previewResizeObserver = new ResizeObserver(syncPreviewTop)
    previewResizeObserver.observe(area)
  }
})

function onWindowResize() {
  if (wordPreview.value) syncPreviewTop()
}

onMounted(() => window.addEventListener('resize', onWindowResize))
onBeforeUnmount(() => {
  window.removeEventListener('resize', onWindowResize)
  previewResizeObserver?.disconnect()
  if (prefsPreviewTimer !== null) window.clearTimeout(prefsPreviewTimer)
  clearCiteTimers()
})

// 自动保存完成后刷新预览，保证预览与正文同步
watch(
  () => autosave.revision.value,
  () => {
    if (wordPreview.value) wordPreviewVersion.value += 1
  },
)

// 纸张 / 页眉页脚设置变化时刷新预览（滑杆连续触发，做一次防抖）
let prefsPreviewTimer: number | null = null
watch(
  docxPrefs,
  () => {
    if (!wordPreview.value) return
    if (prefsPreviewTimer !== null) window.clearTimeout(prefsPreviewTimer)
    prefsPreviewTimer = window.setTimeout(() => {
      prefsPreviewTimer = null
      wordPreviewVersion.value += 1
    }, 500)
  },
  { deep: true },
)

// 离开阅读模式 / 切换编辑器模式时收起预览
watch([readMode, editorMode], () => {
  wordPreview.value = false
})

function focusBody() {
  if (!readMode.value) editorRef.value?.focus()
}

async function loadBacklinks() {
  try {
    backlinks.value = await notes.getBacklinks(props.note.id)
  } catch {
    backlinks.value = []
  }
}

/* ---------- 反向链接跳转：定位并高亮正文中的引用位置 ---------- */
let citeSeq = 0
let citeRetry: number | null = null
let citeFlashTimer: number | null = null

function clearCiteTimers() {
  if (citeRetry !== null) {
    window.clearTimeout(citeRetry)
    citeRetry = null
  }
  if (citeFlashTimer !== null) {
    window.clearTimeout(citeFlashTimer)
    citeFlashTimer = null
  }
}

function locateMention(raw: string, attempt = 0) {
  const id = raw.trim()
  if (!id) return
  const seq = ++citeSeq
  if (citeRetry !== null) {
    window.clearTimeout(citeRetry)
    citeRetry = null
  }
  const find = () => {
    if (seq !== citeSeq) return
    const root = paneRef.value
    const target = root?.querySelector<HTMLElement>(
      `[data-type="mention"][data-id="${CSS.escape(id)}"]`,
    )
    if (target) {
      root
        ?.querySelectorAll('.kiwi-cite-flash')
        .forEach((el) => el.classList.remove('kiwi-cite-flash'))
      target.classList.add('kiwi-cite-flash')
      target.scrollIntoView({ block: 'center', behavior: 'smooth' })
      if (citeFlashTimer !== null) window.clearTimeout(citeFlashTimer)
      citeFlashTimer = window.setTimeout(() => {
        target.classList.remove('kiwi-cite-flash')
        citeFlashTimer = null
      }, 2300)
      return
    }
    // 编辑器 / 只读渲染尚未完成时短暂重试，避免跳转落空。
    if (attempt < 26) {
      citeRetry = window.setTimeout(() => {
        citeRetry = null
        locateMention(id, attempt + 1)
      }, 150)
    }
  }
  void nextTick(find)
}

watch(
  () => [route.query.mention, route.query.t, props.note.id],
  () => {
    const mention = route.query.mention
    if (typeof mention === 'string' && mention) locateMention(mention)
  },
  { immediate: true },
)

onMounted(loadBacklinks)

/** 一键复制为 Markdown：优先取编辑器序列化结果，阅读态回落到已保存正文。 */
async function copyMarkdown() {
  const markdown = editorRef.value?.getMarkdown?.() ?? body.value ?? ''
  if (!markdown.trim()) {
    toast.info('当前笔记还没有可复制的内容')
    return
  }
  try {
    await navigator.clipboard.writeText(markdown)
    toast.success('已复制 Markdown')
  } catch {
    // 非安全上下文 / 剪贴板权限受限时回落
    const area = document.createElement('textarea')
    area.value = markdown
    area.style.position = 'fixed'
    area.style.opacity = '0'
    document.body.appendChild(area)
    area.select()
    try {
      document.execCommand('copy')
      toast.success('已复制 Markdown')
    } catch {
      toast.error('复制失败，请手动选择正文复制')
    } finally {
      area.remove()
    }
  }
}
</script>

<template>
  <div ref="paneRef" class="h-full flex flex-col">
    <header class="shrink-0 h-11 flex items-center gap-2 px-4 border-b border-slate-200/50 bg-white/40">
      <NoteTitleBreadcrumb
        v-model:title="title"
        :note-id="note.id"
        :emoji="note.props_json?.emoji"
        :kind="note.kind"
        :folder-id="note.folder_id"
        placeholder="无标题文档"
        @input="onTitleInput"
      />
      <span
        v-if="isImport"
        class="shrink-0 rounded-md bg-orange-50 px-1.5 py-0.5 text-[10px] text-orange-500 border border-orange-100"
      >
        导入
      </span>
      <button
        type="button"
        class="inline-flex shrink-0 items-center justify-center rounded-lg p-1.5 text-slate-400 transition-colors hover:bg-kiwi-50 hover:text-kiwi-700"
        title="复制整篇笔记的 Markdown"
        aria-label="复制 Markdown"
        @click="copyMarkdown"
      >
        <KiwiIcon name="copy" :size="13" />
      </button>
      <div class="flex-1" />
      <span class="shrink-0 whitespace-nowrap text-[10px] text-slate-400 tabular-nums">
        <template v-if="autosave.saving.value">
          <KiwiIcon name="loader" :size="10" spin class="inline -mt-px mr-1" />保存中…
        </template>
        <template v-else-if="autosave.savedAt.value">已保存 {{ autosave.savedAt.value }}</template>
      </span>
      <NoteTagButton :note="note" />
      <button
        v-if="backlinks.length"
        ref="backlinkTrigger"
        type="button"
        class="inline-flex shrink-0 items-center gap-1 rounded-lg px-2 py-1 text-[10.5px] transition-colors"
        :class="
          backlinkOpen
            ? 'bg-kiwi-50 text-kiwi-700'
            : 'text-slate-500 hover:bg-kiwi-50 hover:text-kiwi-700'
        "
        title="查看引用本文的笔记"
        :aria-expanded="backlinkOpen"
        @click="toggleBacklinks"
      >
        <KiwiIcon name="link2" :size="12" />
        反向链接
        <span class="tabular-nums text-slate-400">{{ backlinks.length }}</span>
      </button>
      <!-- 四种视图：编辑 / 大纲 / 分屏 / 阅读，按笔记持久化 -->
      <div class="flex shrink-0 items-center rounded-lg border border-slate-200/80 bg-white/70 p-0.5">
        <button
          v-for="view in DOC_VIEWS"
          :key="view.id"
          type="button"
          class="inline-flex items-center gap-1 rounded-md px-2 py-1 text-[10.5px] transition-colors"
          :class="
            viewMode === view.id
              ? 'bg-kiwi-50 font-medium text-kiwi-700'
              : 'text-slate-500 hover:bg-slate-50 hover:text-slate-700'
          "
          :title="view.hint"
          @click="setView(view.id)"
        >
          <KiwiIcon :name="view.icon" :size="12" />
          {{ view.label }}
        </button>
      </div>
      <template v-if="!readMode">
        <button
          v-if="editorMode === 'docx'"
          class="kiwi-btn-ghost !py-1 !px-2 !text-[11px]"
          title="导出 Word"
          :disabled="exporting"
          @click="exportDocx"
        >
          <KiwiIcon :name="exporting ? 'loader' : 'download'" :size="13" :spin="exporting" />
          Word
        </button>
        <button
          type="button"
          class="kiwi-btn-ghost whitespace-nowrap !py-1 !px-2 !text-[11px]"
          :class="showPageSettings ? 'bg-kiwi-50 text-kiwi-700' : ''"
          title="页面设置"
          @click="showPageSettings = !showPageSettings"
        >
          <KiwiIcon name="settings" :size="13" />
          页面设置
        </button>
        <EditorModeMenu :mode="editorMode" @change="setEditorMode" />
      </template>
    </header>

    <!-- 反向链接浮层：列表直接展示，点击条目跳到正文引用位置 -->
    <Teleport to="html">
      <div
        v-if="backlinkOpen"
        class="fixed inset-0 z-[95]"
        @mousedown="closeBacklinks"
        @contextmenu.prevent="closeBacklinks"
      >
        <div class="absolute" :style="backlinkPos">
          <div
            class="w-[320px] rounded-xl border border-slate-200/80 bg-white/95 p-2.5 shadow-lifted backdrop-blur-xl animate-scale-in"
            :style="{ zoom: 'var(--ui-scale)' }"
            @mousedown.stop
          >
          <div class="mb-1.5 flex items-center justify-between px-1">
            <p class="text-[11.5px] font-medium text-slate-600">
              反向链接
              <span class="ml-1 text-[10px] font-normal text-slate-400">
                {{ backlinks.length }} 篇笔记引用了本文
              </span>
            </p>
            <button
              type="button"
              class="rounded p-0.5 text-slate-400 transition-colors hover:text-slate-600"
              title="关闭"
              @click="closeBacklinks"
            >
              <KiwiIcon name="close" :size="11" />
            </button>
          </div>
          <div class="max-h-[300px] space-y-0.5 overflow-y-auto">
            <button
              v-for="link in backlinks"
              :key="link.id"
              type="button"
              class="group w-full rounded-lg px-2 py-1.5 text-left transition-colors hover:bg-kiwi-50/70"
              :title="backlinkContext(link.context) || link.title"
              @click="openBacklink(link)"
            >
              <div class="flex items-center gap-1.5">
                <KiwiIcon name="link2" :size="10" class="shrink-0 text-kiwi-300" />
                <span class="truncate text-[11px] text-slate-600 group-hover:text-kiwi-700">
                  {{ link.title || '无标题' }}
                </span>
                <KiwiIcon
                  name="arrowUpRight"
                  :size="10"
                  class="ml-auto shrink-0 text-kiwi-400 opacity-0 transition-opacity group-hover:opacity-100"
                />
              </div>
              <p
                v-if="backlinkContext(link.context)"
                class="mt-0.5 line-clamp-2 pl-[17px] text-[9.5px] leading-relaxed text-slate-400"
              >
                {{ backlinkContext(link.context) }}
              </p>
            </button>
          </div>
          <p class="mt-1.5 border-t border-slate-100 px-1 pt-1.5 text-[9.5px] text-slate-300">
            点击条目打开来源笔记，并定位到引用位置
          </p>
          </div>
        </div>
      </div>
    </Teleport>

    <!-- Word 分栏预览：工具栏横跨正文与预览两栏 -->
    <div v-if="docxToolbarExternal" class="shrink-0">
      <div class="w-full px-6 pt-6">
        <div id="note-docx-toolbar-slot" />
      </div>
    </div>

    <div
      ref="readingAreaRef"
      class="flex-1 min-h-0 relative flex"
      :class="{ 'reading-zen': readMode && readZen }"
    >
      <div
        ref="readingScrollRef"
        class="h-full min-w-0 flex-1 overflow-auto bg-slate-50/50"
        :class="readMode ? 'cursor-none' : ''"
        @scroll.passive="onEditorScroll"
      >
        <div
          class="mx-auto flex min-h-full w-full max-w-[1480px] flex-col px-6"
          :class="readMode ? 'pt-6 pb-28' : docxToolbarExternal ? 'pt-0 pb-6' : 'py-6'"
          :style="readMode ? { zoom: readZoom } : undefined"
        >
          <!-- 导入进度 -->
          <div
            v-if="importing || importFailed"
            class="mb-4 rounded-xl border px-3.5 py-3"
            :class="importFailed ? 'border-rose-200 bg-rose-50/70' : 'border-amber-200 bg-amber-50/60'"
          >
            <div class="flex items-center gap-2 text-[12px]">
              <KiwiIcon
                :name="importFailed ? 'alert' : 'loader'"
                :size="14"
                :spin="!importFailed"
                :class="importFailed ? 'text-rose-500' : 'text-amber-500'"
              />
              <span :class="importFailed ? 'text-rose-600' : 'text-amber-700'">
                {{
                  importFailed
                    ? '解析失败'
                    : importInfo?.status === 'ready'
                      ? '解析完成'
                      : '正在解析文档…'
                }}
              </span>
              <span v-if="!importFailed" class="ml-auto tabular-nums text-[11px] text-amber-600">
                {{ progressPct }}%
              </span>
            </div>
            <p v-if="importFailed" class="mt-1.5 text-[11px] leading-relaxed text-rose-500">
              {{ importInfo?.error || '未知错误' }}
            </p>
            <p v-else class="mt-1 text-[11px] text-amber-600/80">
              解析、切分与向量化在后台进行，完成后正文会自动填充；期间正文只读。
            </p>
            <KiwiProgress
              v-if="!importFailed"
              class="mt-2"
              :value="importInfo?.progress ?? 0"
              :status="importInfo?.status === 'ready' ? 'done' : 'running'"
            />
          </div>

          <KiwiEditor
            :key="editorMode"
            ref="editorRef"
            class="flex-1"
            :content="readBody"
            :note-id="note.id"
            :readonly="readMode || importing"
            :mode="editorMode"
            :docx-prefs="docxPrefs"
            :page-prefs="pagePrefs"
            :paragraph-formats="note.props_json?.paragraph_formats"
            :text-formats="note.props_json?.text_formats"
            :doc-title="title"
            :show-outline="showOutline"
            :agent-open="agentMode"
            :toolbar-host="docxToolbarExternal ? '#note-docx-toolbar-slot' : null"
            @update="onBody"
            @paragraph-formats="onParagraphFormats"
            @text-formats="onTextFormats"
            @docx-prefs="onDocxPrefs"
            @word-preview="toggleWordPreview"
            @toggle-agent="agentOpen = !agentOpen"
          >
            <template #header>
              <div class="flex items-center gap-1.5">
                <NoteEmojiButton
                  v-if="!readMode"
                  :note-id="note.id"
                  :emoji="note.props_json?.emoji"
                  :kind="note.kind"
                  :size="22"
                />
                <span
                  v-else-if="note.props_json?.emoji"
                  class="w-9 shrink-0 text-center text-[24px] leading-none"
                >{{ note.props_json.emoji }}</span>
                <h1
                  v-if="readMode"
                  class="min-w-0 flex-1 text-[26px] leading-tight font-semibold text-slate-800"
                >
                  {{ title || '无标题文档' }}
                </h1>
                <input
                  v-else
                  v-model="title"
                  class="min-w-0 flex-1 bg-transparent text-[26px] leading-tight font-semibold text-slate-800 outline-none placeholder:text-slate-300"
                  placeholder="无标题文档"
                  @input="onTitleInput"
                  @keydown.enter.prevent="focusBody"
                />
              </div>
              <p class="mt-2 text-[11px] text-slate-400">{{ updatedText }}</p>
            </template>
          </KiwiEditor>
        </div>
      </div>

      <!-- 分屏视图：左侧编辑 / 右侧实时渲染预览 -->
      <div
        v-if="viewMode === 'split'"
        class="flex min-h-0 w-[46%] min-w-[320px] shrink-0 flex-col border-l border-slate-200/70 bg-white/60"
      >
        <div
          class="flex shrink-0 items-center gap-1.5 border-b border-slate-200/60 px-4 py-2 text-[10.5px] text-slate-400"
        >
          <KiwiIcon name="bookOpen" :size="12" />
          实时预览
          <span class="ml-auto tabular-nums">{{ body.length.toLocaleString() }} 字符</span>
        </div>
        <div ref="previewScrollRef" class="min-h-0 flex-1 overflow-auto px-6 py-5">
          <h1 class="mb-3 text-[24px] leading-tight font-semibold text-slate-800">
            {{ title || '无标题文档' }}
          </h1>
          <MarkdownView :content="previewBody" />
        </div>
      </div>

      <!-- DOCX 模式：右侧 Word 导出预览，与正文画布同高 -->
      <div
        v-if="wordPreview && !readMode && viewMode !== 'split' && editorMode === 'docx'"
        class="flex min-h-0 w-[47%] min-w-[360px] shrink-0 pb-6 pr-6"
        :style="{ paddingTop: `${previewTop}px` }"
      >
        <WordPreview
          ref="wordPreviewRef"
          :note-id="note.id"
          :kb-id="kbs.currentKbId ?? ''"
          :docx-prefs="docxPrefs"
          :doc-title="title"
          active
          :version="wordPreviewVersion"
          @close="wordPreview = false"
          @rendered="onPreviewRendered"
          @scroll="onPreviewScroll"
        />
      </div>

      <!-- 阅读模式：激光点 + 演示笔 + 缩放 / 全屏 -->
      <NoteReadingTools
        v-if="readMode"
        :area-el="readingAreaRef"
        :scroller-el="readingScrollRef"
        :zoom="readZoom"
        :zen="readZen"
        @update:zoom="readZoom = $event"
        @update:zen="readZen = $event"
      />

      <!-- 页面设置抽屉 -->
      <EditorPageSettings
        v-if="showPageSettings && !readMode"
        docked
        :mode="editorMode"
        :docx-prefs="docxPrefs"
        :page-prefs="pagePrefs"
        @docx-prefs="onDocxPrefs"
        @page-prefs="onPagePrefs"
        @edit-header="editHeaderOnPage"
        @edit-footer="editFooterOnPage"
        @close="showPageSettings = false"
      />

      <!-- Simple 模式的 Agent 组件：悬浮 AI 指令栏 -->
      <div
        v-if="agentMode"
        class="pointer-events-none absolute inset-x-0 bottom-0 z-30 flex justify-center bg-gradient-to-t from-slate-50/90 via-slate-50/55 to-transparent px-6 pb-4 pt-12"
      >
        <div class="pointer-events-auto w-full max-w-2xl">
          <NoteAgentPanel
            :note-id="note.id"
            :get-selection="() => editorRef?.getSelectionText() ?? ''"
            :get-selection-range="() => editorRef?.getSelectionRange() ?? null"
            :get-document-text="() => editorRef?.getDocumentText() ?? ''"
            @apply="onAgentApply"
          />
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.reading-zen {
  position: fixed;
  inset: 0;
  z-index: 100;
  overflow: hidden;
  background: #f8fafc;
}
</style>

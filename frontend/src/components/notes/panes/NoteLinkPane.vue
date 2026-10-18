<script setup lang="ts">
/** 链接笔记：书签卡片 + 抓取正文阅读/编辑 + 重新抓取。 */
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useNotesStore, type LinkMeta, type NoteOut } from '@/stores/notes'
import KiwiEditor from '@/components/editor/KiwiEditor.vue'
import type { ParagraphFormatRecord } from '@/components/editor/extensions/paragraphFormat'
import type { TextFormatRecord } from '@/components/editor/extensions/textFormat'
import EditorModeMenu from '@/components/editor/EditorModeMenu.vue'
import EditorPageSettings from '@/components/editor/EditorPageSettings.vue'
import NoteAgentPanel from '@/components/editor/NoteAgentPanel.vue'
import NoteReadingTools from '@/components/notes/reading/NoteReadingTools.vue'
import WordPreview from '@/components/editor/WordPreview.vue'
import KiwiIcon from '@/components/ui/KiwiIcon.vue'
import NoteTitleBreadcrumb from '@/components/notes/NoteTitleBreadcrumb.vue'
import NoteEmojiButton from '@/components/notes/NoteEmojiButton.vue'
import NoteTagButton from '@/components/notes/NoteTagButton.vue'
import { useAutosave } from '@/composables/useAutosave'
import { useSaveShortcut } from '@/composables/useSaveShortcut'
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
import { useKbsStore } from '@/stores/kbs'

const props = defineProps<{ note: NoteOut }>()
const notes = useNotesStore()
const kbs = useKbsStore()

const title = ref(props.note.title)
const body = ref(props.note.body_md || '')
const readMode = ref(true)
const refreshing = ref(false)
const faviconBroken = ref(false)
const editorRef = ref<InstanceType<typeof KiwiEditor> | null>(null)
const exporting = ref(false)

const modeOverride = ref<EditorMode | null>(null)
const editorMode = computed(
  () => modeOverride.value ?? resolveEditorMode('link', props.note.props_json),
)
// Agent 已合并进 Simple：由工具栏的 Agent 按钮控制底部指令栏
const agentOpen = ref(false)
const agentMode = computed(
  () => editorMode.value === 'simple' && agentOpen.value && !readMode.value,
)
watch(editorMode, () => {
  agentOpen.value = false
})
const docxPrefs = computed(() => resolveDocxPrefs(props.note.props_json?.docx_prefs))
const pagePrefs = computed(() => resolvePagePrefs(props.note.props_json?.page_prefs))

/** DOCX 段落级排版：编辑器回传、随自动保存写入 props_json.paragraph_formats。 */
const paragraphFormats = ref<ParagraphFormatRecord[]>(
  Array.isArray(props.note.props_json?.paragraph_formats)
    ? (props.note.props_json?.paragraph_formats as ParagraphFormatRecord[])
    : [],
)
const textFormats = ref<TextFormatRecord[]>(
  Array.isArray(props.note.props_json?.text_formats)
    ? (props.note.props_json?.text_formats as TextFormatRecord[])
    : [],
)

function readFlag(key: string, fallback: boolean): boolean {
  try {
    const raw = localStorage.getItem(key)
    return raw === null ? fallback : raw === '1'
  } catch {
    return fallback
  }
}
function writeFlag(key: string, value: boolean) {
  try {
    localStorage.setItem(key, value ? '1' : '0')
  } catch {
    /* 隐私模式下忽略 */
  }
}

// 目录默认收起，用户展开后记住选择
const showOutline = ref(readFlag('kiwi.editor.outline.v2', false))
const showPageSettings = ref(false)
watch(showOutline, (value) => writeFlag('kiwi.editor.outline.v2', value))

// ---------- 阅读演示层 ----------
const readingAreaRef = ref<HTMLElement | null>(null)
/** 阅读模式下的实际滚动容器：演示层覆盖其上，需要把滚轮事件转发给它。 */
const readingScrollRef = ref<HTMLElement | null>(null)
const readZoom = ref(1)
const readZen = ref(false)
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

const link = computed<Partial<LinkMeta>>(
  () => (props.note.props_json?.link as Partial<LinkMeta>) ?? {},
)
const failed = computed(() => link.value.fetch_status === 'failed')
const hasBody = computed(() => !!body.value.trim())

let lastSentTitle = ''
let lastSentBody = ''

const autosave = useAutosave(async () => {
  const patch = {
    title: title.value.trim() || '链接',
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
})

useSaveShortcut(() => autosave.flushNow())

watch(
  () => props.note.body_md,
  (val) => {
    if (val === body.value || val === lastSentBody || autosave.saving.value) return
    body.value = val
  },
)
watch(
  () => props.note.title,
  (val) => {
    if (val === title.value || val === lastSentTitle || autosave.saving.value) return
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

function toggleMode() {
  readMode.value = !readMode.value
  agentOpen.value = false
  void autosave.flushNow()
}

// ---------- Word 预览（DOCX 模式，右侧分栏展示导出后的分页效果） ----------
const wordPreview = ref(false)
const wordPreviewVersion = ref(0)
const wordPreviewRef = ref<InstanceType<typeof WordPreview> | null>(null)
const docxToolbarExternal = computed(
  () => !readMode.value && editorMode.value === 'docx' && !agentMode.value,
)
const previewTop = ref(24)

/** 4K 缩放下 getBoundingClientRect 被放大，换算成未缩放的 CSS 像素。 */
function uiScale(): number {
  const raw = getComputedStyle(document.documentElement).getPropertyValue('--ui-scale')
  const value = Number.parseFloat(raw)
  return Number.isFinite(value) && value > 0 ? value : 1
}

/** 预览页与正文纸张顶部对齐：按正文纸张在滚动内容中的偏移计算。 */
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
  const editor = readingScrollRef.value
  const preview = wordPreviewRef.value?.scrollEl
  if (!editor || !preview) return
  syncScrollTo(preview, scrollRatio(editor))
}

function onPreviewScroll(ratio: number) {
  if (!wordPreview.value || Date.now() < scrollSyncLock) return
  syncScrollTo(readingScrollRef.value, ratio)
}

function onPreviewRendered() {
  void nextTick(() => {
    syncPreviewTop()
    const preview = wordPreviewRef.value?.scrollEl
    const editor = readingScrollRef.value
    if (!preview || !editor) return
    const max = preview.scrollHeight - preview.clientHeight
    if (max > 0) preview.scrollTop = scrollRatio(editor) * max
  })
}

function onWindowResize() {
  if (wordPreview.value) syncPreviewTop()
}

onMounted(() => window.addEventListener('resize', onWindowResize))
onBeforeUnmount(() => {
  window.removeEventListener('resize', onWindowResize)
  if (prefsPreviewTimer !== null) window.clearTimeout(prefsPreviewTimer)
})

async function toggleWordPreview() {
  if (wordPreview.value) {
    wordPreview.value = false
    return
  }
  await autosave.flushNow()
  wordPreview.value = true
  wordPreviewVersion.value += 1
  await nextTick()
  syncPreviewTop()
}

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

watch([readMode, editorMode], () => {
  wordPreview.value = false
})

async function refresh() {
  refreshing.value = true
  try {
    const fresh = await notes.refreshLink(props.note.id)
    const meta = (fresh.props_json?.link as Partial<LinkMeta>) ?? {}
    if (meta.fetch_status === 'ok') {
      body.value = fresh.body_md || body.value
      toast.success('已重新抓取正文')
    } else {
      toast.info('仍然无法抓取，已保留现有内容')
    }
  } catch (e: any) {
    toast.error(e.message || '重新抓取失败')
  } finally {
    refreshing.value = false
  }
}

const openUrl = computed(() => link.value.final_url || link.value.url || '')
</script>

<template>
  <div class="h-full flex flex-col">
    <header class="shrink-0 h-11 flex items-center gap-2 px-4 border-b border-slate-200/50 bg-white/40">
      <NoteTitleBreadcrumb
        v-model:title="title"
        :note-id="note.id"
        :emoji="note.props_json?.emoji"
        kind="link"
        :folder-id="note.folder_id"
        placeholder="链接标题"
        @input="autosave.schedule()"
      />
      <div class="flex-1" />
      <span class="text-[10px] text-slate-400">
        <template v-if="autosave.saving.value">保存中…</template>
        <template v-else-if="autosave.savedAt.value">已保存 {{ autosave.savedAt.value }}</template>
      </span>
      <NoteTagButton :note="note" />
      <template v-if="!readMode">
        <button
          class="kiwi-btn-ghost !py-1 !px-2 !text-[11px]"
          :disabled="refreshing"
          @click="refresh"
        >
          <KiwiIcon name="refresh" :size="12" :spin="refreshing" />
          重新抓取
        </button>
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
          class="kiwi-btn-ghost !py-1 !px-2 !text-[11px]"
          :class="showOutline ? 'bg-kiwi-50 text-kiwi-700' : ''"
          :title="showOutline ? '隐藏文档目录' : '显示文档目录'"
          @click="showOutline = !showOutline"
        >
          <KiwiIcon name="listTree" :size="13" />
          目录
        </button>
        <button
          type="button"
          class="kiwi-btn-ghost !py-1 !px-2 !text-[11px]"
          :class="showPageSettings ? 'bg-kiwi-50 text-kiwi-700' : ''"
          title="页面设置"
          @click="showPageSettings = !showPageSettings"
        >
          <KiwiIcon name="settings" :size="13" />
          页面设置
        </button>
        <EditorModeMenu :mode="editorMode" @change="setEditorMode" />
      </template>
      <button
        class="kiwi-btn-ghost !py-1 !px-2 !text-[11px]"
        :title="readMode ? '切换到编辑' : '切换到阅读'"
        @click="toggleMode"
      >
        <KiwiIcon :name="readMode ? 'edit' : 'bookOpen'" :size="13" />
        {{ readMode ? '编辑' : '阅读' }}
      </button>
    </header>

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
          <KiwiEditor
            :key="editorMode"
            ref="editorRef"
            class="flex-1"
            :content="body"
            :note-id="note.id"
            :readonly="readMode"
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
              <!-- 书签卡片 -->
              <div class="relative overflow-hidden rounded-2xl border border-slate-200/70 bg-gradient-to-br from-white/90 to-kiwi-50/60 p-4 shadow-soft">
                <div class="flex items-start gap-3">
                  <div class="w-9 h-9 shrink-0 rounded-xl bg-white border border-slate-200/70 grid place-items-center overflow-hidden">
                    <img
                      v-if="link.favicon && !faviconBroken"
                      :src="link.favicon"
                      class="w-5 h-5"
                      alt=""
                      referrerpolicy="no-referrer"
                      @error="faviconBroken = true"
                    />
                    <KiwiIcon v-else name="link2" :size="15" class="text-sky-500" />
                  </div>
                  <div class="min-w-0 flex-1">
                    <div class="flex items-center gap-2">
                      <span class="text-[11px] font-medium text-slate-500 truncate">
                        {{ link.site || '外部链接' }}
                      </span>
                      <span
                        v-if="failed"
                        class="shrink-0 rounded-md border border-amber-200 bg-amber-50 px-1.5 py-0.5 text-[9.5px] text-amber-600"
                      >
                        仅书签
                      </span>
                    </div>
                    <a
                      v-if="openUrl"
                      :href="openUrl"
                      target="_blank"
                      rel="noopener noreferrer"
                      class="mt-0.5 inline-flex items-center gap-1 text-[13px] font-medium text-slate-700 hover:text-kiwi-700 transition-colors"
                    >
                      <span class="truncate">{{ title || link.url || '外部链接' }}</span>
                      <KiwiIcon name="external" :size="11" class="shrink-0 text-slate-400" />
                    </a>
                    <p v-if="openUrl" class="mt-0.5 text-[10.5px] text-slate-400 truncate">{{ openUrl }}</p>
                  </div>
                </div>
                <p
                  v-if="link.excerpt && !hasBody"
                  class="mt-3 text-[12px] leading-relaxed text-slate-500 line-clamp-3"
                >
                  {{ link.excerpt }}
                </p>
                <p v-if="failed" class="mt-2 flex items-start gap-1.5 text-[11px] leading-relaxed text-amber-600">
                  <KiwiIcon name="alert" :size="12" class="mt-0.5 shrink-0" />
                  {{ link.fetch_error || '网页抓取失败，可以稍后重试，或直接在下方记录内容。' }}
                </p>
              </div>

              <div class="mt-6 flex items-center gap-1.5">
                <NoteEmojiButton
                  v-if="!readMode"
                  :note-id="note.id"
                  :emoji="note.props_json?.emoji"
                  kind="link"
                  :size="20"
                />
                <span
                  v-else-if="note.props_json?.emoji"
                  class="w-9 shrink-0 text-center text-[22px] leading-none"
                >{{ note.props_json.emoji }}</span>
                <h1
                  v-if="readMode"
                  class="min-w-0 flex-1 text-[24px] leading-tight font-semibold text-slate-800"
                >
                  {{ title || '链接标题' }}
                </h1>
                <input
                  v-else
                  v-model="title"
                  class="min-w-0 flex-1 bg-transparent text-[24px] leading-tight font-semibold text-slate-800 outline-none placeholder:text-slate-300"
                  placeholder="链接标题"
                  @input="autosave.schedule()"
                />
              </div>

              <div
                v-if="readMode && !hasBody"
                class="mt-5 rounded-xl border border-dashed border-slate-200 px-4 py-10 text-center"
              >
                <KiwiIcon name="file" :size="22" class="mx-auto text-slate-300" />
                <p class="mt-2 text-[12px] text-slate-400">没有抓取到正文</p>
                <p class="mt-0.5 text-[11px] text-slate-300">可点击“编辑”手动补充摘要或笔记</p>
              </div>
            </template>
          </KiwiEditor>
        </div>
      </div>

      <!-- DOCX 模式：右侧 Word 导出预览，与正文纸张顶部对齐 -->
      <div
        v-if="wordPreview && !readMode && editorMode === 'docx'"
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

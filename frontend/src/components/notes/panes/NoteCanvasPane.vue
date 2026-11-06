<script setup lang="ts">
/** 画布笔记：jvs-draw 拖拽式白板，文档保存在 props_json.draw_doc。 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useNotesStore, type NoteOut } from '@/stores/notes'
import { useAutosave } from '@/composables/useAutosave'
import { useSaveShortcut } from '@/composables/useSaveShortcut'
import { uploadAttachment } from '@/api/attachments'
import NoteTitleBreadcrumb from '@/components/notes/NoteTitleBreadcrumb.vue'
import NoteTagButton from '@/components/notes/NoteTagButton.vue'
import KiwiIcon from '@/components/ui/KiwiIcon.vue'
import DrawEditor from '@/components/draw/DrawEditor.vue'
import DrawSettings from '@/components/draw/DrawSettings.vue'
import { drawDocToSvg } from '@/components/draw/drawSvgExport'
import {
  DRAW_PREFERENCE_DEFAULTS,
  drawDocHasContent,
  emptyDrawDoc,
  readDrawDoc,
  type DrawPreferences,
  type JvsDrawDoc,
} from '@/components/draw/types'

const props = withDefaults(
  defineProps<{
    note: NoteOut
    /** 是否为活动窗口：Ctrl/⌘+S 只保存活动窗口，非活动栏只展示静态预览。 */
    active?: boolean
  }>(),
  { active: true },
)
const notes = useNotesStore()

const title = ref(props.note.title)
const doc = ref<JvsDrawDoc>(readDrawDoc(props.note.props_json) ?? emptyDrawDoc())
const drawRef = ref<any>(null)
const showPrefs = ref(false)
const prefs = ref<DrawPreferences>(DRAW_PREFERENCE_DEFAULTS)

const autosave = useAutosave(async () => {
  await notes.updateNote(props.note.id, {
    title: title.value.trim() || '无标题画布',
    props_json: { draw_doc: doc.value },
  })
})

useSaveShortcut(
  () => autosave.flushNow(),
  () => props.active,
)

function onTitleInput() {
  autosave.schedule()
}

function onDrawUpdate(next: JvsDrawDoc) {
  doc.value = next
  autosave.schedule()
}

/** 白板挂载完成后同步一次偏好，避免面板显示默认值。 */
function syncPrefs() {
  const instance = drawRef.value
  if (typeof instance?.getPreferences === 'function') {
    prefs.value = instance.getPreferences()
  }
}

function onPrefsUpdate(patch: Partial<DrawPreferences>) {
  prefs.value = { ...prefs.value, ...patch }
  drawRef.value?.setPreferences?.(patch)
}

async function uploadImage(file: File): Promise<string> {
  const att = await uploadAttachment(file, props.note.id, props.note.kb_id)
  return att.url
}

const previewSvg = computed(() => {
  if (!drawDocHasContent(doc.value)) return ''
  try {
    return drawDocToSvg(doc.value)
  } catch {
    return ''
  }
})

/** 失活前先把白板内容刷回文档，再卸载重型运行时。 */
watch(
  () => props.active,
  (active, previous) => {
    if (previous && !active) {
      drawRef.value?.flush?.()
      showPrefs.value = false
    }
  },
)

/**
 * 画布笔记的 Ctrl/⌘+F 打开 jvs-draw 的图形 / 文字搜索；
 * 在捕获阶段处理并 preventDefault，工作区的文本页内查找会自动让位。
 */
function onCanvasFindKey(event: KeyboardEvent) {
  if (!props.active || event.defaultPrevented) return
  if (!(event.ctrlKey || event.metaKey) || event.altKey || event.shiftKey) return
  if (event.key.toLowerCase() !== 'f') return
  event.preventDefault()
  drawRef.value?.openSearch?.()
}

onMounted(() => window.addEventListener('keydown', onCanvasFindKey, true))
onBeforeUnmount(() => window.removeEventListener('keydown', onCanvasFindKey, true))

/** 外部重命名（目录树 / 其他入口）同步到标题。 */
watch(
  () => props.note.title,
  (value) => {
    if (value !== title.value && !autosave.saving.value) title.value = value
  },
)
</script>

<template>
  <div class="h-full flex flex-col">
    <header class="shrink-0 h-11 flex items-center gap-2 px-4 border-b border-slate-200/50 bg-white/40">
      <NoteTitleBreadcrumb
        v-model:title="title"
        :note-id="note.id"
        :emoji="note.props_json?.emoji"
        kind="canvas"
        :folder-id="note.folder_id"
        placeholder="无标题画布"
        @input="onTitleInput"
      />
      <span
        class="shrink-0 rounded-md border border-violet-100 bg-violet-50 px-1.5 py-0.5 text-[10px] text-violet-500"
      >
        画布
      </span>
      <template v-if="active">
        <button
          type="button"
          class="inline-flex shrink-0 items-center justify-center rounded-lg p-1.5 text-slate-400 transition-colors hover:bg-kiwi-50 hover:text-kiwi-700"
          title="模板库"
          aria-label="模板库"
          @click="drawRef?.openTemplates?.()"
        >
          <KiwiIcon name="layoutTemplate" :size="13" />
        </button>
        <button
          type="button"
          class="inline-flex shrink-0 items-center justify-center rounded-lg p-1.5 text-slate-400 transition-colors hover:bg-kiwi-50 hover:text-kiwi-700"
          title="信息图"
          aria-label="信息图"
          @click="drawRef?.openInfographic?.()"
        >
          <KiwiIcon name="infographic" :size="13" />
        </button>
      </template>
      <div class="flex-1" />
      <span class="text-[10px] text-slate-400 tabular-nums">
        <template v-if="autosave.saving.value">
          <KiwiIcon name="loader" :size="10" spin class="inline -mt-px mr-1" />保存中…
        </template>
        <template v-else-if="autosave.savedAt.value">已保存 {{ autosave.savedAt.value }}</template>
        <template v-else>自动保存</template>
      </span>
      <NoteTagButton :note="note" />
      <button
        v-if="active"
        type="button"
        class="kiwi-btn-ghost shrink-0 whitespace-nowrap !px-2 !py-1 !text-[11px]"
        :class="showPrefs ? 'bg-kiwi-50 text-kiwi-700' : ''"
        title="画布偏好设置"
        @click="showPrefs = !showPrefs"
      >
        <KiwiIcon name="settings" :size="13" />
        偏好设置
      </button>
    </header>

    <div class="flex min-h-0 flex-1">
      <DrawEditor
        v-if="active"
        ref="drawRef"
        :key="note.id"
        class="min-h-0 flex-1"
        :model-value="doc"
        :upload="uploadImage"
        @ready="syncPrefs"
        @update:model-value="onDrawUpdate"
      />
      <div v-else class="min-h-0 flex-1 overflow-auto bg-slate-50/60 p-6">
        <div v-if="previewSvg" class="canvas-preview mx-auto max-w-full" v-html="previewSvg" />
        <div v-else class="flex h-full flex-col items-center justify-center gap-2 text-slate-400">
          <KiwiIcon name="pen" :size="22" />
          <span class="text-[12px]">画布在后台运行，点击该栏继续编辑</span>
        </div>
      </div>
      <DrawSettings
        v-if="active && showPrefs"
        :prefs="prefs"
        docked
        @update="onPrefsUpdate"
        @close="showPrefs = false"
      />
    </div>
  </div>
</template>

<style scoped>
:deep(.kiwi-draw-view) {
  background: #fff;
}

.canvas-preview :deep(svg) {
  display: block;
  width: 100%;
  height: auto;
}
</style>

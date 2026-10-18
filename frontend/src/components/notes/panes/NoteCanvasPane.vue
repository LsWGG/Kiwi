<script setup lang="ts">
/** 画布笔记：工程图 / 思维导图 / 主题 / 模板 / 智能连线，画布内容保存在 props_json.canvas_doc。 */
import { ref, watch } from 'vue'
import { useNotesStore, type NoteOut } from '@/stores/notes'
import { useAutosave } from '@/composables/useAutosave'
import { useSaveShortcut } from '@/composables/useSaveShortcut'
import NoteTitleBreadcrumb from '@/components/notes/NoteTitleBreadcrumb.vue'
import NoteTagButton from '@/components/notes/NoteTagButton.vue'
import KiwiIcon from '@/components/ui/KiwiIcon.vue'
import CanvasStage from '@/components/notes/canvas/CanvasStage.vue'
import { normalizeDoc, type CanvasDoc } from '@/components/notes/canvas/types'

const props = defineProps<{ note: NoteOut }>()
const notes = useNotesStore()

const title = ref(props.note.title)
const doc = ref<CanvasDoc>(normalizeDoc(props.note.props_json?.canvas_doc))

const autosave = useAutosave(async () => {
  await notes.updateNote(props.note.id, {
    title: title.value.trim() || '无标题画布',
    props_json: { canvas_doc: doc.value },
  })
})

useSaveShortcut(() => autosave.flushNow())

function onTitleInput() {
  autosave.schedule()
}

function onCanvasChange() {
  autosave.schedule()
}

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
      <div class="flex-1" />
      <span class="text-[10px] text-slate-400 tabular-nums">
        <template v-if="autosave.saving.value">
          <KiwiIcon name="loader" :size="10" spin class="inline -mt-px mr-1" />保存中…
        </template>
        <template v-else-if="autosave.savedAt.value">已保存 {{ autosave.savedAt.value }}</template>
        <template v-else>自动保存</template>
      </span>
      <NoteTagButton :note="note" />
    </header>

    <CanvasStage v-model="doc" class="min-h-0 flex-1" @change="onCanvasChange" />
  </div>
</template>

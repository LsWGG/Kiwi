<script setup lang="ts">
/** 按笔记类型渲染对应面板；单篇视图与分栏窗口共用。 */
import type { NoteOut } from '@/stores/notes'
import NoteLockGate from '@/components/notes/NoteLockGate.vue'
import NoteDocPane from '@/components/notes/panes/NoteDocPane.vue'
import NoteLinkPane from '@/components/notes/panes/NoteLinkPane.vue'
import NoteDatabasePane from '@/components/notes/panes/NoteDatabasePane.vue'
import NoteCanvasPane from '@/components/notes/panes/NoteCanvasPane.vue'
import NoteNotebookPane from '@/components/notes/panes/NoteNotebookPane.vue'
import NoteSheetPane from '@/components/notes/panes/NoteSheetPane.vue'

withDefaults(
  defineProps<{
    note: NoteOut
    /** 位于分栏窗口内：隐藏「分栏」入口，避免嵌套。 */
    inPane?: boolean
    /** 是否为活动窗口：决定 Ctrl/⌘+S 的响应者。 */
    active?: boolean
  }>(),
  { inPane: false, active: true },
)

const emit = defineEmits<{
  (e: 'open-info'): void
  (e: 'open-backlink', noteId: string, mentionId?: string): void
  (e: 'open-note', noteId: string): void
  (e: 'unlocked'): void
}>()
</script>

<template>
  <NoteLockGate
    v-if="note.is_locked && !note.unlocked"
    :key="`lock-${note.id}`"
    :note="note"
    @unlocked="emit('unlocked')"
  />
  <NoteDocPane
    v-else-if="note.kind === 'doc' || note.kind === 'import'"
    :key="note.id"
    :note="note"
    :in-pane="inPane"
    :active="active"
    @open-info="emit('open-info')"
    @open-backlink="(noteId, mentionId) => emit('open-backlink', noteId, mentionId)"
  />
  <NoteLinkPane
    v-else-if="note.kind === 'link'"
    :key="note.id"
    :note="note"
    :active="active"
  />
  <NoteDatabasePane
    v-else-if="note.kind === 'database'"
    :key="note.id"
    :note="note"
    @open-note="(noteId) => emit('open-note', noteId)"
  />
  <NoteCanvasPane
    v-else-if="note.kind === 'canvas'"
    :key="note.id"
    :note="note"
    :active="active"
  />
  <NoteNotebookPane
    v-else-if="note.kind === 'notebook'"
    :key="note.id"
    :note="note"
    :active="active"
  />
  <NoteSheetPane
    v-else-if="note.kind === 'sheet'"
    :key="note.id"
    :note="note"
    :active="active"
  />
</template>

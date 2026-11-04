<script setup lang="ts">
/**
 * 分栏工作区：顶部布局工具条 + 停靠式多窗口 + 活动窗口页内查找。
 *
 * 布局状态全部在 notePanes store 中；本组件只负责渲染、命中活动窗口
 * 的查找范围，并把关闭 / 退出的路由决策交回工作区视图。
 */
import { nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { useNotePanesStore } from '@/stores/notePanes'
import { useNoteFindStore } from '@/stores/noteFind'
import { useNotesStore } from '@/stores/notes'
import KiwiIcon from '@/components/ui/KiwiIcon.vue'
import NoteFindBar from '@/components/notes/NoteFindBar.vue'
import PaneSplit from './PaneSplit.vue'
import type { PanePreset } from './paneLayout'
import { toast } from '@/components/ui/toast'

const emit = defineEmits<{
  (e: 'close-pane', paneId: string): void
  (e: 'open-info'): void
  (e: 'open-backlink', noteId: string, mentionId?: string): void
  (e: 'open-note', noteId: string): void
  (e: 'exit'): void
}>()

const panes = useNotePanesStore()
const notes = useNotesStore()
const noteFind = useNoteFindStore()

const rootRef = ref<HTMLElement | null>(null)
const findScope = ref<HTMLElement | null>(null)

function activeNoteId(): string | null {
  const target = panes.activeTarget
  return target && target.kind === 'note' ? target.noteId : null
}

/** 活动窗口切换后重新定位查找范围；新窗口不是同一篇笔记时收起查找。 */
async function syncFindScope() {
  await nextTick()
  const id = panes.activePaneId
  findScope.value = id
    ? (rootRef.value?.querySelector<HTMLElement>(
        `[data-pane-id="${id}"] .pane-find-scope`,
      ) ?? null)
    : null
  if (noteFind.open && noteFind.noteId !== activeNoteId()) noteFind.close()
}

watch(
  [() => panes.activePaneId, () => panes.root],
  () => void syncFindScope(),
  { flush: 'post' },
)

/** 打开页内查找：有选区时以选中文字作为初始关键词。 */
function showFind() {
  const noteId = activeNoteId()
  if (!noteId) {
    toast.info('请先激活一个笔记窗口再查找')
    return
  }
  const note = notes.noteCache[noteId]
  if (note?.is_locked && !note.unlocked) return
  if (noteFind.open) {
    noteFind.show('', noteId)
    return
  }
  let seed = ''
  const selection = window.getSelection()
  const scope = findScope.value
  if (selection && !selection.isCollapsed && scope && selection.anchorNode) {
    if (scope.contains(selection.anchorNode)) {
      seed = selection.toString().replace(/\s+/g, ' ').trim().slice(0, 80)
    }
  }
  noteFind.show(seed, noteId)
}

function closeActivePane() {
  if (panes.activePaneId) emit('close-pane', panes.activePaneId)
}

function applyPreset(preset: PanePreset) {
  if (panes.count < 2) return
  panes.applyPreset(preset)
}

onBeforeUnmount(() => {
  noteFind.close()
})

defineExpose({ showFind, closeActivePane })
</script>

<template>
  <div
    ref="rootRef"
    class="relative h-full min-h-0 flex flex-col overflow-hidden bg-slate-100/70"
  >
    <div
      class="shrink-0 flex h-9 items-center gap-1 border-b border-slate-200/70 bg-white/80 px-2 backdrop-blur"
      data-find-skip
    >
      <KiwiIcon name="columns" :size="13" class="text-kiwi-500" />
      <span class="text-[11.5px] font-medium text-slate-600">分栏</span>
      <span class="rounded bg-slate-100 px-1.5 py-0.5 text-[10px] tabular-nums text-slate-400">
        {{ panes.count }} 栏
      </span>
      <div class="flex-1" />
      <button
        type="button"
        class="rounded-md px-2 py-1 text-[11px] text-slate-500 transition-colors hover:bg-white hover:text-kiwi-700 disabled:pointer-events-none disabled:opacity-40"
        title="左右平铺所有窗口"
        :disabled="panes.count < 2"
        @click="applyPreset('row')"
      >
        左右排列
      </button>
      <button
        type="button"
        class="rounded-md px-2 py-1 text-[11px] text-slate-500 transition-colors hover:bg-white hover:text-kiwi-700 disabled:pointer-events-none disabled:opacity-40"
        title="上下平铺所有窗口"
        :disabled="panes.count < 2"
        @click="applyPreset('column')"
      >
        上下排列
      </button>
      <button
        type="button"
        class="rounded-md px-2 py-1 text-[11px] text-slate-500 transition-colors hover:bg-white hover:text-kiwi-700 disabled:pointer-events-none disabled:opacity-40"
        title="两列网格，超过 2 栏时按行排列"
        :disabled="panes.count < 2"
        @click="applyPreset('grid')"
      >
        网格
      </button>
      <span class="mx-1 h-4 w-px bg-slate-200" />
      <button
        type="button"
        class="inline-flex items-center gap-1 rounded-md px-2 py-1 text-[11px] text-slate-500 transition-colors hover:bg-rose-50 hover:text-rose-600"
        title="退出分栏，回到单篇视图"
        @click="emit('exit')"
      >
        <KiwiIcon name="layoutTemplate" :size="12" />
        退出分栏
      </button>
    </div>

    <div class="flex-1 min-h-0">
      <PaneSplit
        v-if="panes.root"
        :node="panes.root"
        :active-pane-id="panes.activePaneId"
        @close-pane="(id) => emit('close-pane', id)"
        @open-info="emit('open-info')"
        @open-backlink="(id, mentionId) => emit('open-backlink', id, mentionId)"
        @open-note="(id) => emit('open-note', id)"
      />
      <div v-else class="h-full grid place-items-center">
        <div class="text-center">
          <KiwiIcon name="columns" :size="28" class="mx-auto text-slate-300" />
          <p class="mt-2 text-[12.5px] text-slate-500">从左侧目录选择一篇笔记开始分栏</p>
        </div>
      </div>
    </div>

    <NoteFindBar :scope="findScope" />
  </div>
</template>

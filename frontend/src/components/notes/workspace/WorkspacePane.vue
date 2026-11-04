<script setup lang="ts">
/** 分栏中的单个窗口：标题栏拖动停靠 + 活动态 + 按 target 渲染内容。 */
import { computed, onBeforeUnmount, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useNotesStore } from '@/stores/notes'
import { useNotePanesStore } from '@/stores/notePanes'
import KiwiIcon from '@/components/ui/KiwiIcon.vue'
import PaneNoteHost from './PaneNoteHost.vue'
import PaneWebView from './PaneWebView.vue'
import PaneFileView from './PaneFileView.vue'
import type { DockZone, PaneLeaf } from './paneLayout'

const props = defineProps<{
  pane: PaneLeaf
  active: boolean
}>()

const emit = defineEmits<{
  (e: 'close', paneId: string): void
  (e: 'open-info'): void
  (e: 'open-backlink', noteId: string, mentionId?: string): void
  (e: 'open-note', noteId: string): void
}>()

const route = useRoute()
const router = useRouter()
const notes = useNotesStore()
const panes = useNotePanesStore()

const target = computed(() => props.pane.target)
const summary = computed(() => {
  const value = target.value
  return value.kind === 'note'
    ? notes.notes.find((note) => note.id === value.noteId)
    : null
})
const title = computed(() => {
  const value = target.value
  if (value.kind === 'note') {
    return summary.value?.title || notes.noteCache[value.noteId]?.title || '笔记'
  }
  if (value.kind === 'url') return value.title || hostOf(value.url)
  return value.filename
})
const icon = computed(() => {
  const value = target.value
  if (value.kind === 'url') return 'globe'
  if (value.kind === 'file') return 'paperclip'
  switch (summary.value?.kind) {
    case 'database':
      return 'database'
    case 'canvas':
      return 'pen'
    case 'notebook':
      return 'notebook'
    case 'sheet':
      return 'table'
    case 'link':
      return 'link2'
    default:
      return 'fileText'
  }
})
const subtitle = computed(() => {
  const value = target.value
  if (value.kind === 'url') return value.site || hostOf(value.url)
  if (value.kind === 'file') {
    const ext = value.filename.match(/\.([a-z0-9]+)$/i)?.[1]?.toUpperCase()
    return ext || value.contentType
  }
  return ''
})

function hostOf(url: string): string {
  try {
    return new URL(url, window.location.origin).host
  } catch {
    return ''
  }
}

function focus() {
  if (panes.activePaneId !== props.pane.id) panes.activate(props.pane.id)
  if (target.value.kind !== 'note') return
  if (route.params.id === target.value.noteId) return
  void router.replace({
    name: 'notes',
    params: { id: target.value.noteId },
    query: {},
  })
}

/* ---------- 拖动标题栏停靠 ---------- */
const dragging = ref(false)
const dragMoved = ref(false)
const ghost = ref({ x: 0, y: 0 })
let dragPointerId = -1
let startX = 0
let startY = 0

const hint = computed<DockZone | null>(() => {
  const value = panes.dropHint
  return value && value.paneId === props.pane.id ? value.zone : null
})

const hintClass = computed(() => {
  switch (hint.value) {
    case 'left':
      return 'inset-y-0 left-0 w-1/2'
    case 'right':
      return 'inset-y-0 right-0 w-1/2'
    case 'top':
      return 'inset-x-0 top-0 h-1/2'
    case 'bottom':
      return 'inset-x-0 bottom-0 h-1/2'
    default:
      return 'inset-0'
  }
})

function zoneAt(x: number, y: number): { paneId: string; zone: DockZone } | null {
  const hit = document.elementFromPoint(x, y) as HTMLElement | null
  const paneEl = hit?.closest<HTMLElement>('[data-pane-id]')
  const paneId = paneEl?.dataset.paneId
  if (!paneEl || !paneId || paneId === props.pane.id) return null
  const rect = paneEl.getBoundingClientRect()
  if (rect.width <= 0 || rect.height <= 0) return null
  const rx = (x - rect.left) / rect.width
  const ry = (y - rect.top) / rect.height
  const edge = 0.22
  let zone: DockZone = 'center'
  if (rx < edge) zone = 'left'
  else if (rx > 1 - edge) zone = 'right'
  else if (ry < edge) zone = 'top'
  else if (ry > 1 - edge) zone = 'bottom'
  return { paneId, zone }
}

function onDragMove(event: PointerEvent) {
  if (event.pointerId !== dragPointerId) return
  const dx = event.clientX - startX
  const dy = event.clientY - startY
  if (!dragMoved.value && Math.hypot(dx, dy) < 5) return
  if (!dragMoved.value) {
    dragMoved.value = true
    dragging.value = true
    panes.beginDrag(props.pane.id)
  }
  ghost.value = { x: event.clientX + 10, y: event.clientY + 10 }
  const hit = zoneAt(event.clientX, event.clientY)
  if (hit) panes.setDropHint(hit.paneId, hit.zone)
  else panes.setDropHint(null)
  event.preventDefault()
}

function stopDrag(event?: PointerEvent) {
  if (event && event.pointerId !== dragPointerId) return
  const moved = dragMoved.value
  const drop = panes.dropHint
  window.removeEventListener('pointermove', onDragMove)
  window.removeEventListener('pointerup', stopDrag)
  window.removeEventListener('pointercancel', stopDrag)
  dragPointerId = -1
  dragging.value = false
  dragMoved.value = false
  panes.endDrag()
  if (moved && drop) {
    panes.movePane(props.pane.id, drop.paneId, drop.zone)
  }
}

function startDrag(event: PointerEvent) {
  if (event.button !== 0) return
  dragPointerId = event.pointerId
  startX = event.clientX
  startY = event.clientY
  dragMoved.value = false
  const handle = event.currentTarget as HTMLElement
  handle.setPointerCapture(event.pointerId)
  window.addEventListener('pointermove', onDragMove)
  window.addEventListener('pointerup', stopDrag)
  window.addEventListener('pointercancel', stopDrag)
}

onBeforeUnmount(() => {
  window.removeEventListener('pointermove', onDragMove)
  window.removeEventListener('pointerup', stopDrag)
  window.removeEventListener('pointercancel', stopDrag)
})
</script>

<template>
  <article
    class="relative flex h-full w-full min-h-0 min-w-0 flex-col overflow-hidden bg-white"
    :class="active ? 'ring-1 ring-inset ring-kiwi-400/70' : ''"
    :data-pane-id="pane.id"
    @pointerdown.capture="focus"
  >
    <header
      class="shrink-0 flex h-8 items-center gap-1 border-b border-slate-200/70 bg-white/85 px-1.5 backdrop-blur select-none"
      data-pane-header
      data-find-skip
    >
      <button
        type="button"
        class="grid h-5 w-5 shrink-0 cursor-grab place-items-center rounded text-slate-300 transition-colors hover:bg-slate-100 hover:text-slate-500 active:cursor-grabbing"
        title="拖动到其他窗口边缘以重新排列"
        @pointerdown.prevent.stop="startDrag"
      >
        <KiwiIcon name="grip" :size="13" />
      </button>
      <KiwiIcon :name="icon" :size="12" class="shrink-0 text-slate-400" />
      <span class="min-w-0 truncate text-[11px] font-medium text-slate-600" :title="title">
        {{ title }}
      </span>
      <span v-if="subtitle" class="min-w-0 shrink truncate text-[10px] text-slate-400">
        {{ subtitle }}
      </span>
      <div class="flex-1" />
      <button
        type="button"
        class="grid h-5 w-5 shrink-0 place-items-center rounded text-slate-300 transition-colors hover:bg-rose-50 hover:text-rose-500"
        title="关闭这一栏"
        @click.stop="emit('close', pane.id)"
      >
        <KiwiIcon name="close" :size="12" />
      </button>
    </header>

    <div class="relative flex-1 min-h-0 overflow-hidden pane-find-scope">
      <PaneNoteHost
        v-if="target.kind === 'note'"
        :note-id="target.noteId"
        :kb-id="target.kbId"
        :active="active"
        @open-info="$emit('open-info')"
        @open-backlink="(id, mentionId) => $emit('open-backlink', id, mentionId)"
        @open-note="(id) => $emit('open-note', id)"
      />
      <PaneWebView
        v-else-if="target.kind === 'url'"
        :url="target.url"
        :title="target.title"
        :site="target.site"
      />
      <PaneFileView
        v-else
        :url="target.url"
        :filename="target.filename"
        :content-type="target.contentType"
        :size="target.size"
      />
    </div>

    <!-- 拖动停靠时的目标区域预览 -->
    <div v-if="hint" class="pointer-events-none absolute inset-0 z-30">
      <div
        class="absolute bg-kiwi-400/15 ring-2 ring-inset ring-kiwi-400/70 transition-all"
        :class="hintClass"
      />
    </div>
  </article>

  <!-- body 上有 --ui-scale zoom，坐标按视口像素计算；内层单独缩放保持视觉比例。 -->
  <Teleport to="html">
    <div
      v-if="dragging"
      class="pane-drag-ghost pointer-events-none fixed z-[120]"
      :style="{ left: `${ghost.x}px`, top: `${ghost.y}px` }"
    >
      <div
        class="max-w-[240px] truncate rounded-lg border border-kiwi-300 bg-white/95 px-2.5 py-1.5 text-[11.5px] font-medium text-kiwi-700 shadow-lifted"
        :style="{ zoom: 'var(--ui-scale)' }"
      >
        {{ title }}
      </div>
    </div>
  </Teleport>
</template>

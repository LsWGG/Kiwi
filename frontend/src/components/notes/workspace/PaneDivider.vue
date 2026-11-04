<script setup lang="ts">
/** 分栏分隔条：拖动调整相邻两栏比例，双击恢复均分。 */
import { ref } from 'vue'
import { useNotePanesStore } from '@/stores/notePanes'
import { MIN_PANE_PX, findSplit } from './paneLayout'

const props = defineProps<{
  splitId: string
  index: number
  direction: 'row' | 'column'
}>()

const panes = useNotePanesStore()
const dragging = ref(false)

let startPos = 0
let startSizes: number[] = []
let containerSize = 0
let pointerId = -1

function readContainerSize(el: HTMLElement): number {
  const parent = el.parentElement
  if (!parent) return 0
  const rect = parent.getBoundingClientRect()
  return props.direction === 'row' ? rect.width : rect.height
}

function onPointerDown(event: PointerEvent) {
  if (event.button !== 0) return
  const split = findSplit(panes.root, props.splitId)
  const el = event.currentTarget as HTMLElement
  containerSize = readContainerSize(el)
  if (!split || containerSize <= 0) return
  startSizes = [...split.sizes]
  startPos = props.direction === 'row' ? event.clientX : event.clientY
  pointerId = event.pointerId
  dragging.value = true
  el.setPointerCapture(event.pointerId)
  window.addEventListener('pointermove', onPointerMove)
  window.addEventListener('pointerup', stopDrag)
  window.addEventListener('pointercancel', stopDrag)
  event.preventDefault()
}

function onPointerMove(event: PointerEvent) {
  if (!dragging.value || event.pointerId !== pointerId || !startSizes.length) return
  const client = props.direction === 'row' ? event.clientX : event.clientY
  const delta = ((client - startPos) / containerSize) * 100
  const minPct = Math.max(8, (MIN_PANE_PX / containerSize) * 100)
  const a = startSizes[props.index]
  const b = startSizes[props.index + 1]
  if (a === undefined || b === undefined) return
  const total = a + b
  let nextA = a + delta
  let nextB = b - delta
  if (nextA < minPct) {
    nextA = minPct
    nextB = total - minPct
  } else if (nextB < minPct) {
    nextB = minPct
    nextA = total - minPct
  }
  const sizes = [...startSizes]
  sizes[props.index] = nextA
  sizes[props.index + 1] = nextB
  panes.setSplitSizes(props.splitId, sizes)
}

function stopDrag() {
  if (!dragging.value) return
  dragging.value = false
  pointerId = -1
  startSizes = []
  window.removeEventListener('pointermove', onPointerMove)
  window.removeEventListener('pointerup', stopDrag)
  window.removeEventListener('pointercancel', stopDrag)
}

function resetSizes() {
  panes.resetSplitSizes(props.splitId)
}
</script>

<template>
  <div
    class="group relative z-10 shrink-0 bg-slate-200/50 transition-colors hover:bg-kiwi-300/50"
    :class="[
      direction === 'row' ? 'w-1.5 cursor-col-resize' : 'h-1.5 cursor-row-resize',
      dragging ? 'bg-kiwi-400/60' : '',
    ]"
    role="separator"
    :aria-orientation="direction === 'row' ? 'vertical' : 'horizontal'"
    title="拖动调整栏宽，双击恢复均分"
    @pointerdown="onPointerDown"
    @dblclick="resetSizes"
  >
    <div
      class="absolute bg-slate-300/80 transition-colors group-hover:bg-kiwi-500"
      :class="
        direction === 'row'
          ? 'inset-y-0 left-1/2 w-px -translate-x-1/2'
          : 'inset-x-0 top-1/2 h-px -translate-y-1/2'
      "
    />
  </div>
</template>

<script setup lang="ts">
/** 日期胶囊：点击在胶囊正下方弹出统一月历面板，就地选择日期。 */
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { NodeViewWrapper, nodeViewProps } from '@tiptap/vue-3'
import KiwiCalendarPanel from '@/components/ui/KiwiCalendarPanel.vue'
import { useEditorEditable } from './useEditorEditable'

const props = defineProps(nodeViewProps)

const root = ref<HTMLElement | null>(null)
const pop = ref<HTMLElement | null>(null)
const editable = useEditorEditable(props.editor)
const editing = ref(false)

const POP_WIDTH = 264
const POP_HEIGHT = 336

const popStyle = ref<Record<string, string>>({})

function uiScale(): number {
  const raw = getComputedStyle(document.documentElement).getPropertyValue('--ui-scale')
  const value = Number.parseFloat(raw)
  return Number.isFinite(value) && value > 0 ? value : 1
}

function placePopover() {
  const chip = (root.value as unknown as { $el?: HTMLElement })?.$el
  const anchor = chip?.querySelector?.<HTMLElement>('.kiwi-date-chip') ?? chip
  if (!anchor) return
  const rect = anchor.getBoundingClientRect()
  // 面板内部按 --ui-scale 缩放，视口占位也要换算成缩放后的尺寸。
  const scale = uiScale()
  const width = POP_WIDTH * scale
  const height = POP_HEIGHT * scale
  const left = Math.min(
    Math.max(8, rect.left + rect.width / 2 - width / 2),
    window.innerWidth - width - 8,
  )
  let top = rect.bottom + 8
  // 下方空间不足时翻到上方，避免弹层被视口裁掉。
  if (top + height > window.innerHeight - 8) {
    top = Math.max(8, rect.top - height - 8)
  }
  popStyle.value = { left: `${Math.round(left)}px`, top: `${Math.round(top)}px` }
}

function open() {
  if (!editable.value) return
  editing.value = true
  placePopover()
  void nextTick(placePopover)
}

function close() {
  editing.value = false
}

function applyDate(value: string) {
  props.updateAttributes({ date: value })
  close()
}

function onDocPointer(event: MouseEvent) {
  if (!editing.value) return
  const target = event.target as Node | null
  if (!target) return
  if (pop.value?.contains(target)) return
  const dom = (() => {
    try {
      const pos = props.getPos()
      return typeof pos === 'number' ? props.editor.view.nodeDOM(pos) : null
    } catch {
      return null
    }
  })()
  if (dom && (dom as HTMLElement).contains(target)) return
  close()
}

function onDocKey(event: KeyboardEvent) {
  if (editing.value && event.key === 'Escape') close()
}

function onViewportChange() {
  if (editing.value) placePopover()
}

watch(editing, (open) => {
  if (open) {
    window.addEventListener('scroll', onViewportChange, true)
    window.addEventListener('resize', onViewportChange)
  } else {
    window.removeEventListener('scroll', onViewportChange, true)
    window.removeEventListener('resize', onViewportChange)
  }
})

onMounted(() => {
  document.addEventListener('mousedown', onDocPointer)
  document.addEventListener('keydown', onDocKey)
})
onBeforeUnmount(() => {
  document.removeEventListener('mousedown', onDocPointer)
  document.removeEventListener('keydown', onDocKey)
  window.removeEventListener('scroll', onViewportChange, true)
  window.removeEventListener('resize', onViewportChange)
})
</script>

<template>
  <NodeViewWrapper
    ref="root"
    as="span"
    class="kiwi-date-wrap"
    :class="{ 'is-selected': selected, 'is-readonly': !editable, 'is-open': editing }"
    data-kiwi-date-node
    contenteditable="false"
  >
    <button
      type="button"
      class="kiwi-date-chip"
      :title="editable ? '点击修改日期' : String(node.attrs.date || '')"
      @mousedown.prevent
      @click.stop="open"
    >
      <span class="kiwi-date-icon" aria-hidden="true">📅</span>
      <span>{{ node.attrs.date || '选择日期' }}</span>
    </button>

    <Teleport to="html">
      <!-- 外层固定在视口坐标（<html> 不受 body zoom 影响），内层单独缩放 -->
      <div v-if="editing" class="kiwi-date-anchor" :style="popStyle">
        <div ref="pop" :style="{ zoom: 'var(--ui-scale)' }" @mousedown.stop>
          <KiwiCalendarPanel
            :model-value="String(node.attrs.date || '')"
            hint="选择日期后立即生效"
            @update:model-value="applyDate"
            @close="close"
          />
        </div>
      </div>
    </Teleport>
  </NodeViewWrapper>
</template>

<style scoped>
.kiwi-date-wrap {
  position: relative;
  display: inline-flex;
  vertical-align: baseline;
}
.kiwi-date-chip {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  margin: 0 2px;
  padding: 1px 7px;
  border-radius: 999px;
  border: 1px solid rgb(var(--theme-accent) / 0.4);
  background: rgb(var(--theme-accent) / 0.1);
  color: rgb(var(--theme-accent));
  font-size: 0.86em;
  line-height: 1.5;
  font-variant-numeric: tabular-nums;
  cursor: pointer;
  transition: background 0.15s ease, border-color 0.15s ease;
}
.kiwi-date-chip:hover {
  background: rgb(var(--theme-accent) / 0.16);
  border-color: rgb(var(--theme-accent) / 0.65);
}
.kiwi-date-icon {
  font-size: 0.92em;
  line-height: 1;
}
.is-readonly .kiwi-date-chip {
  cursor: default;
}
.is-readonly .kiwi-date-chip:hover {
  background: rgb(var(--theme-accent) / 0.1);
  border-color: rgb(var(--theme-accent) / 0.4);
}
.is-selected .kiwi-date-chip,
.is-open .kiwi-date-chip {
  outline: 2px solid rgb(var(--theme-accent) / 0.55);
  outline-offset: 1px;
}
</style>

<style>
/* 弹层通过 Teleport 挂到 <html>，定位样式不能带 scoped 属性。 */
.kiwi-date-anchor {
  position: fixed;
  z-index: 90;
  width: 0;
  height: 0;
}
</style>

<script setup lang="ts">
/** 日期胶囊：点击在胶囊正下方弹出主题化月历，就地选择日期。 */
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { NodeViewWrapper, nodeViewProps } from '@tiptap/vue-3'
import { useEditorEditable } from './useEditorEditable'

const props = defineProps(nodeViewProps)

const root = ref<HTMLElement | null>(null)
const pop = ref<HTMLElement | null>(null)
const editable = useEditorEditable(props.editor)
const editing = ref(false)
const draft = ref(String(props.node.attrs.date || ''))

const POP_WIDTH = 264
const POP_HEIGHT = 336

const popStyle = ref<Record<string, string>>({})

function uiScale(): number {
  const raw = getComputedStyle(document.documentElement).getPropertyValue('--ui-scale')
  const value = Number.parseFloat(raw)
  return Number.isFinite(value) && value > 0 ? value : 1
}

function formatDate(year: number, month: number, day: number) {
  const m = String(month + 1).padStart(2, '0')
  const d = String(day).padStart(2, '0')
  return `${year}-${m}-${d}`
}

function parseDate(value: string): { year: number; month: number; day: number } | null {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value)
  if (!match) return null
  return { year: Number(match[1]), month: Number(match[2]) - 1, day: Number(match[3]) }
}

const today = new Date()
const viewYear = ref(today.getFullYear())
const viewMonth = ref(today.getMonth())

const selectedKey = computed(() => draft.value)
const todayKey = formatDate(today.getFullYear(), today.getMonth(), today.getDate())

const monthLabel = computed(() => `${viewYear.value} 年 ${viewMonth.value + 1} 月`)

const WEEKDAYS = ['一', '二', '三', '四', '五', '六', '日']

interface DayCell {
  key: string
  day: number
  inMonth: boolean
}

const days = computed<DayCell[]>(() => {
  const first = new Date(viewYear.value, viewMonth.value, 1)
  // 周一为一周起点：getDay() 的周日是 0。
  const offset = (first.getDay() + 6) % 7
  const cells: DayCell[] = []
  for (let index = 0; index < 42; index += 1) {
    const date = new Date(viewYear.value, viewMonth.value, index - offset + 1)
    cells.push({
      key: formatDate(date.getFullYear(), date.getMonth(), date.getDate()),
      day: date.getDate(),
      inMonth: date.getMonth() === viewMonth.value,
    })
  }
  return cells
})

function shiftMonth(delta: number) {
  const next = new Date(viewYear.value, viewMonth.value + delta, 1)
  viewYear.value = next.getFullYear()
  viewMonth.value = next.getMonth()
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
  draft.value = String(props.node.attrs.date || '')
  const parsed = parseDate(draft.value)
  const base = parsed ?? {
    year: today.getFullYear(),
    month: today.getMonth(),
    day: today.getDate(),
  }
  viewYear.value = base.year
  viewMonth.value = base.month
  editing.value = true
  placePopover()
  void nextTick(placePopover)
}

function close() {
  editing.value = false
}

function pick(key: string) {
  draft.value = key
  props.updateAttributes({ date: key })
  close()
}

function clear() {
  draft.value = ''
  props.updateAttributes({ date: '' })
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
        <div
          ref="pop"
          class="kiwi-date-pop"
          :style="{ zoom: 'var(--ui-scale)' }"
          role="dialog"
          aria-label="选择日期"
          @mousedown.stop
        >
        <div class="kiwi-date-pop-head">
          <button type="button" class="kiwi-date-nav" title="上个月" @click="shiftMonth(-1)">
            ‹
          </button>
          <span class="kiwi-date-month">{{ monthLabel }}</span>
          <button type="button" class="kiwi-date-nav" title="下个月" @click="shiftMonth(1)">
            ›
          </button>
        </div>
        <div class="kiwi-date-week">
          <span v-for="weekday in WEEKDAYS" :key="weekday">{{ weekday }}</span>
        </div>
        <div class="kiwi-date-grid">
          <button
            v-for="cell in days"
            :key="cell.key"
            type="button"
            class="kiwi-date-day"
            :class="{
              'is-outside': !cell.inMonth,
              'is-today': cell.key === todayKey,
              'is-selected': cell.key === selectedKey,
            }"
            @click="pick(cell.key)"
          >
            {{ cell.day }}
          </button>
        </div>
        <div class="kiwi-date-pop-foot">
          <button type="button" class="kiwi-date-quick" @click="pick(todayKey)">今天</button>
          <button
            v-if="node.attrs.date"
            type="button"
            class="kiwi-date-quick is-muted"
            @click="clear"
          >
            清除
          </button>
          <span class="kiwi-date-hint">选择日期后立即生效</span>
        </div>
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
  border: 1px solid rgb(var(--kiwi-400) / 0.45);
  background: rgb(var(--kiwi-50));
  color: rgb(var(--kiwi-700));
  font-size: 0.86em;
  line-height: 1.5;
  font-variant-numeric: tabular-nums;
  cursor: pointer;
  transition: background 0.15s ease, border-color 0.15s ease;
}
.kiwi-date-chip:hover {
  background: rgb(var(--kiwi-100));
  border-color: rgb(var(--kiwi-400) / 0.7);
}
.kiwi-date-icon {
  font-size: 0.92em;
  line-height: 1;
}
.is-readonly .kiwi-date-chip {
  cursor: default;
}
.is-readonly .kiwi-date-chip:hover {
  background: rgb(var(--kiwi-50));
  border-color: rgb(var(--kiwi-400) / 0.45);
}
.is-selected .kiwi-date-chip,
.is-open .kiwi-date-chip {
  outline: 2px solid rgb(var(--kiwi-400) / 0.55);
  outline-offset: 1px;
}
</style>

<style>
/* 弹层通过 Teleport 挂到 <html>，样式不能带 scoped 属性。 */
.kiwi-date-anchor {
  position: fixed;
  z-index: 90;
  width: 0;
  height: 0;
}
.kiwi-date-pop {
  position: relative;
  width: 264px;
  padding: 10px;
  border: 1px solid rgb(var(--kiwi-200));
  border-radius: 14px;
  background: #fff;
  box-shadow: 0 18px 44px rgb(15 23 42 / 0.16), 0 2px 8px rgb(15 23 42 / 0.06);
  font-family: inherit;
  animation: kiwi-date-pop-in 0.14s ease;
}
@keyframes kiwi-date-pop-in {
  from {
    opacity: 0;
    transform: translateY(-4px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}
.kiwi-date-pop-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
  padding: 2px 2px 8px;
}
.kiwi-date-month {
  font-size: 12.5px;
  font-weight: 600;
  color: rgb(30 41 59);
}
.kiwi-date-nav {
  display: grid;
  place-items: center;
  width: 24px;
  height: 24px;
  border-radius: 7px;
  color: rgb(var(--kiwi-700));
  font-size: 15px;
  line-height: 1;
  transition: background 0.15s ease;
}
.kiwi-date-nav:hover {
  background: rgb(var(--kiwi-50));
}
.kiwi-date-week,
.kiwi-date-grid {
  display: grid;
  grid-template-columns: repeat(7, 1fr);
  gap: 2px;
}
.kiwi-date-week {
  padding-bottom: 4px;
  font-size: 10px;
  color: rgb(148 163 184);
  text-align: center;
}
.kiwi-date-day {
  height: 30px;
  border-radius: 8px;
  font-size: 12px;
  color: rgb(51 65 85);
  font-variant-numeric: tabular-nums;
  transition: background 0.12s ease, color 0.12s ease;
}
.kiwi-date-day:hover {
  background: rgb(var(--kiwi-50));
  color: rgb(var(--kiwi-700));
}
.kiwi-date-day.is-outside {
  color: rgb(203 213 225);
}
.kiwi-date-day.is-today {
  box-shadow: inset 0 0 0 1px rgb(var(--kiwi-300));
}
.kiwi-date-day.is-selected {
  background: rgb(var(--kiwi-500));
  color: #fff;
  font-weight: 600;
  box-shadow: none;
}
.kiwi-date-pop-foot {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px solid rgb(241 245 249);
}
.kiwi-date-quick {
  padding: 3px 9px;
  border-radius: 7px;
  background: rgb(var(--kiwi-50));
  color: rgb(var(--kiwi-700));
  font-size: 11px;
}
.kiwi-date-quick:hover {
  background: rgb(var(--kiwi-100));
}
.kiwi-date-quick.is-muted {
  background: rgb(248 250 252);
  color: rgb(100 116 139);
}
.kiwi-date-hint {
  margin-left: auto;
  font-size: 10px;
  color: rgb(148 163 184);
}
</style>

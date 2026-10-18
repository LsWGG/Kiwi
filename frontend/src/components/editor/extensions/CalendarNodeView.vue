<script setup lang="ts">
/**
 * 日历块：月视图浏览，支持单日与跨天安排。
 * 跨天安排以周为单位绘制连续横条，排布规则与数据表笔记的日历视图一致。
 */
import { computed, ref, watch } from 'vue'
import { NodeViewWrapper, nodeViewProps } from '@tiptap/vue-3'
import KiwiIcon from '@/components/ui/KiwiIcon.vue'
import { chipClass, dotClass } from '@/components/notes/database/colors'
import {
  CALENDAR_COLORS,
  buildCalendarMonth,
  currentMonth,
  dateKey,
  eventRangeLabel,
  eventsOnDate,
  isValidCalendarDate,
  newCalendarEventId,
  rangeBarStyle,
  sanitizeEvents,
  type CalendarEvent,
} from './calendar'
import { useEditorEditable } from './useEditorEditable'

const props = defineProps(nodeViewProps)

const WEEKDAYS = ['一', '二', '三', '四', '五', '六', '日']
const TODAY = dateKey(new Date())

function normalizedMonth(value: unknown): string {
  const raw = String(value ?? '')
  return /^\d{4}-\d{2}$/.test(raw) ? raw : currentMonth()
}

const title = computed(() => String(props.node.attrs.title || ''))
const events = computed(() => sanitizeEvents(props.node.attrs.events))
const editable = useEditorEditable(props.editor)

// 月份是浏览状态：在阅读模式翻月不会改写笔记正文
const viewMonth = ref(normalizedMonth(props.node.attrs.month))
watch(
  () => props.node.attrs.month,
  (value) => {
    const next = normalizedMonth(value)
    if (next !== viewMonth.value) viewMonth.value = next
  },
)

const monthModel = computed(() =>
  buildCalendarMonth(viewMonth.value, events.value, TODAY),
)
const monthLabel = computed(
  () => `${monthModel.value.year} 年 ${monthModel.value.monthIndex + 1} 月`,
)

const selectedDate = ref('')
const editingId = ref<string | null>(null)
const draftTitle = ref('')
const draftStart = ref('')
const draftEnd = ref('')
const draftColor = ref<string>('green')

const selectedDayEvents = computed(() =>
  selectedDate.value
    ? eventsOnDate(events.value, selectedDate.value).sort(
        (a, b) => a.start.localeCompare(b.start) || a.title.localeCompare(b.title),
      )
    : [],
)

// 切到阅读模式时清掉编辑态选中，避免日期仍显示为“已选中”
watch(editable, (value) => {
  if (!value) {
    selectedDate.value = ''
    editingId.value = null
  }
})

function update(attrs: Record<string, unknown>) {
  props.updateAttributes(attrs)
}

function setViewMonth(value: string) {
  viewMonth.value = value
  // 编辑时记住浏览月份，重新打开笔记仍停留在最近查看的月份；阅读模式不改正文
  if (editable.value) update({ month: value })
}

function shiftMonth(delta: number) {
  const model = monthModel.value
  const target = new Date(model.year, model.monthIndex + delta, 1)
  setViewMonth(
    `${target.getFullYear()}-${String(target.getMonth() + 1).padStart(2, '0')}`,
  )
  selectedDate.value = ''
  editingId.value = null
}

function goToday() {
  setViewMonth(currentMonth())
  selectedDate.value = ''
  editingId.value = null
}

function resetDraft(date: string) {
  editingId.value = null
  draftTitle.value = ''
  draftStart.value = date
  draftEnd.value = date
  draftColor.value = 'green'
}

function pickDay(dayKey: string) {
  if (!editable.value) return
  if (dayKey.slice(0, 7) !== viewMonth.value) setViewMonth(dayKey.slice(0, 7))
  selectedDate.value = dayKey
  resetDraft(dayKey)
}

function editEvent(event: CalendarEvent) {
  if (!editable.value) return
  selectedDate.value = event.start
  if (event.start.slice(0, 7) !== viewMonth.value) setViewMonth(event.start.slice(0, 7))
  editingId.value = event.id
  draftTitle.value = event.title
  draftStart.value = event.start
  draftEnd.value = event.end
  draftColor.value = event.color ?? 'green'
}

function dayEvents(key: string): CalendarEvent[] {
  return monthModel.value.singleByDate.get(key) ?? []
}

function compactRange(event: CalendarEvent): string {
  const start = event.start.slice(5)
  return event.end === event.start ? start : `${start} → ${event.end.slice(5)}`
}

function eventTone(event: CalendarEvent): string {
  return chipClass(event.color ?? undefined)
}

function commit() {
  if (!selectedDate.value) return
  const text = draftTitle.value.trim()
  if (!text) {
    if (editingId.value) removeEvent()
    return
  }
  const start = isValidCalendarDate(draftStart.value)
    ? draftStart.value
    : selectedDate.value
  const end =
    isValidCalendarDate(draftEnd.value) && draftEnd.value >= start
      ? draftEnd.value
      : start
  const color = CALENDAR_COLORS.includes(draftColor.value as any)
    ? draftColor.value
    : null
  let next: CalendarEvent[]
  if (editingId.value) {
    next = events.value.map((event) =>
      event.id === editingId.value
        ? { id: event.id, title: text, start, end, color }
        : event,
    )
  } else {
    next = [...events.value, { id: newCalendarEventId(), title: text, start, end, color }]
  }
  update({ events: next })
  selectedDate.value = start
  resetDraft(start)
}

function removeEvent() {
  if (!editingId.value) return
  update({ events: events.value.filter((event) => event.id !== editingId.value) })
  resetDraft(selectedDate.value || dateKey(new Date()))
}

function clearDraft() {
  resetDraft(selectedDate.value || dateKey(new Date()))
  selectedDate.value = ''
}

function setTitle(event: Event) {
  update({ title: (event.target as HTMLInputElement).value.slice(0, 200) })
}
</script>

<template>
  <NodeViewWrapper
    class="kiwi-calendar-block"
    :class="{ 'is-selected': selected, 'is-readonly': !editable }"
    data-type="kiwi-calendar"
    contenteditable="false"
  >
    <div v-if="editable" class="kiwi-calendar-toolbar">
      <span class="kiwi-calendar-tag">
        <KiwiIcon name="calendar" :size="11" />
        日历
      </span>
      <input
        class="kiwi-calendar-title"
        :value="title"
        placeholder="添加日历标题"
        @input="setTitle"
        @keydown.stop
        @mousedown.stop
      />
      <div class="kiwi-calendar-nav">
        <button type="button" title="上个月" @mousedown.prevent @click="shiftMonth(-1)">
          <KiwiIcon name="chevronRight" :size="12" class="rotate-180" />
        </button>
        <button type="button" class="kiwi-calendar-month" title="回到本月" @mousedown.prevent @click="goToday">
          {{ monthLabel }}
        </button>
        <button type="button" title="下个月" @mousedown.prevent @click="shiftMonth(1)">
          <KiwiIcon name="chevronRight" :size="12" />
        </button>
      </div>
    </div>

    <div v-if="!editable" class="kiwi-calendar-readonly-head">
      <span v-if="title" class="kiwi-calendar-readonly-title">{{ title }}</span>
      <div class="kiwi-calendar-nav">
        <button type="button" title="上个月" @mousedown.prevent @click="shiftMonth(-1)">
          <KiwiIcon name="chevronRight" :size="12" class="rotate-180" />
        </button>
        <button type="button" class="kiwi-calendar-month" title="回到本月" @mousedown.prevent @click="goToday">
          {{ monthLabel }}
        </button>
        <button type="button" title="下个月" @mousedown.prevent @click="shiftMonth(1)">
          <KiwiIcon name="chevronRight" :size="12" />
        </button>
      </div>
    </div>

    <div class="kiwi-calendar-grid">
      <span v-for="weekday in WEEKDAYS" :key="weekday" class="kiwi-calendar-weekday">
        {{ weekday }}
      </span>
    </div>

    <div class="kiwi-calendar-weeks">
      <div v-for="week in monthModel.weeks" :key="week.key" class="kiwi-calendar-week">
        <!-- 跨天安排：本周顶部连续横条 -->
        <div
          v-if="week.ranges.length"
          class="kiwi-calendar-band"
          :style="{ height: `${week.bandHeight}px` }"
        >
          <div
            v-for="segment in week.ranges"
            :key="segment.event.id"
            class="kiwi-calendar-range"
            :class="[
              eventTone(segment.event),
              segment.continuesLeft ? 'rounded-l-none border-l-0' : '',
              segment.continuesRight ? 'rounded-r-none border-r-0' : '',
              editable ? 'is-editable' : '',
            ]"
            :style="rangeBarStyle(segment)"
            :title="eventRangeLabel(segment.event) + ' · ' + segment.event.title"
            @click.stop="editable && editEvent(segment.event)"
          >
            <span class="min-w-0 truncate">
              <span v-if="segment.continuesLeft" class="opacity-60">…</span>{{ segment.event.title }}<span
                v-if="segment.continuesRight"
                class="opacity-60"
              >…</span>
            </span>
          </div>
        </div>

        <div class="kiwi-calendar-weekdays-row">
          <div
            v-for="day in week.days"
            :key="day.key"
            class="kiwi-calendar-day"
            :class="{
              'is-outside': !day.inMonth,
              'is-today': day.today,
              'is-selected': selectedDate === day.key && editable,
              'is-clickable': editable,
            }"
            :title="day.key"
            @click="pickDay(day.key)"
          >
            <span class="kiwi-calendar-daynum">{{ day.day }}</span>
            <div v-if="dayEvents(day.key).length" class="kiwi-calendar-chips">
              <span
                v-for="event in dayEvents(day.key).slice(0, 2)"
                :key="event.id"
                class="kiwi-calendar-chip"
                :class="[eventTone(event), editable ? 'is-editable' : '']"
                :title="event.title"
                @click.stop="editable && editEvent(event)"
              >
                <span class="truncate">{{ event.title }}</span>
              </span>
              <span v-if="dayEvents(day.key).length > 2" class="kiwi-calendar-more">
                +{{ dayEvents(day.key).length - 2 }}
              </span>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 编辑面板：新建 / 修改一条安排 -->
    <div v-if="editable && selectedDate" class="kiwi-calendar-editor">
      <div class="kiwi-calendar-editor-row">
        <span class="kiwi-calendar-event-date">{{ selectedDate.slice(5) }}</span>
        <span v-if="editingId" class="kiwi-calendar-editing-tag">编辑安排</span>
        <span v-else class="kiwi-calendar-editing-tag">新建安排</span>
        <input
          v-model="draftTitle"
          class="kiwi-calendar-event-input"
          placeholder="安排内容，例如：现场联调"
          @keydown.stop
          @keydown.enter.prevent="commit"
          @mousedown.stop
        />
      </div>
      <div class="kiwi-calendar-editor-row is-options">
        <label class="kiwi-calendar-date-field">
          开始
          <input v-model="draftStart" type="date" @keydown.stop @mousedown.stop />
        </label>
        <span class="kiwi-calendar-arrow">→</span>
        <label class="kiwi-calendar-date-field">
          结束
          <input v-model="draftEnd" type="date" :min="draftStart" @keydown.stop @mousedown.stop />
        </label>
        <div class="kiwi-calendar-colors">
          <button
            v-for="color in CALENDAR_COLORS"
            :key="color"
            type="button"
            class="kiwi-calendar-swatch"
            :class="[dotClass(color), draftColor === color ? 'is-active' : '']"
            :title="`标记颜色：${color}`"
            @mousedown.prevent
            @click="draftColor = color"
          />
        </div>
        <div class="flex-1" />
        <button
          v-if="editingId"
          type="button"
          class="kiwi-calendar-clear"
          title="删除这条安排"
          @mousedown.prevent
          @click="removeEvent"
        >
          <KiwiIcon name="trash" :size="11" />
        </button>
        <button type="button" class="kiwi-calendar-cancel" @mousedown.prevent @click="clearDraft">取消</button>
        <button type="button" class="kiwi-calendar-save" @mousedown.prevent @click="commit">保存</button>
      </div>
      <div v-if="selectedDayEvents.length" class="kiwi-calendar-day-events">
        <button
          v-for="event in selectedDayEvents"
          :key="event.id"
          type="button"
          class="kiwi-calendar-day-event"
          :class="{ 'is-current': editingId === event.id }"
          @mousedown.prevent
          @click="editEvent(event)"
        >
          <span class="kiwi-calendar-event-range">{{ eventRangeLabel(event) }}</span>
          <span class="truncate">{{ event.title }}</span>
        </button>
      </div>
    </div>
    <p v-else-if="editable" class="kiwi-calendar-hint">
      点击日期添加安排；设置结束日期即可跨天，跨天安排会在每周顶部连续展示
    </p>

    <div v-if="!editable && monthModel.monthEvents.length" class="kiwi-calendar-readonly-events">
      <div
        v-for="event in monthModel.monthEvents"
        :key="event.id"
        class="kiwi-calendar-readonly-event"
      >
        <span
          class="kiwi-calendar-readonly-date"
          :class="event.color ? chipClass(event.color) : ''"
        >{{ compactRange(event) }}</span>
        <span class="kiwi-calendar-readonly-text">{{ event.title }}</span>
      </div>
    </div>
  </NodeViewWrapper>
</template>

<style scoped>
.kiwi-calendar-block {
  margin: 0.75rem 0;
  padding: 10px 12px 8px;
  border-radius: 12px;
  border: 1px solid rgb(226 232 240);
  background: rgb(255 255 255 / 0.82);
  transition: border-color 0.15s ease, box-shadow 0.15s ease;
}
.kiwi-calendar-block.is-selected {
  border-color: rgb(190 242 100);
  box-shadow: 0 0 0 3px rgb(236 252 203 / 0.55);
}
/* 阅读模式：去掉组件外框，只保留月历与安排本身 */
.kiwi-calendar-block.is-readonly {
  margin: 0.9rem 0;
  padding: 0;
  border: 0;
  background: transparent;
  border-radius: 0;
}
.kiwi-calendar-readonly-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 6px;
}
.kiwi-calendar-readonly-title {
  font-size: 12.5px;
  font-weight: 600;
  color: rgb(51 65 85);
}
.kiwi-calendar-toolbar {
  display: flex;
  align-items: center;
  gap: 8px;
  min-height: 26px;
  margin-bottom: 6px;
}
.kiwi-calendar-tag {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 11px;
  font-weight: 500;
  color: rgb(71 85 105);
}
.kiwi-calendar-title {
  min-width: 0;
  flex: 1;
  border: 0;
  background: transparent;
  font-size: 12px;
  color: rgb(51 65 85);
  outline: none;
}
.kiwi-calendar-title::placeholder {
  color: rgb(148 163 184);
}
.kiwi-calendar-nav {
  display: flex;
  align-items: center;
  gap: 2px;
  color: rgb(100 116 139);
}
.kiwi-calendar-nav button {
  display: grid;
  place-items: center;
  height: 24px;
  padding: 0 5px;
  border-radius: 6px;
  transition: background 0.15s ease, color 0.15s ease;
}
.kiwi-calendar-nav button:hover {
  background: rgb(247 254 231);
  color: rgb(77 124 15);
}
.kiwi-calendar-month {
  font-size: 11px;
  font-variant-numeric: tabular-nums;
}
.kiwi-calendar-grid {
  display: grid;
  grid-template-columns: repeat(7, minmax(0, 1fr));
  gap: 2px;
}
.kiwi-calendar-weekday {
  padding: 2px 0;
  text-align: center;
  font-size: 9.5px;
  color: rgb(148 163 184);
}
.kiwi-calendar-weeks {
  display: flex;
  flex-direction: column;
  gap: 3px;
}
.kiwi-calendar-week {
  border-radius: 7px;
  overflow: hidden;
}
.kiwi-calendar-band {
  position: relative;
  background: rgb(248 250 252 / 0.45);
}
.kiwi-calendar-range {
  position: absolute;
  display: flex;
  align-items: center;
  padding: 0 5px;
  border-width: 1px;
  border-style: solid;
  border-radius: 5px;
  font-size: 9.5px;
  line-height: 18px;
  overflow: hidden;
  transition: filter 0.15s ease, box-shadow 0.15s ease;
}
.kiwi-calendar-range.is-editable {
  cursor: pointer;
}
.kiwi-calendar-range.is-editable:hover {
  filter: saturate(1.4);
  box-shadow: 0 3px 10px rgb(15 23 42 / 0.16);
  z-index: 5;
}
.kiwi-calendar-weekdays-row {
  display: grid;
  grid-template-columns: repeat(7, minmax(0, 1fr));
  gap: 2px;
}
.kiwi-calendar-day {
  position: relative;
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-height: 48px;
  padding: 3px 3px 2px;
  border-radius: 6px;
  transition: background 0.12s ease;
}
.kiwi-calendar-day.is-clickable {
  cursor: pointer;
}
.kiwi-calendar-day.is-clickable:hover {
  background: rgb(241 245 249);
}
.kiwi-calendar-day.is-outside .kiwi-calendar-daynum {
  color: rgb(203 213 225);
}
.kiwi-calendar-day.is-today .kiwi-calendar-daynum {
  display: inline-grid;
  place-items: center;
  width: 16px;
  height: 16px;
  border-radius: 999px;
  background: rgb(101 163 13);
  color: white;
  font-weight: 600;
}
.kiwi-calendar-day.is-selected {
  background: rgb(236 252 203 / 0.9);
  box-shadow: inset 0 0 0 1px rgb(163 230 53 / 0.8);
}
.kiwi-calendar-daynum {
  width: 16px;
  height: 16px;
  display: inline-grid;
  place-items: center;
  font-size: 10px;
  color: rgb(71 85 105);
  font-variant-numeric: tabular-nums;
}
.kiwi-calendar-chips {
  display: flex;
  flex-direction: column;
  gap: 1px;
  min-width: 0;
}
.kiwi-calendar-chip {
  border-width: 1px;
  border-style: solid;
  border-radius: 4px;
  padding: 0 3px;
  font-size: 9px;
  line-height: 13px;
  overflow: hidden;
  white-space: nowrap;
}
.kiwi-calendar-chip.is-editable {
  cursor: pointer;
}
.kiwi-calendar-chip.is-editable:hover {
  filter: saturate(1.4);
}
.kiwi-calendar-more {
  font-size: 8.5px;
  color: rgb(148 163 184);
  padding-left: 2px;
}
.kiwi-calendar-editor {
  margin-top: 8px;
  padding-top: 7px;
  border-top: 1px dashed rgb(226 232 240);
  display: flex;
  flex-direction: column;
  gap: 5px;
}
.kiwi-calendar-editor-row {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
}
.kiwi-calendar-editor-row.is-options {
  flex-wrap: wrap;
}
.kiwi-calendar-event-date {
  flex-shrink: 0;
  border-radius: 5px;
  background: rgb(247 254 231);
  padding: 2px 6px;
  font-size: 10px;
  color: rgb(77 124 15);
  font-variant-numeric: tabular-nums;
}
.kiwi-calendar-editing-tag {
  flex-shrink: 0;
  font-size: 9.5px;
  color: rgb(148 163 184);
}
.kiwi-calendar-event-input {
  min-width: 0;
  flex: 1;
  border: 0;
  background: transparent;
  font-size: 11.5px;
  color: rgb(51 65 85);
  outline: none;
}
.kiwi-calendar-event-input::placeholder {
  color: rgb(148 163 184);
}
.kiwi-calendar-date-field {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 9.5px;
  color: rgb(100 116 139);
}
.kiwi-calendar-date-field input {
  border: 1px solid rgb(226 232 240);
  border-radius: 5px;
  background: white;
  padding: 1px 3px;
  font-size: 10px;
  color: rgb(51 65 85);
  outline: none;
  color-scheme: light;
}
.kiwi-calendar-date-field input:focus {
  border-color: rgb(163 230 53);
  box-shadow: 0 0 0 2px rgb(236 252 203 / 0.7);
}
.kiwi-calendar-arrow {
  color: rgb(203 213 225);
  font-size: 10px;
}
.kiwi-calendar-colors {
  display: flex;
  align-items: center;
  gap: 3px;
  margin-left: 2px;
}
.kiwi-calendar-swatch {
  width: 10px;
  height: 10px;
  border-radius: 999px;
  border: 1.5px solid transparent;
  transition: transform 0.12s ease, box-shadow 0.12s ease;
}
.kiwi-calendar-swatch:hover {
  transform: scale(1.2);
}
.kiwi-calendar-swatch.is-active {
  box-shadow: 0 0 0 2px white, 0 0 0 3px rgb(132 204 22);
}
.kiwi-calendar-save {
  border-radius: 5px;
  background: rgb(101 163 13);
  color: white;
  font-size: 10px;
  padding: 2px 8px;
}
.kiwi-calendar-save:hover {
  background: rgb(77 124 15);
}
.kiwi-calendar-cancel {
  border-radius: 5px;
  font-size: 10px;
  color: rgb(100 116 139);
  padding: 2px 6px;
}
.kiwi-calendar-cancel:hover {
  background: rgb(241 245 249);
}
.kiwi-calendar-clear {
  flex-shrink: 0;
  border-radius: 5px;
  padding: 3px;
  color: rgb(148 163 184);
}
.kiwi-calendar-clear:hover {
  background: rgb(254 242 242);
  color: rgb(220 38 38);
}
.kiwi-calendar-day-events {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding-top: 2px;
}
.kiwi-calendar-day-event {
  display: flex;
  align-items: baseline;
  gap: 6px;
  min-width: 0;
  border-radius: 5px;
  padding: 2px 4px;
  text-align: left;
  font-size: 10.5px;
  color: rgb(71 85 105);
}
.kiwi-calendar-day-event:hover {
  background: rgb(247 254 231);
  color: rgb(63 98 18);
}
.kiwi-calendar-day-event.is-current {
  background: rgb(236 252 203 / 0.7);
}
.kiwi-calendar-event-range {
  flex-shrink: 0;
  font-size: 9px;
  color: rgb(148 163 184);
  font-variant-numeric: tabular-nums;
}
.kiwi-calendar-hint {
  margin-top: 7px;
  padding-top: 6px;
  border-top: 1px dashed rgb(241 245 249);
  font-size: 10px;
  color: rgb(148 163 184);
}
.kiwi-calendar-readonly-events {
  margin-top: 9px;
  padding-top: 8px;
  border-top: 1px dashed rgb(226 232 240);
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.kiwi-calendar-readonly-event {
  display: flex;
  align-items: baseline;
  gap: 8px;
  font-size: 11.5px;
  color: rgb(51 65 85);
}
.kiwi-calendar-readonly-date {
  flex-shrink: 0;
  border-radius: 5px;
  background: rgb(247 254 231);
  padding: 1px 6px;
  font-size: 10px;
  color: rgb(77 124 15);
  font-variant-numeric: tabular-nums;
}
.kiwi-calendar-readonly-text {
  min-width: 0;
  line-height: 1.55;
}
</style>

<script setup lang="ts">
/**
 * 系统统一日期选择：玻璃面板 + 月历，替代原生 date 输入框。
 * v-model 使用 YYYY-MM-DD 字符串；清空时输出空字符串。
 */
import { computed, ref, watch } from 'vue'
import KiwiDropdown from './KiwiDropdown.vue'
import KiwiIcon from './KiwiIcon.vue'

const props = withDefaults(
  defineProps<{
    modelValue: string | null | undefined
    min?: string
    max?: string
    placeholder?: string
    disabled?: boolean
    title?: string
    /** 触发器额外 class，便于嵌入表格 / 筛选栏时沿用容器样式 */
    triggerClass?: string
    /** 允许清空 */
    clearable?: boolean
  }>(),
  {
    modelValue: '',
    min: '',
    max: '',
    placeholder: '选择日期',
    disabled: false,
    title: '',
    triggerClass: '',
    clearable: true,
  },
)

const emit = defineEmits<{ (e: 'update:modelValue', value: string): void }>()

const WEEKDAYS = ['一', '二', '三', '四', '五', '六', '日']

function pad(value: number) {
  return String(value).padStart(2, '0')
}

function iso(year: number, month: number, day: number) {
  return `${year}-${pad(month + 1)}-${pad(day)}`
}

function parseValue(value: string | null | undefined): Date | null {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(value || ''))
  if (!match) return null
  const date = new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]))
  return Number.isNaN(date.getTime()) ? null : date
}

const today = new Date()
const todayKey = iso(today.getFullYear(), today.getMonth(), today.getDate())
const viewYear = ref(today.getFullYear())
const viewMonth = ref(today.getMonth())

const selectedKey = computed(() => String(props.modelValue || ''))
const selectedDate = computed(() => parseValue(selectedKey.value))
const display = computed(() => selectedKey.value || props.placeholder)
const hasValue = computed(() => !!selectedKey.value)

function syncViewToValue() {
  const date = selectedDate.value
  if (date) {
    viewYear.value = date.getFullYear()
    viewMonth.value = date.getMonth()
  }
}

watch(selectedKey, syncViewToValue)

const monthLabel = computed(() => `${viewYear.value} 年 ${viewMonth.value + 1} 月`)

const weeks = computed(() => {
  const first = new Date(viewYear.value, viewMonth.value, 1)
  const offset = (first.getDay() + 6) % 7
  const start = new Date(viewYear.value, viewMonth.value, 1 - offset)
  return Array.from({ length: 6 }, (_, row) =>
    Array.from({ length: 7 }, (_, col) => {
      const date = new Date(start.getFullYear(), start.getMonth(), start.getDate() + row * 7 + col)
      const key = iso(date.getFullYear(), date.getMonth(), date.getDate())
      return {
        key,
        day: date.getDate(),
        inMonth: date.getMonth() === viewMonth.value,
        today: key === todayKey,
        selected: key === selectedKey.value,
      }
    }),
  )
})

function disabledKey(key: string) {
  if (props.min && key < props.min) return true
  if (props.max && key > props.max) return true
  return false
}

function shiftMonth(delta: number) {
  const next = new Date(viewYear.value, viewMonth.value + delta, 1)
  viewYear.value = next.getFullYear()
  viewMonth.value = next.getMonth()
}

function goToday() {
  const now = new Date()
  viewYear.value = now.getFullYear()
  viewMonth.value = now.getMonth()
  if (!disabledKey(todayKey)) emit('update:modelValue', todayKey)
}

function pick(key: string, close: () => void) {
  if (disabledKey(key)) return
  emit('update:modelValue', key)
  close()
}

function clear(close: () => void) {
  emit('update:modelValue', '')
  close()
}
</script>

<template>
  <KiwiDropdown width="w-[268px]" align="left">
    <template #trigger="{ open }">
      <button
        type="button"
        class="flex h-8 w-full items-center gap-1.5 rounded-lg border border-slate-200 bg-white/80 px-2 text-left text-[11px] text-slate-600 outline-none transition-colors hover:border-kiwi-200 focus:ring-2 focus:ring-kiwi-200 disabled:cursor-not-allowed disabled:opacity-50"
        :class="[
          triggerClass,
          open ? 'border-kiwi-300 ring-2 ring-kiwi-100' : '',
          !hasValue ? 'text-slate-400' : '',
        ]"
        :disabled="disabled"
        :title="title || display"
        :aria-label="title || placeholder"
        aria-haspopup="dialog"
        :aria-expanded="open"
      >
        <KiwiIcon name="calendar" :size="13" class="shrink-0 text-slate-400" />
        <span class="min-w-0 flex-1 truncate tabular-nums">{{ display }}</span>
        <KiwiIcon
          v-if="clearable && hasValue"
          name="close"
          :size="11"
          class="shrink-0 text-slate-300 hover:text-rose-500"
          title="清除日期"
          @click.stop="emit('update:modelValue', '')"
        />
      </button>
    </template>
    <template #default="{ close }">
      <div class="select-none">
        <div class="flex items-center justify-between px-1 pb-1.5 pt-0.5">
          <button
            type="button"
            class="grid h-6 w-6 place-items-center rounded-md text-slate-400 transition-colors hover:bg-kiwi-50 hover:text-kiwi-700"
            title="上个月"
            @click="shiftMonth(-1)"
          >
            <KiwiIcon name="chevron" :size="11" class="rotate-90" />
          </button>
          <button
            type="button"
            class="rounded-md px-1.5 py-0.5 text-[11.5px] font-medium text-slate-700 transition-colors hover:bg-kiwi-50 hover:text-kiwi-700"
            title="回到今天"
            @click="goToday"
          >
            {{ monthLabel }}
          </button>
          <button
            type="button"
            class="grid h-6 w-6 place-items-center rounded-md text-slate-400 transition-colors hover:bg-kiwi-50 hover:text-kiwi-700"
            title="下个月"
            @click="shiftMonth(1)"
          >
            <KiwiIcon name="chevron" :size="11" class="-rotate-90" />
          </button>
        </div>
        <div class="grid grid-cols-7 gap-0.5 px-0.5 pb-0.5">
          <span
            v-for="weekday in WEEKDAYS"
            :key="weekday"
            class="grid h-6 place-items-center text-[10px] font-medium text-slate-400"
          >{{ weekday }}</span>
          <template v-for="(week, index) in weeks" :key="index">
            <button
              v-for="day in week"
              :key="day.key"
              type="button"
              class="relative grid h-7 place-items-center rounded-md text-[11px] tabular-nums transition-colors disabled:cursor-not-allowed disabled:opacity-35"
              :class="[
                day.selected
                  ? 'bg-kiwi-500 font-semibold text-white'
                  : day.today
                    ? 'font-semibold text-kiwi-700 hover:bg-kiwi-50'
                    : day.inMonth
                      ? 'text-slate-600 hover:bg-kiwi-50'
                      : 'text-slate-300 hover:bg-slate-50',
              ]"
              :title="day.key"
              :disabled="disabledKey(day.key)"
              @click="pick(day.key, close)"
            >
              {{ day.day }}
              <span
                v-if="day.today && !day.selected"
                class="absolute bottom-0.5 h-1 w-1 rounded-full bg-kiwi-500"
              />
            </button>
          </template>
        </div>
        <div class="mt-1 flex items-center justify-between border-t border-slate-100 px-1 pt-1">
          <button
            type="button"
            class="rounded-md px-1.5 py-0.5 text-[10.5px] text-slate-500 transition-colors hover:bg-kiwi-50 hover:text-kiwi-700"
            @click="goToday(); close()"
          >
            今天
          </button>
          <button
            v-if="clearable"
            type="button"
            class="rounded-md px-1.5 py-0.5 text-[10.5px] text-slate-400 transition-colors hover:bg-rose-50 hover:text-rose-500"
            @click="clear(close)"
          >
            清除
          </button>
        </div>
      </div>
    </template>
  </KiwiDropdown>
</template>

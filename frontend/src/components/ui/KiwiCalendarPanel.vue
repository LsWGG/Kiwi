<script setup lang="ts">
/**
 * 统一月历面板：数据表日期字段、筛选栏、日期胶囊共用同一套视觉与交互。
 * 选中即生效：点击日期、今天或清除都会立即 emit，由宿主决定是否关闭弹层。
 */
import { computed, ref, watch } from 'vue'
import KiwiIcon from './KiwiIcon.vue'

const props = withDefaults(
  defineProps<{
    modelValue?: string | null
    min?: string
    max?: string
    clearable?: boolean
    /** 底部右侧提示文案；留空则不显示。 */
    hint?: string
  }>(),
  {
    modelValue: '',
    min: '',
    max: '',
    clearable: true,
    hint: '选择日期后立即生效',
  },
)

const emit = defineEmits<{
  (e: 'update:modelValue', value: string): void
  (e: 'close'): void
}>()

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
const hasValue = computed(() => !!selectedKey.value)

function syncViewToValue() {
  const date = parseValue(selectedKey.value)
  if (date) {
    viewYear.value = date.getFullYear()
    viewMonth.value = date.getMonth()
  }
}

watch(selectedKey, syncViewToValue, { immediate: true })

const monthLabel = computed(() => `${viewYear.value} 年 ${viewMonth.value + 1} 月`)

const days = computed(() => {
  const first = new Date(viewYear.value, viewMonth.value, 1)
  // 周一为一周起点：getDay() 的周日是 0。
  const offset = (first.getDay() + 6) % 7
  return Array.from({ length: 42 }, (_, index) => {
    const date = new Date(viewYear.value, viewMonth.value, index - offset + 1)
    const key = iso(date.getFullYear(), date.getMonth(), date.getDate())
    return {
      key,
      day: date.getDate(),
      inMonth: date.getMonth() === viewMonth.value,
      today: key === todayKey,
      selected: key === selectedKey.value,
    }
  })
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

function pick(key: string) {
  if (disabledKey(key)) return
  emit('update:modelValue', key)
  emit('close')
}

function goToday() {
  const now = new Date()
  viewYear.value = now.getFullYear()
  viewMonth.value = now.getMonth()
  pick(todayKey)
}

function clear() {
  emit('update:modelValue', '')
  emit('close')
}
</script>

<template>
  <div class="kiwi-calendar-panel" role="dialog" aria-label="选择日期">
    <div class="kiwi-calendar-head">
      <button type="button" class="kiwi-calendar-nav" title="上个月" @click="shiftMonth(-1)">
        <KiwiIcon name="chevron" :size="11" class="rotate-90" />
      </button>
      <span class="kiwi-calendar-month">{{ monthLabel }}</span>
      <button type="button" class="kiwi-calendar-nav" title="下个月" @click="shiftMonth(1)">
        <KiwiIcon name="chevron" :size="11" class="-rotate-90" />
      </button>
    </div>
    <div class="kiwi-calendar-week">
      <span v-for="weekday in WEEKDAYS" :key="weekday">{{ weekday }}</span>
    </div>
    <div class="kiwi-calendar-grid">
      <button
        v-for="day in days"
        :key="day.key"
        type="button"
        class="kiwi-calendar-day"
        :class="{
          'is-outside': !day.inMonth,
          'is-today': day.today,
          'is-selected': day.selected,
        }"
        :title="day.key"
        :disabled="disabledKey(day.key)"
        @click="pick(day.key)"
      >
        {{ day.day }}
      </button>
    </div>
    <div class="kiwi-calendar-foot">
      <button type="button" class="kiwi-calendar-quick" @click="goToday">今天</button>
      <button
        v-if="clearable && hasValue"
        type="button"
        class="kiwi-calendar-quick is-muted"
        @click="clear"
      >
        清除
      </button>
      <span v-if="hint" class="kiwi-calendar-hint">{{ hint }}</span>
    </div>
  </div>
</template>

<style scoped>
.kiwi-calendar-panel {
  width: 264px;
  padding: 10px;
  border: 1px solid rgb(var(--theme-border) / 0.9);
  border-radius: 14px;
  background: rgb(var(--theme-surface));
  box-shadow:
    0 18px 44px rgb(var(--theme-text-primary) / 0.16),
    0 2px 8px rgb(var(--theme-text-primary) / 0.06);
  font-family: inherit;
  user-select: none;
  animation: kiwi-calendar-in 0.14s ease;
}
@keyframes kiwi-calendar-in {
  from {
    opacity: 0;
    transform: translateY(-4px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}
.kiwi-calendar-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
  padding: 2px 2px 8px;
}
.kiwi-calendar-month {
  font-size: 12.5px;
  font-weight: 600;
  color: rgb(var(--theme-text-strong));
  font-variant-numeric: tabular-nums;
}
.kiwi-calendar-nav {
  display: grid;
  place-items: center;
  width: 24px;
  height: 24px;
  border-radius: 7px;
  color: rgb(var(--theme-text-muted));
  transition: background 0.15s ease, color 0.15s ease;
}
.kiwi-calendar-nav:hover {
  background: rgb(var(--theme-accent) / 0.1);
  color: rgb(var(--theme-accent));
}
.kiwi-calendar-week,
.kiwi-calendar-grid {
  display: grid;
  grid-template-columns: repeat(7, 1fr);
  gap: 2px;
}
.kiwi-calendar-week {
  padding-bottom: 4px;
  font-size: 10px;
  color: rgb(var(--theme-text-subtle));
  text-align: center;
}
.kiwi-calendar-day {
  height: 30px;
  border-radius: 8px;
  font-size: 12px;
  color: rgb(var(--theme-text-secondary));
  font-variant-numeric: tabular-nums;
  transition: background 0.12s ease, color 0.12s ease;
}
.kiwi-calendar-day:hover {
  background: rgb(var(--theme-accent) / 0.1);
  color: rgb(var(--theme-accent));
}
.kiwi-calendar-day.is-outside {
  color: rgb(var(--theme-text-faint));
}
.kiwi-calendar-day.is-today {
  box-shadow: inset 0 0 0 1px rgb(var(--theme-accent) / 0.45);
  font-weight: 600;
}
.kiwi-calendar-day.is-selected {
  background: rgb(var(--theme-accent));
  color: rgb(var(--theme-accent-foreground, 255 255 255));
  font-weight: 600;
  box-shadow: none;
}
.kiwi-calendar-day:disabled {
  cursor: not-allowed;
  opacity: 0.35;
}
.kiwi-calendar-day:disabled:hover {
  background: transparent;
  color: rgb(var(--theme-text-secondary));
}
.kiwi-calendar-foot {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px solid rgb(var(--theme-border-subtle) / 0.9);
}
.kiwi-calendar-quick {
  padding: 3px 9px;
  border-radius: 7px;
  background: rgb(var(--theme-accent) / 0.1);
  color: rgb(var(--theme-accent));
  font-size: 11px;
}
.kiwi-calendar-quick:hover {
  background: rgb(var(--theme-accent) / 0.16);
}
.kiwi-calendar-quick.is-muted {
  background: rgb(var(--theme-surface-muted));
  color: rgb(var(--theme-text-muted));
}
.kiwi-calendar-quick.is-muted:hover {
  color: rgb(var(--theme-text-secondary));
}
.kiwi-calendar-hint {
  margin-left: auto;
  font-size: 10px;
  color: rgb(var(--theme-text-subtle));
  white-space: nowrap;
}
</style>

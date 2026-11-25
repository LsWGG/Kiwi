<script setup lang="ts">
/**
 * 系统时间选择器：替代浏览器原生 <input type="time">。
 * 面板分为「小时 / 分钟」两段；小时点击后保持打开，分钟点击后关闭。
 */
import { computed } from 'vue'
import KiwiDropdown from './KiwiDropdown.vue'
import KiwiIcon from './KiwiIcon.vue'

const props = withDefaults(
  defineProps<{
    modelValue: string
    minuteStep?: number
    disabled?: boolean
    ariaLabel?: string
    width?: string
  }>(),
  {
    modelValue: '09:00',
    minuteStep: 5,
    disabled: false,
    ariaLabel: '选择时间',
    width: 'w-60',
  },
)

const emit = defineEmits<{ (e: 'update:modelValue', value: string): void }>()

function parse(value: string): [number, number] {
  const match = /^([01]?\d|2[0-3]):([0-5]\d)$/.exec(String(value || '').trim())
  if (!match) return [9, 0]
  return [Number(match[1]), Number(match[2])]
}

const current = computed(() => parse(props.modelValue))
const hour = computed(() => current.value[0])
const minute = computed(() => current.value[1])
const display = computed(
  () => `${String(hour.value).padStart(2, '0')}:${String(minute.value).padStart(2, '0')}`,
)
const hours = Array.from({ length: 24 }, (_, index) => index)
const minutes = computed(() => {
  const step = Math.max(1, Math.min(30, props.minuteStep))
  const values: number[] = []
  for (let value = 0; value < 60; value += step) values.push(value)
  if (!values.includes(minute.value)) values.push(minute.value)
  values.sort((a, b) => a - b)
  return values
})

function chooseHour(value: number) {
  emit('update:modelValue', `${String(value).padStart(2, '0')}:${String(minute.value).padStart(2, '0')}`)
}

function chooseMinute(value: number, close: () => void) {
  emit('update:modelValue', `${String(hour.value).padStart(2, '0')}:${String(value).padStart(2, '0')}`)
  close()
}
</script>

<template>
  <KiwiDropdown :width="width" :disabled="disabled" align="left">
    <template #trigger="{ open }">
      <button
        type="button"
        class="kiwi-time-trigger kiwi-input inline-flex h-9 w-full items-center gap-1.5 !py-0 text-left transition-colors disabled:cursor-not-allowed disabled:opacity-50"
        :class="open ? 'is-open' : ''"
        :disabled="disabled"
        :aria-label="ariaLabel"
        aria-haspopup="dialog"
        :aria-expanded="open"
      >
        <KiwiIcon name="clock" :size="12" class="shrink-0 text-slate-400" />
        <span class="min-w-0 flex-1 font-mono text-[12px] text-slate-600">{{ display }}</span>
        <KiwiIcon
          name="chevron"
          :size="9"
          class="shrink-0 text-slate-400 transition-transform"
          :class="open ? 'rotate-180' : ''"
        />
      </button>
    </template>

    <template #default="{ close }">
      <div role="dialog" :aria-label="ariaLabel">
        <div class="flex items-center justify-between px-2 py-1">
          <span class="text-[10px] font-medium uppercase tracking-wide text-slate-400">小时</span>
          <span class="font-mono text-[11px] text-kiwi-700">{{ display }}</span>
        </div>
        <div class="grid grid-cols-6 gap-1 px-1">
          <button
            v-for="value in hours"
            :key="value"
            type="button"
            class="kiwi-time-cell rounded-md py-1 font-mono text-[11px] transition-colors"
            :class="value === hour ? 'is-selected' : ''"
            :aria-label="`${String(value).padStart(2, '0')} 时`"
            @click="chooseHour(value)"
          >
            {{ String(value).padStart(2, '0') }}
          </button>
        </div>
        <div class="mt-2 border-t border-slate-200/60 px-2 pt-1.5 text-[10px] font-medium uppercase tracking-wide text-slate-400">
          分钟
        </div>
        <div class="grid grid-cols-6 gap-1 px-1">
          <button
            v-for="value in minutes"
            :key="value"
            type="button"
            class="kiwi-time-cell rounded-md py-1 font-mono text-[11px] transition-colors"
            :class="value === minute ? 'is-selected' : ''"
            :aria-label="`${String(value).padStart(2, '0')} 分`"
            @click="chooseMinute(value, close)"
          >
            {{ String(value).padStart(2, '0') }}
          </button>
        </div>
      </div>
    </template>
  </KiwiDropdown>
</template>

<style scoped>
.kiwi-time-trigger.is-open {
  border-color: rgb(var(--theme-accent) / 0.5);
  box-shadow: 0 0 0 2px rgb(var(--theme-accent) / 0.16);
}
.kiwi-time-cell {
  color: rgb(var(--theme-text-secondary, 100 116 139));
}
.kiwi-time-cell:hover {
  background: rgb(var(--theme-accent) / 0.08);
}
.kiwi-time-cell.is-selected {
  background: rgb(var(--theme-accent) / 0.12);
  color: rgb(var(--theme-accent));
  font-weight: 600;
}
</style>

<script setup lang="ts">
/**
 * 系统多选器：触发器样式与 KiwiSelect 一致，面板为可勾选的行列表。
 * 点击选项不关闭面板，底部「完成」或点击外部关闭。
 */
import { computed } from 'vue'
import KiwiDropdown from './KiwiDropdown.vue'
import KiwiIcon from './KiwiIcon.vue'

export interface KiwiMultiSelectOption {
  value: string | number
  label: string
  hint?: string
  icon?: string
}

const props = withDefaults(
  defineProps<{
    modelValue: Array<string | number>
    options: KiwiMultiSelectOption[]
    placeholder?: string
    disabled?: boolean
    width?: string
    ariaLabel?: string
    /** 已选超过 1 个时，触发器显示「首个 等 N 个」。 */
    maxLabels?: number
  }>(),
  {
    modelValue: () => [],
    options: () => [],
    placeholder: '请选择',
    disabled: false,
    width: 'w-64',
    ariaLabel: '',
    maxLabels: 1,
  },
)

const emit = defineEmits<{ (e: 'update:modelValue', value: Array<string | number>): void }>()

const selected = computed(() => new Set(props.modelValue.map((item) => String(item))))
const labels = computed(() =>
  props.options
    .filter((option) => selected.value.has(String(option.value)))
    .map((option) => option.label),
)
const display = computed(() => {
  if (!labels.value.length) return props.placeholder
  if (labels.value.length === 1) return labels.value[0]
  if (props.maxLabels > 1) {
    return `${labels.value.slice(0, props.maxLabels).join('、')} 等 ${labels.value.length} 个`
  }
  return `${labels.value[0]} 等 ${labels.value.length} 个`
})

function toggle(value: string | number) {
  if (props.disabled) return
  const key = String(value)
  const next = props.modelValue.filter((item) => String(item) !== key)
  if (next.length === props.modelValue.length) next.push(value)
  emit('update:modelValue', next)
}

function clear() {
  emit('update:modelValue', [])
}
</script>

<template>
  <KiwiDropdown :width="width" :disabled="disabled" align="left">
    <template #trigger="{ open }">
      <button
        type="button"
        class="kiwi-multi-trigger kiwi-input inline-flex h-9 w-full items-center gap-1 !py-0 text-left transition-colors disabled:cursor-not-allowed disabled:opacity-50"
        :class="open ? 'is-open' : ''"
        :disabled="disabled"
        :aria-label="ariaLabel || placeholder"
        aria-haspopup="listbox"
        :aria-expanded="open"
      >
        <span class="min-w-0 flex-1 truncate text-[12px] text-slate-600">
          {{ display }}
        </span>
        <KiwiIcon
          name="chevron"
          :size="9"
          class="shrink-0 text-slate-400 transition-transform"
          :class="open ? 'rotate-180' : ''"
        />
      </button>
    </template>

    <template #default="{ close }">
      <div role="listbox" aria-multiselectable="true" :aria-label="ariaLabel || placeholder">
        <div class="flex items-center justify-between px-2 py-1">
          <span class="text-[10px] font-medium uppercase tracking-wide text-slate-400">
            已选 {{ modelValue.length }} 个
          </span>
          <button
            v-if="modelValue.length"
            type="button"
            class="text-[10px] text-slate-400 transition-colors hover:text-slate-600"
            @click="clear"
          >
            清空
          </button>
        </div>
        <button
          v-for="option in options"
          :key="String(option.value)"
          type="button"
          role="option"
          :aria-selected="selected.has(String(option.value))"
          class="kiwi-multi-option flex w-full items-center gap-2.5 rounded-lg px-2 py-1.5 text-left transition-colors"
          :class="selected.has(String(option.value)) ? 'is-selected' : ''"
          @click="toggle(option.value)"
        >
          <span
            class="grid h-3.5 w-3.5 shrink-0 place-items-center rounded border transition-colors"
            :class="
              selected.has(String(option.value))
                ? 'border-transparent bg-kiwi-500 text-white'
                : 'border-slate-300 text-transparent'
            "
          >
            <KiwiIcon name="check" :size="9" />
          </span>
          <KiwiIcon v-if="option.icon" :name="option.icon" :size="13" class="shrink-0 text-slate-400" />
          <span class="min-w-0 flex-1">
            <span class="block truncate text-[12px] font-medium text-slate-700">
              {{ option.label }}
            </span>
            <span v-if="option.hint" class="block truncate text-[10px] text-slate-400">
              {{ option.hint }}
            </span>
          </span>
        </button>
        <p v-if="!options.length" class="px-2 py-2 text-[11px] text-slate-400">暂无可选项</p>
        <div class="mt-1 border-t border-slate-200/60 px-2 pb-0.5 pt-1">
          <button
            type="button"
            class="w-full rounded-md px-2 py-1 text-[11px] font-medium text-kiwi-700 transition-colors hover:bg-kiwi-50"
            @click="close"
          >
            完成
          </button>
        </div>
      </div>
    </template>
  </KiwiDropdown>
</template>

<style scoped>
.kiwi-multi-trigger.is-open {
  border-color: rgb(var(--theme-accent) / 0.5);
  box-shadow: 0 0 0 2px rgb(var(--theme-accent) / 0.16);
}
.kiwi-multi-option:hover {
  background: rgb(var(--theme-accent) / 0.08);
}
.kiwi-multi-option.is-selected {
  background: rgb(var(--theme-accent) / 0.1);
}
</style>

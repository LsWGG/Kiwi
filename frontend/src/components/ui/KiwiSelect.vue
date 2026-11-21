<script setup lang="ts">
/**
 * 系统统一选择器：触发器 + 与「扩展组件」一致的玻璃面板。
 * 用于替换原生 <select>，避免浏览器默认下拉在深色 / 玻璃主题中突兀。
 */
import { computed } from 'vue'
import KiwiDropdown from './KiwiDropdown.vue'
import KiwiIcon from './KiwiIcon.vue'

export interface KiwiSelectOption {
  value: string | number
  label: string
  hint?: string
  icon?: string
}

const props = withDefaults(
  defineProps<{
    modelValue: string | number | null | undefined
    options: KiwiSelectOption[]
    placeholder?: string
    disabled?: boolean
    title?: string
    /** toolbar：编辑器工具栏紧凑样式；input：表单输入框样式 */
    variant?: 'toolbar' | 'input'
    width?: string
    ariaLabel?: string
    /** 触发器额外 class，便于嵌入表格 / 筛选栏时沿用容器样式 */
    triggerClass?: string
  }>(),
  {
    modelValue: '',
    placeholder: '请选择',
    disabled: false,
    title: '',
    variant: 'toolbar',
    width: 'w-52',
    ariaLabel: '',
    triggerClass: '',
  },
)

const emit = defineEmits<{ (e: 'update:modelValue', value: string | number): void }>()

const selected = computed(
  () => props.options.find((item) => String(item.value) === String(props.modelValue)) ?? null,
)
const display = computed(() => selected.value?.label ?? props.placeholder)
const isToolbar = computed(() => props.variant === 'toolbar')

function choose(value: string | number, close: () => void) {
  if (props.disabled) return
  emit('update:modelValue', value)
  close()
}
</script>

<template>
  <KiwiDropdown :width="width" align="left">
    <template #trigger="{ open }">
      <button
        type="button"
        class="kiwi-select-trigger inline-flex items-center gap-1 text-left transition-colors disabled:cursor-not-allowed disabled:opacity-50"
        :class="[
          isToolbar
            ? 'is-toolbar h-7 max-w-full rounded-lg px-1.5 text-[11px] text-slate-600'
            : 'is-input kiwi-input h-9 w-full justify-between !py-0',
          open ? 'is-open' : '',
          triggerClass,
        ]"
        :disabled="disabled"
        :title="title || display"
        :aria-label="ariaLabel || title || display"
        aria-haspopup="listbox"
        :aria-expanded="open"
      >
        <KiwiIcon v-if="selected?.icon" :name="selected.icon" :size="13" class="shrink-0 text-slate-400" />
        <span class="min-w-0 flex-1 truncate">{{ display }}</span>
        <KiwiIcon
          name="chevron"
          :size="9"
          class="shrink-0 text-slate-400 transition-transform"
          :class="open ? 'rotate-180' : ''"
        />
      </button>
    </template>
    <template #default="{ close }">
      <div role="listbox" :aria-label="ariaLabel || title || placeholder">
        <button
          v-for="option in options"
          :key="String(option.value)"
          type="button"
          role="option"
          :aria-selected="String(option.value) === String(modelValue)"
          class="kiwi-select-option flex w-full items-center gap-2.5 rounded-lg px-2 py-1.5 text-left transition-colors"
          :class="String(option.value) === String(modelValue) ? 'is-selected' : ''"
          @click="choose(option.value, close)"
        >
          <span class="kiwi-select-check grid w-3.5 shrink-0 place-items-center">
            <KiwiIcon v-if="String(option.value) === String(modelValue)" name="check" :size="12" />
          </span>
          <KiwiIcon v-if="option.icon" :name="option.icon" :size="13" class="shrink-0 text-slate-400" />
          <span class="min-w-0 flex-1">
            <span
              class="kiwi-select-label block truncate text-[12px] font-medium text-slate-700"
            >{{ option.label }}</span>
            <span v-if="option.hint" class="block truncate text-[10px] text-slate-400">
              {{ option.hint }}
            </span>
          </span>
        </button>
        <p v-if="!options.length" class="px-2 py-2 text-[11px] text-slate-400">暂无可选项</p>
      </div>
    </template>
  </KiwiDropdown>
</template>

<style scoped>
/* 选择器全部使用主题令牌：主题插件与「自定义外观」强调色都能生效。 */
.kiwi-select-trigger.is-toolbar:hover,
.kiwi-select-trigger.is-toolbar.is-open {
  background: rgb(var(--theme-accent) / 0.1);
  color: rgb(var(--theme-text-strong));
}
.kiwi-select-trigger.is-input.is-open {
  border-color: rgb(var(--theme-accent) / 0.5);
  box-shadow: 0 0 0 2px rgb(var(--theme-accent) / 0.16);
}
.kiwi-select-option:hover {
  background: rgb(var(--theme-accent) / 0.08);
}
.kiwi-select-option.is-selected {
  background: rgb(var(--theme-accent) / 0.1);
}
.kiwi-select-option.is-selected .kiwi-select-label,
.kiwi-select-check {
  color: rgb(var(--theme-accent));
}
</style>

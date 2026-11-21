<script setup lang="ts">
/**
 * 系统统一日期选择：主题化触发器 + 共享月历面板，替代原生 date 输入框。
 * v-model 使用 YYYY-MM-DD 字符串；清空时输出空字符串。
 */
import { computed } from 'vue'
import KiwiDropdown from './KiwiDropdown.vue'
import KiwiIcon from './KiwiIcon.vue'
import KiwiCalendarPanel from './KiwiCalendarPanel.vue'

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
    /** 面板底部提示；传空字符串可隐藏。 */
    hint?: string
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
    hint: '选择日期后立即生效',
  },
)

const emit = defineEmits<{ (e: 'update:modelValue', value: string): void }>()

const selectedKey = computed(() => String(props.modelValue || ''))
const display = computed(() => selectedKey.value || props.placeholder)
const hasValue = computed(() => !!selectedKey.value)
</script>

<template>
  <KiwiDropdown
    width="w-[264px]"
    align="left"
    panel-class="!overflow-visible !border-0 !bg-transparent !p-0 !shadow-none !backdrop-blur-none"
  >
    <template #trigger="{ open }">
      <button
        type="button"
        class="kiwi-date-trigger flex h-8 w-full items-center gap-1.5 rounded-lg px-2 text-left text-[11px] outline-none transition-colors disabled:cursor-not-allowed disabled:opacity-50"
        :class="[triggerClass, open ? 'is-open' : '', !hasValue ? 'is-empty' : '']"
        :disabled="disabled"
        :title="title || display"
        :aria-label="title || placeholder"
        aria-haspopup="dialog"
        :aria-expanded="open"
      >
        <KiwiIcon name="calendar" :size="13" class="kiwi-date-trigger-icon shrink-0" />
        <span class="min-w-0 flex-1 truncate tabular-nums">{{ display }}</span>
        <KiwiIcon
          v-if="clearable && hasValue"
          name="close"
          :size="11"
          class="kiwi-date-trigger-clear shrink-0"
          title="清除日期"
          @click.stop="emit('update:modelValue', '')"
        />
      </button>
    </template>
    <template #default="{ close }">
      <KiwiCalendarPanel
        :model-value="selectedKey"
        :min="min"
        :max="max"
        :clearable="clearable"
        :hint="hint"
        @update:model-value="emit('update:modelValue', $event)"
        @close="close"
      />
    </template>
  </KiwiDropdown>
</template>

<style scoped>
.kiwi-date-trigger {
  border: 1px solid rgb(var(--theme-border) / 0.9);
  background: rgb(var(--theme-surface) / calc(0.8 * var(--theme-surface-opacity)));
  color: rgb(var(--theme-text-secondary));
}
.kiwi-date-trigger:hover {
  border-color: rgb(var(--theme-accent) / 0.35);
}
.kiwi-date-trigger:focus-visible,
.kiwi-date-trigger.is-open {
  border-color: rgb(var(--theme-accent) / 0.55);
  box-shadow: 0 0 0 2px rgb(var(--theme-accent) / 0.16);
}
.kiwi-date-trigger.is-empty {
  color: rgb(var(--theme-text-subtle));
}
.kiwi-date-trigger-icon {
  color: rgb(var(--theme-text-subtle));
}
.kiwi-date-trigger-clear {
  color: rgb(var(--theme-text-subtle));
}
.kiwi-date-trigger-clear:hover {
  color: rgb(var(--theme-text-strong));
}
</style>

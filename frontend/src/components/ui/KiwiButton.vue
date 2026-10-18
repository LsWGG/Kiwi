<script setup lang="ts">
// KiwiButton：统一按钮变体。含 loading（spinner + 禁用）。
import KiwiIcon from './KiwiIcon.vue'

withDefaults(
  defineProps<{
    variant?: 'primary' | 'secondary' | 'ghost' | 'danger'
    loading?: boolean
    disabled?: boolean
    type?: string
  }>(),
  { variant: 'primary', loading: false, disabled: false, type: 'button' },
)

const classMap: Record<string, string> = {
  primary: 'kiwi-btn-primary',
  secondary: 'kiwi-btn-secondary',
  ghost: 'kiwi-btn-ghost',
  danger: 'kiwi-btn-danger',
}
</script>

<template>
  <button
    :type="(type as 'button') || 'button'"
    :class="classMap[variant]"
    :disabled="disabled || loading"
    class="kiwi-base"
  >
    <KiwiIcon v-if="loading" name="loader" :size="15" spin class="shrink-0" />
    <slot />
  </button>
</template>

<style scoped>
.kiwi-base {
  position: relative;
}
</style>
<script setup lang="ts">
// KiwiProgress：线性进度条（带流光与完成态）。
import { computed } from 'vue'

const props = withDefaults(
  defineProps<{ value: number; status?: 'running' | 'done' | 'error' }>(),
  { value: 0, status: 'running' },
)

const pct = computed(() => Math.min(Math.max(props.value, 0), 1) * 100)

const barClass = computed(() =>
  props.status === 'error'
    ? 'from-rose-500 to-rose-600'
    : props.status === 'done'
      ? 'from-emerald-500 to-emerald-600'
      : 'from-kiwi-500 to-kiwi-700',
)
</script>

<template>
  <div class="w-full">
    <div class="h-2 rounded-full bg-slate-200/50 overflow-hidden">
      <div
        class="h-full rounded-full bg-gradient-to-r transition-[width] duration-500 ease-out"
        :class="[barClass, status === 'running' && 'relative overflow-hidden']"
        :style="{ width: `${pct}%` }"
      >
        <div
          v-if="status === 'running'"
          class="absolute inset-0 animate-shimmer"
          style="background: linear-gradient(90deg, transparent, rgba(255,255,255,0.5), transparent); background-size: 200% 100%;"
        />
      </div>
    </div>
  </div>
</template>
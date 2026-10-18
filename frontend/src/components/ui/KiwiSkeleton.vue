<script setup lang="ts">
// 骨架屏：基础 row 与卡片变体。
const props = withDefaults(
  defineProps<{ variant?: 'row' | 'card' | 'stat'; cols?: number }>(),
  { variant: 'card', cols: 3 },
)
</script>

<template>
  <div v-if="variant === 'row'" class="space-y-2.5">
    <div v-for="i in cols" :key="i" class="h-4 rounded-md shimmer bg-slate-200/60" :style="{ width: `${100 - i * 6}%` }" />
  </div>

  <div v-else-if="variant === 'stat'" class="grid gap-4" :style="{ gridTemplateColumns: `repeat(${cols}, minmax(0,1fr))` }">
    <div v-for="i in cols" :key="i" class="kiwi-card p-5 space-y-3">
      <div class="h-4 w-20 rounded-md shimmer bg-slate-200/60" />
      <div class="h-8 w-16 rounded-lg shimmer bg-slate-200/60" />
    </div>
  </div>

  <div v-else class="grid gap-4" :style="{ gridTemplateColumns: `repeat(${cols}, minmax(0,1fr))` }">
    <div v-for="i in cols" :key="i" class="kiwi-card p-5 space-y-3">
      <div class="h-5 w-2/3 rounded-md shimmer bg-slate-200/60" />
      <div class="h-3 w-full rounded shimmer bg-slate-200/40" />
      <div class="h-3 w-4/5 rounded shimmer bg-slate-200/40" />
    </div>
  </div>
</template>

<style scoped>
.shimmer {
  background: linear-gradient(90deg, rgba(226, 232, 240, 0.5) 25%, rgba(226, 232, 240, 0.9) 50%, rgba(226, 232, 240, 0.5) 75%);
  background-size: 200% 100%;
  animation: shimmer 1.6s linear infinite;
}
@keyframes shimmer {
  0% { background-position: -200% 0; }
  100% { background-position: 200% 0; }
}
</style>
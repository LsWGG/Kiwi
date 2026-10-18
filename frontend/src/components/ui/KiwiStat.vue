<script setup lang="ts">
// KiwiStat：数字滚动统计卡（count-up）。受 IntersectionObserver 触发。
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'

const props = withDefaults(
  defineProps<{
    label: string
    value: number
    icon?: string
    accent?: 'kiwi' | 'emerald' | 'amber' | 'slate'
  }>(),
  { accent: 'kiwi' },
)

const el = ref<HTMLElement>()
const shown = ref(0)
const inView = ref(false)

const accentClass: Record<string, string> = {
  kiwi: 'from-kiwi-500/20 to-kiwi-100/40 text-kiwi-700',
  emerald: 'from-emerald-500/20 to-emerald-100/40 text-emerald-700',
  amber: 'from-amber-500/20 to-amber-100/40 text-amber-700',
  slate: 'from-slate-500/20 to-slate-100/40 text-slate-700',
}

let observer: IntersectionObserver | undefined
let raf = 0

function animate(to: number) {
  const start = shown.value
  const t0 = performance.now()
  const dur = 700
  const step = (now: number) => {
    const p = Math.min((now - t0) / dur, 1)
    const eased = 1 - Math.pow(1 - p, 3)
    shown.value = Math.round(start + (to - start) * eased)
    if (p < 1) raf = requestAnimationFrame(step)
  }
  raf = requestAnimationFrame(step)
}

watch(
  () => props.value,
  (v) => { if (inView.value) animate(v) },
)

onMounted(() => {
  observer = new IntersectionObserver(
    ([entry]) => {
      if (entry.isIntersecting) {
        inView.value = true
        animate(props.value)
        observer?.disconnect()
      }
    },
    { threshold: 0.3 },
  )
  if (el.value) observer.observe(el.value)
})

onUnmounted(() => {
  observer?.disconnect()
  cancelAnimationFrame(raf)
})
</script>

<template>
  <div ref="el" class="kiwi-card p-5 flex items-start gap-4">
    <div
      class="w-10 h-10 rounded-xl bg-gradient-to-br grid place-items-center shrink-0 border border-white/60"
      :class="accentClass[accent]"
    >
      <slot name="icon" />
    </div>
    <div class="min-w-0">
      <p class="text-3xl font-bold tabular-nums text-slate-800 leading-none">{{ shown }}</p>
      <p class="text-xs text-slate-500 mt-1.5">{{ label }}</p>
    </div>
  </div>
</template>
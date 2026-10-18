<script setup lang="ts">
import { toasts, dismiss } from './toast'
import KiwiIcon from './KiwiIcon.vue'

const badge = (t: string) => (t === 'success' ? 'check' : t === 'error' ? 'alert' : 'sparkle')
const badgeClass = (t: string) =>
  t === 'success'
    ? 'text-emerald-600 bg-emerald-50'
    : t === 'error'
      ? 'text-rose-600 bg-rose-50'
      : 'text-kiwi-600 bg-kiwi-50'
</script>

<template>
  <Teleport to="body">
    <div class="fixed bottom-6 right-6 z-[100] flex flex-col gap-2 items-end pointer-events-none">
      <TransitionGroup
        enter-active-class="transition-all duration-300 ease-spring"
        enter-from-class="opacity-0 translate-y-3 scale-95"
        leave-active-class="transition-all duration-200"
        leave-to-class="opacity-0 translate-x-4"
      >
        <div
          v-for="t in toasts"
          :key="t.id"
          class="pointer-events-auto flex items-center gap-2.5 px-4 py-2.5 rounded-xl glass-strong shadow-lifted min-w-[220px] max-w-sm"
          @click="dismiss(t.id)"
        >
          <span class="w-6 h-6 rounded-lg grid place-items-center shrink-0" :class="badgeClass(t.type)">
            <KiwiIcon :name="badge(t.type)" :size="14" />
          </span>
          <span class="text-sm text-slate-700">{{ t.message }}</span>
        </div>
      </TransitionGroup>
    </div>
  </Teleport>
</template>
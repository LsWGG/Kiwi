<script setup lang="ts">
import KiwiIcon from './KiwiIcon.vue'

defineProps<{
  icon?: string
  title: string
  desc?: string
}>()
</script>

<template>
  <div class="flex flex-col items-center justify-center py-16 text-center animate-fade-up">
    <div
      class="w-16 h-16 rounded-2xl bg-gradient-to-br from-kiwi-100 to-kiwi-50 border border-kiwi-100 grid place-items-center text-kiwi-400 mb-4 shadow-soft"
    >
      <KiwiIcon :name="icon || 'sparkle'" :size="30" />
    </div>
    <h3 class="font-medium text-slate-600">{{ title }}</h3>
    <p v-if="desc" class="text-sm text-slate-400 mt-1 max-w-xs">{{ desc }}</p>
    <div class="mt-5 flex gap-3">
      <slot />
    </div>
  </div>
</template>
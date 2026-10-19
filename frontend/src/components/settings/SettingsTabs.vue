<script setup lang="ts">
import { useRoute } from 'vue-router'
import KiwiIcon from '@/components/ui/KiwiIcon.vue'

const route = useRoute()

const tabs = [
  { path: '/settings', label: '大模型配置', icon: 'sparkle' },
  { path: '/settings/embedding', label: '向量模型', icon: 'layers' },
  { path: '/settings/brand', label: '品牌', icon: 'palette' },
  { path: '/settings/ocr', label: 'OCR', icon: 'scanText' },
]
</script>

<template>
  <nav
    class="inline-flex items-center gap-1 p-1 rounded-xl bg-white/60 border border-slate-200/70 mb-6"
    aria-label="设置分类"
  >
    <RouterLink
      v-for="tab in tabs"
      :key="tab.path"
      :to="tab.path"
      class="flex items-center gap-1.5 px-3.5 py-2 rounded-lg text-sm font-medium transition-colors"
      :class="
        route.path === tab.path
          ? 'bg-white text-kiwi-700 shadow-sm'
          : 'text-slate-500 hover:text-slate-700'
      "
      :aria-current="route.path === tab.path ? 'page' : undefined"
    >
      <KiwiIcon :name="tab.icon" :size="15" />
      {{ tab.label }}
    </RouterLink>
  </nav>
</template>

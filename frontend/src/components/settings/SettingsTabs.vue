<script setup lang="ts">
/** 设置页统一导航：品牌 / 模型（大模型·向量·OCR）/ 运维 / 插件与区块。 */
import { useRoute } from 'vue-router'
import KiwiIcon from '@/components/ui/KiwiIcon.vue'
import { IS_DESKTOP } from '@/desktop/env'

const route = useRoute()

const tabs = [
  { path: '/settings', label: '品牌', icon: 'palette' },
  { path: '/settings/models', label: '模型', icon: 'sparkle' },
  { path: '/settings/operations', label: '运维', icon: 'server' },
  { path: '/settings/plugins', label: '插件与区块', icon: 'puzzle' },
  ...(IS_DESKTOP ? [{ path: '/settings/desktop', label: '桌面', icon: 'monitor' }] : []),
]

/** 模型页使用 ?tab= 切换子页，父级导航仍保持高亮。 */
function isActive(path: string) {
  return route.path === path
}
</script>

<template>
  <nav
    class="mb-6 flex w-full items-center gap-1 overflow-x-auto rounded-2xl border border-slate-200/70 bg-white/60 p-1 backdrop-blur-xl"
    aria-label="设置分类"
  >
    <RouterLink
      v-for="tab in tabs"
      :key="tab.path"
      :to="tab.path"
      class="group flex shrink-0 items-center gap-2 rounded-xl px-3.5 py-2 text-[12.5px] font-medium transition-all"
      :class="
        isActive(tab.path)
          ? 'bg-white text-kiwi-700 shadow-soft ring-1 ring-kiwi-100'
          : 'text-slate-500 hover:bg-white/70 hover:text-slate-700'
      "
      :aria-current="isActive(tab.path) ? 'page' : undefined"
    >
      <span
        class="grid h-6 w-6 place-items-center rounded-lg transition-colors"
        :class="
          isActive(tab.path)
            ? 'bg-kiwi-50 text-kiwi-600'
            : 'bg-slate-100/80 text-slate-400 group-hover:text-slate-500'
        "
      >
        <KiwiIcon :name="tab.icon" :size="13" />
      </span>
      {{ tab.label }}
    </RouterLink>
  </nav>
</template>

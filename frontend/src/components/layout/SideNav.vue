<script setup lang="ts">
import { RouterLink, useRoute } from 'vue-router'
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import KiwiIcon from '@/components/ui/KiwiIcon.vue'

const route = useRoute()
const items = [
  { to: '/kbs', icon: 'database', label: '知识库' },
  { to: '/notes', icon: 'note', label: '笔记' },
  { to: '/wiki', icon: 'wiki', label: 'Wiki' },
  { to: '/sources', icon: 'bookOpen', label: '编译任务' },
  { to: '/chat', icon: 'chat', label: '问答' },
]

const active = computed(() => {
  for (const it of items) {
    if (route.path.startsWith(it.to)) return it.to
  }
  return ''
})

// ---------- 独立收起 / 展开 ----------
const STORAGE_KEY = 'kiwi.sidenav.collapsed'
const collapsed = ref((() => {
  try {
    return localStorage.getItem(STORAGE_KEY) === '1'
  } catch {
    return false
  }
})())

watch(collapsed, (value) => {
  try {
    localStorage.setItem(STORAGE_KEY, value ? '1' : '0')
  } catch {
    /* 隐私模式下忽略 */
  }
})

/** 窄屏强制收起为图标轨道，把横向空间留给笔记正文。 */
const narrow = ref(false)
let narrowQuery: MediaQueryList | null = null
const isCollapsed = computed(() => collapsed.value || narrow.value)

function onNarrowChange(event: MediaQueryListEvent) {
  narrow.value = event.matches
}

onMounted(() => {
  narrowQuery = window.matchMedia('(max-width: 767px)')
  narrow.value = narrowQuery.matches
  narrowQuery.addEventListener('change', onNarrowChange)
})
onBeforeUnmount(() => narrowQuery?.removeEventListener('change', onNarrowChange))

function toggle() {
  collapsed.value = !collapsed.value
}
</script>

<template>
  <nav
    class="shrink-0 sidebar-glass h-full flex flex-col py-3 gap-0.5 overflow-visible transition-[width] duration-300 ease-out"
    :class="isCollapsed ? 'w-14' : 'w-44'"
  >
    <RouterLink
      v-for="it in items"
      :key="it.to"
      :to="it.to"
      :title="isCollapsed ? it.label : undefined"
      class="group relative rounded-xl flex items-center gap-2.5 text-sm transition-all duration-200"
      :class="[
        isCollapsed ? 'mx-2 justify-center px-0 py-2.5' : 'mx-2 px-3 py-2',
        active === it.to
          ? 'text-kiwi-700 font-medium'
          : 'text-slate-500 hover:text-slate-700 hover:bg-white/50',
      ]"
    >
      <!-- 活动高亮胶囊 -->
      <span
        class="absolute inset-0 -z-0 rounded-xl bg-gradient-to-r from-kiwi-100/90 to-kiwi-50/60 border border-kiwi-200/50 shadow-soft transition-all duration-300"
        :class="active === it.to ? 'opacity-100 scale-100' : 'opacity-0 scale-95'"
      />
      <span
        class="relative z-[1] grid place-items-center transition-transform duration-200 group-hover:scale-110"
      >
        <KiwiIcon
          :name="it.icon"
          :size="17"
          class="transition-colors duration-200"
          :class="active === it.to ? 'text-kiwi-600' : 'text-slate-400 group-hover:text-slate-600'"
        />
      </span>
      <span v-if="!isCollapsed" class="relative z-[1] whitespace-nowrap">{{ it.label }}</span>
    </RouterLink>

    <!-- 独立收起按钮：窄屏固定为图标轨道，不提供展开 -->
    <div v-if="!narrow" class="mt-auto px-2 pt-2">
      <button
        type="button"
        class="flex w-full items-center gap-2.5 rounded-xl py-2 text-[11px] text-slate-400 transition-colors hover:bg-white/50 hover:text-slate-600"
        :class="isCollapsed ? 'justify-center px-0' : 'px-3'"
        :title="isCollapsed ? '展开菜单' : '收起菜单'"
        @click="toggle"
      >
        <KiwiIcon :name="isCollapsed ? 'panelLeftOpen' : 'panelLeftClose'" :size="16" />
        <span v-if="!isCollapsed" class="whitespace-nowrap">收起菜单</span>
      </button>
    </div>
  </nav>
</template>

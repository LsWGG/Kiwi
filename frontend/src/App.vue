<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, watch } from 'vue'
import { RouterLink, RouterView } from 'vue-router'
import { useKbsStore } from '@/stores/kbs'
import { useModeStore } from '@/stores/mode'
import { useRoute } from 'vue-router'
import ModeSwitcher from '@/components/layout/ModeSwitcher.vue'
import SideNav from '@/components/layout/SideNav.vue'
import LearnSideNav from '@/components/study/LearnSideNav.vue'
import KbSwitcher from '@/components/layout/KbSwitcher.vue'
import KiwiIcon from '@/components/ui/KiwiIcon.vue'
import KiwiToastHost from '@/components/ui/KiwiToastHost.vue'

const kbs = useKbsStore()
const mode = useModeStore()
const route = useRoute()

/**
 * 学习模式使用青绿主题色，编辑模式保持冷紫；
 * 直接访问 /learn 时也按路由切换，避免刷新后主题与页面不一致。
 */
const isLearn = computed(() => mode.mode === 'learn' || route.path.startsWith('/learn'))
watch(
  isLearn,
  (value) => document.body.classList.toggle('theme-learn', value),
  { immediate: true },
)

/** 直接访问 /learn 或返回编辑路由时，同步模式状态，避免双侧栏与主题错位。 */
watch(
  () => route.path,
  (path) => {
    // 冷启动时 router 尚未解析出目标路由（name 为空、path 为 "/"），
    // 此时同步会把手动保存的 learn 模式误改回 edit；等实际路由就绪再判断。
    if (!route.name) return
    // 设置与 Wiki 浏览是双模共享页：
    // 从学习模式进入时保持学习模式（Wiki 批注仅学习模式可写），不自动跳回编辑模式
    if (path.startsWith('/settings') || path.startsWith('/wiki')) return
    const learn = path.startsWith('/learn')
    if (learn && mode.mode !== 'learn') mode.setMode('learn')
    else if (!learn && mode.mode === 'learn') mode.setMode('edit')
  },
  { immediate: true },
)

/** 大屏自动放大 UI：4K 屏上文字/控件不再偏小。 */
function applyUiScale() {
  const width = window.innerWidth
  const scale =
    width >= 4000 ? 1.75 : width >= 3200 ? 1.5 : width >= 2400 ? 1.3 : width >= 1800 ? 1.12 : 1
  document.documentElement.style.setProperty('--ui-scale', String(scale))
  // body 的 zoom 会放大内容，而 100dvh 不随之缩放。Wiki 页面目录需要的是
  // 视觉上不超过一屏的高度，因此先按缩放比换算成布局像素再下发。
  const treeHeight = Math.max(320, Math.round(window.innerHeight / scale - 156))
  document.documentElement.style.setProperty('--wiki-tree-h', `${treeHeight}px`)
}

onMounted(() => {
  kbs.fetchKbs()
  applyUiScale()
  window.addEventListener('resize', applyUiScale)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', applyUiScale)
})
</script>

<template>
  <div class="h-full flex flex-col">
    <!-- 全局顶栏：渐变玻璃条 -->
    <header
      class="h-14 shrink-0 relative z-30 flex items-center gap-4 px-4 backdrop-blur-xl bg-white/55 border-b border-slate-200/60"
    >
      <!-- 顶部高光细线 -->
      <div
        class="absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-kiwi-400/50 to-transparent"
      />
      <div class="flex items-center gap-2.5 select-none">
        <div
          class="relative w-8 h-8 rounded-xl bg-gradient-to-br from-kiwi-400 to-kiwi-600 flex items-center justify-center text-white text-sm font-bold shadow-glow"
        >
          <div class="absolute inset-0 rounded-xl bg-white/20 blur-[2px]" />
          <span class="relative">K</span>
        </div>
        <div class="leading-tight">
          <span class="font-bold text-slate-800 tracking-wide text-[15px]">Kiwi</span>
          <p class="text-[10px] text-slate-400 leading-none mt-0.5">
            {{ isLearn ? '学习训练 · 复习' : '知识编译 · 检索' }}
          </p>
        </div>
      </div>

      <div class="flex-1" />

      <!-- 右侧：模式切换 + 知识库切换 + 设置入口（两种模式共用） -->
      <ModeSwitcher />
      <KbSwitcher :learn="isLearn" />
      <RouterLink
        to="/settings"
        title="设置"
        class="grid h-8 w-8 place-items-center rounded-xl text-slate-500 transition-colors hover:bg-white/70 hover:text-slate-700"
        :class="route.path.startsWith('/settings') ? 'bg-white/80 text-kiwi-600' : ''"
      >
        <KiwiIcon name="settings" :size="17" />
      </RouterLink>
    </header>

    <main class="flex-1 min-h-0 flex">
      <!-- 侧栏：编辑 / 学习各自一套；学习侧栏在设置页也保留 -->
      <SideNav v-if="mode.mode === 'edit'" />
      <LearnSideNav v-else />

      <!-- 主内容：路由过渡 -->
      <div class="flex-1 min-w-0 overflow-y-auto">
        <RouterView v-slot="{ Component }">
          <Transition name="page" mode="out-in">
            <component :is="Component" :key="route.name" />
          </Transition>
        </RouterView>
      </div>
    </main>

    <KiwiToastHost />
  </div>
</template>
<script setup lang="ts">
/**
 * 学习模式左侧导航：与编辑模式 SideNav 同宽、同样式、共用收起状态。
 * 独立于 StudyView，进入设置等双模共享页面时菜单仍然保留。
 */
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useKbsStore } from '@/stores/kbs'
import { useStudyStore } from '@/stores/study'
import { IS_DESKTOP } from '@/desktop/env'
import KiwiIcon from '@/components/ui/KiwiIcon.vue'

type Pane =
  | 'review'
  | 'train'
  | 'mock'
  | 'graph'
  | 'plan'
  | 'report'
  | 'reminders'
  | 'mistakes'
  | 'profile'
type NavKey = Pane | 'resume'

const PANES: Pane[] = [
  'review',
  'train',
  'mock',
  'graph',
  'plan',
  'report',
  'reminders',
  'mistakes',
  'profile',
]

const route = useRoute()
const router = useRouter()
const kbs = useKbsStore()
const study = useStudyStore()

// 冷启动 = 学习画像采集完成。完成前主舞台只显示对话/画像表单，
// 侧栏其余功能没有可用的画像与掌握度数据，统一限制点击，避免半初始化状态下的空转请求。
const learnKb = computed(
  () => kbs.kbs.find((k) => k.id === kbs.activeLearnKbId) ?? null,
)
const learnReady = computed(() => (learnKb.value?.wiki_count ?? 0) > 0)
const coldStarted = computed(() => learnReady.value && !!study.profile?.onboarded)

// 共享页（设置 / Wiki）不会挂载 StudyView；若画像尚未加载，
// 侧栏主动取一次，保证冷启动门禁在冷刷新后仍然准确。
watch(
  () => kbs.activeLearnKbId,
  (id) => {
    if (!id) return
    if (!study.profile && !study.profileLoading) void study.loadProfile()
  },
  { immediate: true },
)

/** 今日复习承载冷启动对话，始终可点；其余入口在冷启动完成前禁用。 */
function navLocked(key: NavKey): boolean {
  if (coldStarted.value) return false
  return key !== 'review'
}

function lockedHint(key: NavKey): string | undefined {
  if (!navLocked(key)) return undefined
  if (!learnReady.value) return '请先在编辑模式导入素材并完成编译'
  return '请先完成学习冷启动对话'
}

const NAV_STORAGE_KEY = 'kiwi.sidenav.collapsed'
const navCollapsed = ref((() => {
  try {
    return localStorage.getItem(NAV_STORAGE_KEY) === '1'
  } catch {
    return false
  }
})())
watch(navCollapsed, (value) => {
  try {
    localStorage.setItem(NAV_STORAGE_KEY, value ? '1' : '0')
  } catch {
    /* 隐私模式下忽略 */
  }
})
function toggleNav() {
  navCollapsed.value = !navCollapsed.value
}

const navItems = computed<{ key: NavKey; label: string; icon: string }[]>(() => {
  const items: { key: NavKey; label: string; icon: string }[] = [
    { key: 'review', label: '今日复习', icon: 'refresh' },
  ]
  if (study.activeSession) items.push({ key: 'resume', label: '继续学习', icon: 'learn' })
  items.push(
    { key: 'train', label: '开始训练', icon: 'target' },
    { key: 'mock', label: '仿真考试', icon: 'book' },
    { key: 'graph', label: '学习图谱', icon: 'graph' },
    { key: 'plan', label: '学习计划', icon: 'calendar' },
    { key: 'report', label: '学习周报', icon: 'trendingUp' },
    // 桌面版没有推送服务，隐藏提醒设置。
    ...(IS_DESKTOP ? [] : [{ key: 'reminders' as const, label: '提醒设置', icon: 'bell' }]),
    { key: 'mistakes', label: '错题本', icon: 'bookOpen' },
    { key: 'profile', label: '我的画像', icon: 'edit' },
  )
  return items
})

/** 当前高亮项来自路由 query；在设置页时不高亮任何学习菜单项。 */
const activeKey = computed<NavKey | ''>(() => {
  if (route.name !== 'learn') return ''
  const raw = typeof route.query.pane === 'string' ? route.query.pane : 'review'
  if (raw === 'resume') return 'resume'
  return (PANES as string[]).includes(raw) ? (raw as Pane) : 'review'
})

function onNav(key: NavKey) {
  if (navLocked(key)) return
  void router.push({ name: 'learn', query: { ...route.query, pane: key } })
}
</script>

<template>
  <aside
    class="shrink-0 sidebar-glass h-full flex flex-col py-3 gap-0.5 overflow-visible transition-[width] duration-300 ease-out"
    :class="navCollapsed ? 'w-14' : 'w-44'"
  >
    <nav class="flex-1 min-h-0 flex flex-col gap-0.5 overflow-y-auto overflow-x-hidden">
      <button
        v-for="n in navItems"
        :key="n.key"
        type="button"
        :title="navLocked(n.key) ? lockedHint(n.key) : navCollapsed ? n.label : undefined"
        :disabled="navLocked(n.key)"
        :aria-disabled="navLocked(n.key) || undefined"
        class="group relative rounded-xl flex items-center gap-2.5 text-sm transition-all duration-200"
        :class="[
          navCollapsed ? 'mx-2 justify-center px-0 py-2.5' : 'mx-2 px-3 py-2',
          navLocked(n.key)
            ? 'opacity-40 cursor-not-allowed'
            : activeKey === n.key
              ? 'text-kiwi-700 font-medium'
              : 'text-slate-500 hover:text-slate-700 hover:bg-white/50',
        ]"
        @click="onNav(n.key)"
      >
        <!-- 与编辑模式 SideNav 完全一致的选中胶囊：位置、渐变、描边、阴影。 -->
        <span
          class="absolute inset-0 -z-0 rounded-xl bg-gradient-to-r from-kiwi-100/90 to-kiwi-50/60 border border-kiwi-200/50 shadow-soft transition-all duration-300"
          :class="activeKey === n.key ? 'opacity-100 scale-100' : 'opacity-0 scale-95'"
        />
        <span
          class="relative z-[1] grid place-items-center transition-transform duration-200 group-hover:scale-110"
        >
          <KiwiIcon
            :name="n.icon"
            :size="17"
            class="transition-colors duration-200"
            :class="
              activeKey === n.key ? 'text-kiwi-600' : 'text-slate-400 group-hover:text-slate-600'
            "
          />
        </span>
        <span v-if="!navCollapsed" class="relative z-[1] flex-1 whitespace-nowrap text-left">
          {{ n.label }}
        </span>
        <span
          v-if="!navCollapsed && n.key === 'review' && study.dueReviews.length"
          class="relative z-[1] px-1.5 py-0.5 rounded-md bg-amber-100 text-amber-700 text-[10px] font-semibold leading-none tabular-nums"
        >
          {{ study.dueReviews.length }}
        </span>
        <span
          v-else-if="!navCollapsed && n.key === 'resume' && study.activeSession"
          class="relative z-[1] px-1.5 py-0.5 rounded-md bg-kiwi-100 text-kiwi-700 text-[10px] font-semibold leading-none tabular-nums"
        >
          {{ study.activeSession.answered_count }}
        </span>
      </button>
    </nav>

    <div class="mt-auto px-2 pt-2">
      <button
        type="button"
        class="flex w-full items-center gap-2.5 rounded-xl py-2 text-[11px] text-slate-400 transition-colors hover:bg-white/50 hover:text-slate-600"
        :class="navCollapsed ? 'justify-center px-0' : 'px-3'"
        :title="navCollapsed ? '展开菜单' : '收起菜单'"
        @click="toggleNav"
      >
        <KiwiIcon :name="navCollapsed ? 'panelLeftOpen' : 'panelLeftClose'" :size="16" />
        <span v-if="!navCollapsed" class="whitespace-nowrap">收起菜单</span>
      </button>
    </div>
  </aside>
</template>

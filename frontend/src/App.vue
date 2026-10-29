<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { RouterLink, RouterView } from 'vue-router'
import { useKbsStore } from '@/stores/kbs'
import { useModeStore } from '@/stores/mode'
import { useSystemStore } from '@/stores/system'
import { useDesktopStore } from '@/stores/desktop'
import { useRoute } from 'vue-router'
import ModeSwitcher from '@/components/layout/ModeSwitcher.vue'
import SideNav from '@/components/layout/SideNav.vue'
import LearnSideNav from '@/components/study/LearnSideNav.vue'
import KbSwitcher from '@/components/layout/KbSwitcher.vue'
import KiwiIcon from '@/components/ui/KiwiIcon.vue'
import KiwiLogo from '@/components/ui/KiwiLogo.vue'
import KiwiToastHost from '@/components/ui/KiwiToastHost.vue'
import ShortcutHelpDialog from '@/components/ui/ShortcutHelpDialog.vue'
import NoteStickyLayer from '@/components/notes/NoteStickyLayer.vue'
import NoteSearchDialog from '@/components/notes/NoteSearchDialog.vue'
import PluginFloatLayer from '@/components/editor/PluginFloatLayer.vue'
import AuthLoginView from '@/views/AuthLoginView.vue'
import { useAuthStore } from '@/stores/auth'
import { useCommandPaletteStore } from '@/stores/commandPalette'
import { uiScaleForWidth } from '@/utils/uiScale'

const kbs = useKbsStore()
const mode = useModeStore()
const system = useSystemStore()
const desktop = useDesktopStore()
const auth = useAuthStore()
const commandPalette = useCommandPaletteStore()
const route = useRoute()

const shortcutsOpen = ref(false)
const booted = ref(false)
/**
 * 业务数据就绪标记。首次登录后必须先拿到知识库列表再渲染主布局：
 * 之前 kb 列表还是空的，页面按「无知识库」渲染，密钥登录后看起来像
 * 没有刷新加载数据。
 */
const appReady = ref(false)

/** 公开分享页使用独立布局，不加载业务数据、不弹登录页。 */
const isPublicShare = computed(() => route.name === 'note-share')

/** 登录成功后再拉取业务数据，避免访问控制开启时首屏刷出一串 401。 */
async function loadAppData() {
  if (booted.value) return
  booted.value = true
  appReady.value = false
  try {
    await kbs.fetchKbs()
  } catch {
    // 拉取失败也放行到主布局：页面内有重试入口，不能把用户卡在启动页。
  } finally {
    appReady.value = true
  }
  // 品牌信息与主题色来自后端系统设置；失败时保留内置默认值。
  void system.fetchSettings().catch(() => undefined)
  // 桌面运行状态：Docker 构建内部直接返回，不发起请求。
  void desktop.load()
}

async function boot() {
  if (isPublicShare.value) {
    auth.checking = false
    return
  }
  await auth.check()
  if (!auth.blocked) await loadAppData()
}

/**
 * 登录成功后由 auth 状态变化驱动加载业务数据。
 *
 * 不能依赖 AuthLoginView 的 `success` 事件：`auth.login()` 会先写入
 * authenticated，Vue 随即卸载登录组件并清空其事件监听，等 `await login()`
 * 返回后再 `emit` 已被忽略，导致首次登录后知识库列表一直为空。
 */
watch(
  () => auth.blocked,
  (blocked) => {
    if (blocked || auth.checking || booted.value) return
    void loadAppData()
  },
)

async function onLogout() {
  commandPalette.close()
  await auth.logout()
  booted.value = false
  appReady.value = false
}

function onUnauthorized() {
  commandPalette.close()
  auth.markUnauthorized()
  booted.value = false
  appReady.value = false
}

/** 输入框 / 编辑器内不抢占 `?`，保证正常输入问号。 */
function isTypingTarget(target: EventTarget | null) {
  const el = target as HTMLElement | null
  if (!el) return false
  return (
    el.isContentEditable ||
    el.tagName === 'INPUT' ||
    el.tagName === 'TEXTAREA' ||
    el.tagName === 'SELECT'
  )
}

function onShortcutKey(event: KeyboardEvent) {
  if (event.key !== '?') return
  if (event.defaultPrevented || event.ctrlKey || event.metaKey || event.altKey) return
  if (isTypingTarget(event.target)) return
  event.preventDefault()
  shortcutsOpen.value = !shortcutsOpen.value
}

/** 全站命令面板：笔记检索 + 新建 / 导航 / 页内查找 / 置顶插件等操作。 */
function onCommandPaletteKey(event: KeyboardEvent) {
  if (event.defaultPrevented || event.altKey || event.shiftKey) return
  if (!(event.ctrlKey || event.metaKey)) return
  if (event.key.toLowerCase() !== 'k') return
  if (isPublicShare.value || auth.blocked || auth.checking) return
  event.preventDefault()
  commandPalette.toggle()
}

/** Ctrl/⌘+Shift+P：只显示命令（VSCode 习惯），不混入笔记结果。 */
function onCommandOnlyPaletteKey(event: KeyboardEvent) {
  if (event.defaultPrevented || event.altKey || !event.shiftKey) return
  if (!(event.ctrlKey || event.metaKey)) return
  if (event.key.toLowerCase() !== 'p') return
  if (isPublicShare.value || auth.blocked || auth.checking) return
  event.preventDefault()
  commandPalette.show(true)
}

/**
 * 学习模式使用青绿主题色，编辑模式保持冷紫；
 * 直接访问 /learn 时也按路由切换，避免刷新后主题与页面不一致。
 */
const isLearn = computed(() => mode.mode === 'learn' || route.path.startsWith('/learn'))
/** 顶栏 Logo 按模式回显：学习模式未单独上传时沿用品牌 Logo。 */
const headerLogo = computed(() =>
  isLearn.value ? system.learnLogoUrl : system.logoUrl,
)
watch(
  isLearn,
  (value) => {
    document.body.classList.toggle('theme-learn', value)
    // 两种模式使用不同的品牌标记，浏览器标签页同步切换。
    const icon = document.querySelector<HTMLLinkElement>('link[rel="icon"]')
    if (icon) {
      icon.href = `${import.meta.env.BASE_URL}${value ? 'favicon-learn.svg' : 'favicon.svg'}`
    }
  },
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
  const scale = uiScaleForWidth(width)
  document.documentElement.style.setProperty('--ui-scale', String(scale))
  // body 的 zoom 会放大内容，而 100dvh 不随之缩放。Wiki 页面目录需要的是
  // 视觉上不超过一屏的高度，因此先按缩放比换算成布局像素再下发。
  const treeHeight = Math.max(320, Math.round(window.innerHeight / scale - 156))
  document.documentElement.style.setProperty('--wiki-tree-h', `${treeHeight}px`)
}

onMounted(() => {
  applyUiScale()
  window.addEventListener('resize', applyUiScale)
  window.addEventListener('keydown', onShortcutKey)
  window.addEventListener('keydown', onCommandPaletteKey)
  window.addEventListener('keydown', onCommandOnlyPaletteKey)
  window.addEventListener('kiwi:unauthorized', onUnauthorized)
  void boot()
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', applyUiScale)
  window.removeEventListener('keydown', onShortcutKey)
  window.removeEventListener('keydown', onCommandPaletteKey)
  window.removeEventListener('keydown', onCommandOnlyPaletteKey)
  window.removeEventListener('kiwi:unauthorized', onUnauthorized)
})
</script>

<template>
  <!-- 公开只读分享页：不渲染顶栏、侧栏与登录门。 -->
  <RouterView v-if="isPublicShare" />

  <div v-else-if="auth.checking" class="grid h-full place-items-center text-sm text-slate-400">
    <span class="flex items-center gap-2">
      <KiwiIcon name="loader" :size="16" :spin="true" />
      正在检查访问权限…
    </span>
  </div>

  <!-- 登录成功后的数据加载由 auth.blocked 的 watcher 触发，不依赖组件事件 -->
  <AuthLoginView v-else-if="auth.blocked" />

  <div v-else-if="!appReady" class="grid h-full place-items-center text-sm text-slate-400">
    <span class="flex items-center gap-2">
      <KiwiIcon name="loader" :size="16" :spin="true" />
      正在加载知识库…
    </span>
  </div>

  <div v-else class="h-full flex flex-col">
    <!-- 全局顶栏：渐变玻璃条 -->
    <header
      class="h-14 shrink-0 relative z-30 flex items-center gap-4 px-4 backdrop-blur-xl bg-white/55 border-b border-slate-200/60 max-md:gap-1.5 max-md:px-2"
    >
      <!-- 顶部高光细线 -->
      <div
        class="absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-kiwi-400/50 to-transparent"
      />
      <RouterLink to="/kbs" class="flex min-w-0 items-center gap-2.5 select-none">
        <img
          v-if="headerLogo"
          :src="headerLogo"
          :alt="system.appName"
          class="relative h-8 w-8 shrink-0 rounded-xl object-cover shadow-glow"
        />
        <KiwiLogo
          v-else
          :mode="isLearn ? 'learn' : 'edit'"
          :size="32"
          class="relative shrink-0 rounded-xl shadow-glow"
        />
        <div class="min-w-0 leading-tight max-md:hidden">
          <span class="block truncate text-[15px] font-bold tracking-wide text-slate-800">
            {{ system.appName }}
          </span>
          <p class="mt-0.5 max-w-[260px] truncate text-[10px] leading-none text-slate-400">
            {{ isLearn ? system.learnDescription : system.appDescription }}
          </p>
        </div>
      </RouterLink>

      <div class="flex-1" />

      <!-- 右侧：模式切换 + 知识库切换 + 设置入口（两种模式共用） -->
      <ModeSwitcher class="max-md:hidden" />
      <KbSwitcher :learn="isLearn" />
      <button
        type="button"
        title="键盘快捷键（?）"
        aria-label="键盘快捷键"
        class="grid h-8 w-8 place-items-center rounded-xl text-slate-500 transition-colors hover:bg-white/70 hover:text-slate-700 max-md:hidden"
        :class="shortcutsOpen ? 'bg-white/80 text-kiwi-600' : ''"
        @click="shortcutsOpen = true"
      >
        <KiwiIcon name="keyboard" :size="17" />
      </button>
      <RouterLink
        to="/settings"
        title="设置"
        class="grid h-8 w-8 place-items-center rounded-xl text-slate-500 transition-colors hover:bg-white/70 hover:text-slate-700"
        :class="route.path.startsWith('/settings') ? 'bg-white/80 text-kiwi-600' : ''"
      >
        <KiwiIcon name="settings" :size="17" />
      </RouterLink>
      <button
        v-if="auth.enabled"
        type="button"
        title="退出登录"
        aria-label="退出登录"
        class="grid h-8 w-8 place-items-center rounded-xl text-slate-500 transition-colors hover:bg-rose-50 hover:text-rose-500"
        @click="onLogout"
      >
        <KiwiIcon name="lock" :size="16" />
      </button>
    </header>

    <main class="flex-1 min-h-0 flex">
      <!-- 侧栏：编辑 / 学习各自一套；学习侧栏在设置页也保留 -->
      <SideNav v-if="mode.mode === 'edit'" />
      <LearnSideNav v-else />

      <!-- 主内容：路由过渡；「贴一贴」打开主窗口时以该区域为展开目标 -->
      <div class="flex-1 min-w-0 overflow-y-auto" data-kiwi-main-content>
        <RouterView v-slot="{ Component }">
          <Transition name="page" mode="out-in">
            <component :is="Component" :key="route.name" />
          </Transition>
        </RouterView>
      </div>
    </main>

    <ShortcutHelpDialog :open="shortcutsOpen" @close="shortcutsOpen = false" />
    <!-- 全局命令面板：Ctrl/⌘+K 检索笔记或执行「置顶插件组件」等快捷操作 -->
    <NoteSearchDialog :open="commandPalette.open" @close="commandPalette.close()" />
    <!-- 「贴一贴」便签窗口：跨路由保留，登录后才渲染 -->
    <NoteStickyLayer />
    <!-- 组件插件置顶窗口：pinnable 区块可跨路由常驻 -->
    <PluginFloatLayer />
  </div>

  <KiwiToastHost />
</template>
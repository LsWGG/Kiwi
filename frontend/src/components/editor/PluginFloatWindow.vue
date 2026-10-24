<script setup lang="ts">
/**
 * 组件插件置顶浮窗：声明 pinnable 的区块（番茄钟 / 倒计时等）可以在
 * 独立窗口里跨路由常驻，交互状态写入浮窗自己的 props，不修改笔记正文。
 *
 * 窗口结构参考「贴一贴」：外层按视口坐标定位，内层按 --ui-scale 放大；
 * 位置、尺寸与组件状态由 pluginWindows store 持久化。
 */
import {
  computed,
  nextTick,
  onBeforeUnmount,
  onErrorCaptured,
  onMounted,
  ref,
  watch,
} from 'vue'
import KiwiIcon from '@/components/ui/KiwiIcon.vue'
import { usePluginWindowsStore, type PluginFloatWindow } from '@/stores/pluginWindows'
import { usePluginsStore } from '@/stores/plugins'
import { useFloatingWindowDrag } from '@/composables/useFloatingWindowDrag'

const props = defineProps<{ win: PluginFloatWindow }>()

const pluginWindows = usePluginWindowsStore()
const plugins = usePluginsStore()
const renderError = ref('')
const windowEl = ref<HTMLElement | null>(null)
const headerEl = ref<HTMLElement | null>(null)
const bodyEl = ref<HTMLElement | null>(null)
/** 插件组件的自然内容尺寸包装层，用于把浮窗高度贴合内容。 */
const contentEl = ref<HTMLElement | null>(null)

const entry = computed(() =>
  plugins.getComponentBlock(props.win.pluginKey, props.win.blockType),
)
const plugin = computed(() =>
  plugins.plugins.find((item) => item.key === props.win.pluginKey),
)
const loadError = computed(
  () => plugins.runtimeErrors[props.win.pluginKey] || renderError.value,
)
const subtitle = computed(() => {
  const name = plugin.value?.name || props.win.pluginKey
  return `${name} · ${props.win.blockType}`
})
const message = computed(() => {
  if (renderError.value) return '组件渲染失败'
  if (loadError.value) return loadError.value
  if (!plugin.value) return '插件未安装或已删除'
  if (!plugin.value.enabled) return '插件已停用'
  if (plugins.runtimeLoading) return '插件运行时加载中…'
  return '插件未注册该区块，或加载失败'
})

const { onDragStart, onResizeStart } = useFloatingWindowDrag({
  bounds: props.win,
  minW: pluginWindows.MIN_W,
  minH: pluginWindows.MIN_H,
  onCommit: () =>
    pluginWindows.updateBounds(props.win.id, {
      x: props.win.x,
      y: props.win.y,
      w: props.win.w,
      h: props.win.h,
    }),
})

/**
 * 内容自适应高度：插件区块本身没有固定高度，窗口默认高度容易留下大片空白
 * 或截出滚动条。这里测出「头部 + 内容」的自然高度并同步到 store。
 *
 * 用户手动缩放过高度后只允许继续加高（内容变多时不出现滚动条），
 * 不再自动压回去；正在拖动缩放手柄时暂停测量，避免和指针位置打架。
 */
let fitObserver: ResizeObserver | null = null
let fitRaf = 0
let resizing = false
let userSized = false

function measureContentHeight(): number {
  const winEl = windowEl.value
  const header = headerEl.value
  const body = bodyEl.value
  const content = contentEl.value
  if (!winEl || !header || !body || !content) return 0
  const style = getComputedStyle(body)
  const padY =
    (Number.parseFloat(style.paddingTop) || 0) +
    (Number.parseFloat(style.paddingBottom) || 0)
  // offset* 不受 --ui-scale 的 zoom 放大影响，可直接与 win.h 比较。
  const borderY = winEl.offsetHeight - winEl.clientHeight
  return Math.ceil(header.offsetHeight + content.offsetHeight + padY + borderY)
}

function applyFit() {
  fitRaf = 0
  if (resizing) return
  const desired = measureContentHeight()
  if (!desired) return
  const current = props.win.h
  if (Math.abs(desired - current) < 1) return
  if (desired < current && userSized) return
  pluginWindows.updateBounds(props.win.id, { h: desired })
}

function scheduleFit() {
  if (fitRaf) return
  fitRaf = requestAnimationFrame(applyFit)
}

/** 拖动缩放期间暂停自动高度；松手后只补足内容需要的高度。 */
function handleResizeStart(event: PointerEvent) {
  if (event.button !== 0) return
  resizing = true
  userSized = true
  onResizeStart(event)
  const stop = () => {
    resizing = false
    window.removeEventListener('pointerup', stop)
    window.removeEventListener('pointercancel', stop)
    void nextTick(scheduleFit)
  }
  window.addEventListener('pointerup', stop)
  window.addEventListener('pointercancel', stop)
}

/** 从其他浮窗后面升到最前时给一个回弹，提示当前操作的是哪个窗口。 */
function pulseWindow() {
  const node = windowEl.value
  if (!node) return
  if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return
  node.animate(
    [
      { transform: 'scale(1)' },
      { transform: 'scale(1.04)', offset: 0.35 },
      { transform: 'scale(0.99)', offset: 0.7 },
      { transform: 'scale(1)' },
    ],
    { duration: 440, easing: 'cubic-bezier(0.2, 1.2, 0.3, 1)' },
  )
}

function onWindowPointerDown() {
  const topZ = Math.max(0, ...pluginWindows.windows.map((item) => item.z))
  const rising = props.win.z < topZ
  pluginWindows.focus(props.win.id)
  if (rising) pulseWindow()
}

function updateProps(patch: Record<string, unknown>) {
  pluginWindows.patchProps(props.win.id, patch)
}

function close() {
  pluginWindows.close(props.win.id)
}

function requestRuntime() {
  void plugins.ensureComponentBlocks()
}

onErrorCaptured((error) => {
  renderError.value =
    error instanceof Error && error.message ? error.message : '组件渲染失败'
  return false
})

watch(
  () => [props.win.pluginKey, props.win.blockType],
  () => {
    renderError.value = ''
    requestRuntime()
  },
)

// 插件运行时异步注册区块，组件挂载 / 报错切换后都重新贴合一次高度。
watch([entry, loadError, () => plugins.runtimeLoading], async () => {
  await nextTick()
  scheduleFit()
})

onMounted(() => {
  requestRuntime()
  if (typeof ResizeObserver !== 'undefined' && contentEl.value) {
    fitObserver = new ResizeObserver(scheduleFit)
    fitObserver.observe(contentEl.value)
  }
  void nextTick(scheduleFit)
})

onBeforeUnmount(() => {
  fitObserver?.disconnect()
  fitObserver = null
  if (fitRaf) cancelAnimationFrame(fitRaf)
  fitRaf = 0
})
</script>

<template>
  <div
    class="plugin-float-anchor fixed"
    :style="{ left: `${win.x}px`, top: `${win.y}px`, zIndex: win.z }"
    @pointerdown.capture="onWindowPointerDown"
  >
    <div
      ref="windowEl"
      class="plugin-float-window relative flex flex-col overflow-hidden rounded-2xl border border-slate-200/80 bg-white/95 shadow-lifted backdrop-blur-xl"
      :style="{ width: `${win.w}px`, height: `${win.h}px`, zoom: 'var(--ui-scale)' }"
      role="dialog"
      :aria-label="`置顶组件：${win.title}`"
    >
      <header
        ref="headerEl"
        class="flex shrink-0 cursor-grab items-center gap-2 border-b border-slate-100 bg-gradient-to-b from-slate-50/90 to-white px-3 py-2 active:cursor-grabbing"
        @pointerdown="onDragStart"
      >
        <KiwiIcon :name="win.icon || 'puzzle'" :size="14" class="shrink-0 text-kiwi-600" />
        <div class="min-w-0 flex-1">
          <p class="truncate text-[12.5px] font-medium text-slate-700" :title="win.title">
            {{ win.title }}
          </p>
          <p class="truncate text-[9.5px] text-slate-400">{{ subtitle }}</p>
        </div>
        <button
          type="button"
          class="plugin-float-icon-button hover:!bg-rose-50 hover:!text-rose-500"
          title="关闭置顶窗口"
          @click.stop="close"
        >
          <KiwiIcon name="close" :size="13" />
        </button>
      </header>

      <div ref="bodyEl" class="plugin-float-body min-h-0 flex-1 overflow-auto p-2.5">
        <div ref="contentEl" class="plugin-float-content">
          <component
            :is="entry.component"
            v-if="entry && !renderError"
            :block-props="win.props"
            :readonly="false"
            :selected="false"
            :update-props="updateProps"
            :delete-block="() => {}"
          />
          <div v-else class="plugin-float-fallback">
            <KiwiIcon :name="loadError ? 'alert' : 'puzzle'" :size="18" />
            <p class="plugin-float-fallback-title">{{ win.title }}</p>
            <p class="plugin-float-fallback-message" :class="{ 'is-error': !!loadError }">
              {{ message }}
            </p>
          </div>
        </div>
      </div>

      <!-- 缩放手柄 -->
      <span
        class="absolute bottom-0 right-0 h-4 w-4 cursor-nwse-resize"
        title="拖动调整大小"
        @pointerdown="handleResizeStart"
      >
        <svg viewBox="0 0 16 16" class="h-4 w-4 text-slate-300" aria-hidden="true">
          <path
            d="M15 6L6 15M15 10l-5 5"
            stroke="currentColor"
            stroke-width="1.4"
            stroke-linecap="round"
          />
        </svg>
      </span>
    </div>
  </div>
</template>

<style scoped>
.plugin-float-window {
  min-width: 260px;
  min-height: 180px;
  transform-origin: 85% 8%;
  animation: plugin-float-pop 0.46s cubic-bezier(0.2, 1.4, 0.32, 1) both;
}
/* 弹入时沿窗口边缘扩散一圈主题色光晕；外扩阴影由未裁切的外层锚点承载。 */
.plugin-float-anchor::after {
  content: '';
  position: absolute;
  inset: 0;
  border-radius: calc(1rem * var(--ui-scale, 1));
  pointer-events: none;
  animation: plugin-float-halo 0.7s cubic-bezier(0.16, 1, 0.3, 1) 0.08s;
}
@keyframes plugin-float-pop {
  0% {
    opacity: 0;
    transform: translateY(18px) scale(0.6);
  }
  55% {
    opacity: 1;
  }
  72% {
    transform: translateY(-3px) scale(1.045);
  }
  100% {
    opacity: 1;
    transform: translateY(0) scale(1);
  }
}
@keyframes plugin-float-halo {
  0% {
    opacity: 0.85;
    box-shadow:
      0 0 0 2px rgb(var(--kiwi-400) / 0.5),
      0 0 20px 4px rgb(var(--kiwi-300) / 0.32);
  }
  100% {
    opacity: 0;
    box-shadow:
      0 0 0 26px rgb(var(--kiwi-400) / 0),
      0 0 36px 16px rgb(var(--kiwi-300) / 0);
  }
}
@media (prefers-reduced-motion: reduce) {
  .plugin-float-window {
    animation: none;
  }
  .plugin-float-anchor::after {
    display: none;
  }
}
/* flow-root 让包装层高度包含子元素外边距，测量结果不会少算几像素。 */
.plugin-float-content {
  display: flow-root;
}
.plugin-float-icon-button {
  display: grid;
  place-items: center;
  width: 24px;
  height: 24px;
  border-radius: 7px;
  color: rgb(100 116 139);
  transition: background 0.15s ease, color 0.15s ease;
}
.plugin-float-icon-button:hover {
  background: rgb(241 245 249);
  color: rgb(30 41 59);
}
.plugin-float-fallback {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 6px;
  min-height: 120px;
  padding: 16px;
  text-align: center;
  color: rgb(100 116 139);
}
.plugin-float-fallback-title {
  margin: 0;
  font-size: 12px;
  font-weight: 600;
  color: rgb(51 65 85);
}
.plugin-float-fallback-message {
  margin: 0;
  font-size: 10.5px;
  line-height: 1.5;
}
.plugin-float-fallback-message.is-error {
  color: rgb(225 29 72);
}
</style>

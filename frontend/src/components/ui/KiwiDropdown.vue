<script setup lang="ts">
/**
 * 轻量下拉：点击触发，点击外部关闭，内容点击不自动关闭（可自行调用 close）。
 * 面板挂到 <html> 下：4K 下 body 的 CSS zoom 会让 absolute 坐标二次缩放，
 * 且目录栏的层叠上下文会被正文工具栏盖住，统一用视口坐标 + 高层级解决。
 */
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import {
  ownsOrNested as ownedBySelfOrNested,
  registerDropdown,
  registerPanel,
  unregisterDropdown,
  type DropdownHandle,
} from './dropdownRegistry'

const props = withDefaults(
  defineProps<{
    align?: 'left' | 'right'
    width?: string
    panelClass?: string
    /** 禁用时触发器不响应点击（颜色选择器等需要整块禁用时使用）。 */
    disabled?: boolean
  }>(),
  { align: 'left', width: 'w-48', panelClass: '', disabled: false },
)

const open = ref(false)
const root = ref<HTMLElement | null>(null)
const panel = ref<HTMLElement | null>(null)
const pos = ref({ left: '0px', top: '0px' })

const ancestorPanel = ref<HTMLElement | null>(null)
const handle: DropdownHandle = {
  isOpen: () => open.value,
  owns(target) {
    return Boolean(root.value?.contains(target) || panel.value?.contains(target))
  },
  panelEl: () => panel.value,
  ancestorPanelEl: () => ancestorPanel.value,
}

function ownsOrNested(target: Node): boolean {
  return ownedBySelfOrNested(handle, target)
}

function place() {
  const anchor = root.value
  if (!anchor) return
  const rect = anchor.getBoundingClientRect()
  void nextTick(() => {
    if (panel.value) registerPanel(panel.value, handle)
    const box = panel.value?.getBoundingClientRect()
    const width = box?.width ?? 0
    const height = box?.height ?? 0
    const gap = 6
    let left = props.align === 'right' ? rect.right - width : rect.left
    left = Math.max(8, Math.min(left, window.innerWidth - width - 8))
    let top = rect.bottom + gap
    if (top + height > window.innerHeight - 8) {
      top = Math.max(8, rect.top - height - gap)
    }
    pos.value = { left: `${left}px`, top: `${top}px` }
  })
}

function toggle() {
  if (props.disabled) return
  open.value = !open.value
}
function close() {
  open.value = false
}
function onDocPointerDown(e: Event) {
  if (!open.value) return
  const target = e.target as Node
  if (ownsOrNested(target)) return
  close()
}
function onViewportChange() {
  if (open.value) close()
}
/** 窗口失焦 / Esc 时收起，避免面板悬浮在画布上遮挡操作。 */
function onWindowBlur() {
  close()
}
function onKeydown(e: KeyboardEvent) {
  if (open.value && e.key === 'Escape') close()
}
/**
 * 面板内部（如表情网格）滚动不应关闭下拉；
 * scroll 不冒泡，但捕获阶段能拿到来源元素，据此排除面板自身。
 */
function onAnyScroll(e: Event) {
  if (!open.value) return
  const target = e.target as Node | null
  if (target && ownsOrNested(target)) return
  // 锚点所在的可滚动祖先（例如工具栏 overflow-x-auto）滚动时不应关闭面板：
  // 点击触发按钮会让浏览器把它滚入视野，若此时关闭，面板会瞬开瞬关。
  if (target && root.value && target.contains(root.value)) return
  close()
}

watch(open, (value) => {
  if (!value) {
    ancestorPanel.value = null
    return
  }
  // 打开时记下触发器所在的外层面板：这是 Teleport 之后唯一可靠的双向线索。
  ancestorPanel.value = root.value?.closest('.kiwi-menu-panel') ?? null
  place()
})

onMounted(() => {
  registerDropdown(handle)
  // pointerdown 比 mousedown 更可靠：画布的 pointerdown 会 preventDefault，
  // 从而抑制兼容 mouse 事件，导致点击画布时下拉无法关闭。
  document.addEventListener('pointerdown', onDocPointerDown, true)
  window.addEventListener('blur', onWindowBlur)
  document.addEventListener('keydown', onKeydown)
  window.addEventListener('resize', onViewportChange)
  window.addEventListener('scroll', onAnyScroll, true)
})
onBeforeUnmount(() => {
  unregisterDropdown(handle)
  document.removeEventListener('pointerdown', onDocPointerDown, true)
  window.removeEventListener('blur', onWindowBlur)
  document.removeEventListener('keydown', onKeydown)
  window.removeEventListener('resize', onViewportChange)
  window.removeEventListener('scroll', onAnyScroll, true)
})
</script>

<template>
  <div ref="root" class="relative">
    <div @click="toggle">
      <slot name="trigger" :open="open" />
    </div>
    <Teleport to="html">
      <Transition name="dropdown">
        <div
          v-if="open"
          class="fixed z-[120]"
          :style="pos"
        >
          <div
            ref="panel"
            class="kiwi-menu-panel rounded-xl border border-slate-200/90 bg-white/40 p-1.5 shadow-xl backdrop-blur-2xl"
            :class="[width, panelClass]"
            :style="{ zoom: 'var(--ui-scale)' }"
          >
            <slot :close="close" />
          </div>
        </div>
      </Transition>
    </Teleport>
  </div>
</template>

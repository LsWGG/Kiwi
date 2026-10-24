/**
 * 浮窗拖动 / 右下角缩放，贴一贴与插件置顶窗口共用。
 *
 * 直接修改传入的 bounds（store 中的响应式对象），松手时通过 onCommit 持久化。
 */
import { onBeforeUnmount } from 'vue'
import { uiScaleForWidth } from '@/utils/uiScale'
import type { FloatingBounds } from '@/utils/floatingWindow'

type DragState = {
  mode: 'move' | 'resize'
  startX: number
  startY: number
  x: number
  y: number
  w: number
  h: number
}

export function useFloatingWindowDrag(options: {
  bounds: FloatingBounds
  minW: number
  minH: number
  onCommit: () => void
  /** 浮窗内部不触发拖动的元素（按钮、输入框等）。 */
  ignoreSelector?: string
}) {
  let dragState: DragState | null = null
  const ignoreSelector =
    options.ignoreSelector || 'button, input, textarea, select, .sticky-no-drag'

  function start(event: PointerEvent, mode: DragState['mode']) {
    if (event.button !== 0) return
    if (mode === 'move' && (event.target as HTMLElement).closest(ignoreSelector)) return
    dragState = {
      mode,
      startX: event.clientX,
      startY: event.clientY,
      x: options.bounds.x,
      y: options.bounds.y,
      w: options.bounds.w,
      h: options.bounds.h,
    }
    window.addEventListener('pointermove', onMove)
    window.addEventListener('pointerup', onEnd)
    event.preventDefault()
    if (mode === 'resize') event.stopPropagation()
  }

  function onDragStart(event: PointerEvent) {
    start(event, 'move')
  }

  function onResizeStart(event: PointerEvent) {
    start(event, 'resize')
  }

  function onMove(event: PointerEvent) {
    const state = dragState
    if (!state) return
    const dx = event.clientX - state.startX
    const dy = event.clientY - state.startY
    if (state.mode === 'move') {
      options.bounds.x = Math.max(8, Math.min(state.x + dx, window.innerWidth - 120))
      options.bounds.y = Math.max(8, Math.min(state.y + dy, window.innerHeight - 48))
      return
    }
    // 内层带 --ui-scale 缩放，指针位移要折算回局部尺寸，四边才能在视觉上贴住视口。
    const scale = uiScaleForWidth(window.innerWidth)
    options.bounds.w = Math.max(
      options.minW,
      Math.min(state.w + dx / scale, (window.innerWidth - state.x - 8) / scale),
    )
    options.bounds.h = Math.max(
      options.minH,
      Math.min(state.h + dy / scale, (window.innerHeight - state.y - 8) / scale),
    )
  }

  function onEnd() {
    if (!dragState) return
    dragState = null
    window.removeEventListener('pointermove', onMove)
    window.removeEventListener('pointerup', onEnd)
    options.onCommit()
  }

  function cleanup() {
    dragState = null
    window.removeEventListener('pointermove', onMove)
    window.removeEventListener('pointerup', onEnd)
  }

  onBeforeUnmount(cleanup)

  return { onDragStart, onResizeStart }
}

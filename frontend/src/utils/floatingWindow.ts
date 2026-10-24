/**
 * 浮窗（贴一贴 / 插件置顶）共用的视口边界计算。
 *
 * 浮窗挂在 <html> 下、内层单独按 --ui-scale 放大，w/h 是放大前的局部尺寸，
 * 判断右 / 下边界时要乘回缩放比例，否则 2K / 4K 下会整窗落到屏幕外。
 */
import { uiScaleForWidth } from './uiScale'

export interface FloatingBounds {
  x: number
  y: number
  w: number
  h: number
}

export function clampFloatingBounds(
  win: FloatingBounds,
  minW: number,
  minH: number,
): FloatingBounds {
  if (typeof window === 'undefined') return { ...win }
  const vw = window.innerWidth
  const vh = window.innerHeight
  const scale = uiScaleForWidth(vw)
  const w = Math.max(minW, Math.min(win.w, Math.max(minW, vw / scale - 16)))
  const h = Math.max(minH, Math.min(win.h, Math.max(minH, vh / scale - 16)))
  return {
    w,
    h,
    x: Math.max(8, Math.min(win.x, vw - w * scale - 8)),
    y: Math.max(8, Math.min(win.y, vh - h * scale - 8)),
  }
}

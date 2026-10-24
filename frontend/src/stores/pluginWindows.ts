/**
 * 组件插件「置顶浮窗」：把声明了 pinnable 的插件区块放到独立窗口，
 * 跨路由置顶展示（参考「贴一贴」），位置 / 尺寸与组件状态持久化到 localStorage。
 *
 * 同一个插件区块类型只保留一个全局窗口；窗口里的 props 独立于笔记节点，
 * 因此离开笔记后计时器仍可继续运行。
 */
import { defineStore } from 'pinia'
import { ref } from 'vue'
import { uiScaleForWidth } from '@/utils/uiScale'
import {
  clampFloatingBounds,
  type FloatingBounds,
} from '@/utils/floatingWindow'

export interface PluginFloatWindow extends FloatingBounds {
  id: string
  pluginKey: string
  blockType: string
  title: string
  icon: string
  props: Record<string, unknown>
  z: number
}

export interface PluginFloatInput {
  pluginKey: string
  blockType: string
  title: string
  icon: string
  props: Record<string, unknown>
}

const STORAGE_KEY = 'kiwi.plugin.windows'
const MIN_W = 260
const MIN_H = 180
const DEFAULT_W = 380
const DEFAULT_H = 320
const MAX_WINDOWS = 8

export function pluginWindowId(pluginKey: string, blockType: string): string {
  return `${pluginKey}:${blockType}`
}

function isProps(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === 'object' && !Array.isArray(value)
}

function loadSaved(): PluginFloatWindow[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return []
    const parsed = JSON.parse(raw)
    if (!Array.isArray(parsed)) return []
    return parsed
      .filter(
        (item) =>
          item &&
          typeof item.pluginKey === 'string' &&
          typeof item.blockType === 'string',
      )
      .slice(0, MAX_WINDOWS)
      .map((item, index) => {
        const bounds = clampFloatingBounds(
          {
            x: Number(item.x) || 160,
            y: Number(item.y) || 120,
            w: Number(item.w) || DEFAULT_W,
            h: Number(item.h) || DEFAULT_H,
          },
          MIN_W,
          MIN_H,
        )
        return {
          id: pluginWindowId(item.pluginKey, item.blockType),
          pluginKey: item.pluginKey,
          blockType: item.blockType,
          title: String(item.title || `${item.pluginKey}:${item.blockType}`),
          icon: String(item.icon || 'puzzle'),
          props: isProps(item.props) ? item.props : {},
          z: 80 + index,
          ...bounds,
        }
      })
  } catch {
    return []
  }
}

export const usePluginWindowsStore = defineStore('pluginWindows', () => {
  const windows = ref<PluginFloatWindow[]>(loadSaved())
  let zCounter = windows.value.reduce((max, win) => Math.max(max, win.z), 80)
  let persistTimer: number | null = null

  function persist() {
    if (persistTimer !== null) {
      window.clearTimeout(persistTimer)
      persistTimer = null
    }
    try {
      localStorage.setItem(
        STORAGE_KEY,
        JSON.stringify(
          windows.value.map(
            ({ pluginKey, blockType, title, icon, props, x, y, w, h }) => ({
              pluginKey,
              blockType,
              title,
              icon,
              props,
              x,
              y,
              w,
              h,
            }),
          ),
        ),
      )
    } catch {
      /* 隐私模式下 localStorage 不可用，浮窗仍可在当前会话使用。 */
    }
  }

  /** 组件 props 每秒都在变（计时器），持久化做轻度防抖。 */
  function schedulePersist() {
    if (persistTimer !== null) window.clearTimeout(persistTimer)
    persistTimer = window.setTimeout(persist, 1200)
  }

  function windowId(pluginKey: string, blockType: string): string {
    return pluginWindowId(pluginKey, blockType)
  }

  function isOpen(pluginKey: string, blockType: string): boolean {
    return windows.value.some(
      (win) => win.pluginKey === pluginKey && win.blockType === blockType,
    )
  }

  /** 打开 / 聚焦置顶窗口；再次打开时以当前区块 props 刷新窗口状态。 */
  function open(input: PluginFloatInput) {
    const id = pluginWindowId(input.pluginKey, input.blockType)
    const existing = windows.value.find((win) => win.id === id)
    if (existing) {
      existing.title = input.title
      existing.icon = input.icon
      existing.props = { ...input.props }
      Object.assign(existing, clampFloatingBounds(existing, MIN_W, MIN_H))
      focus(id)
      return id
    }
    const offset = (windows.value.length % 6) * 24
    const scale = uiScaleForWidth(window.innerWidth)
    const bounds = clampFloatingBounds(
      {
        x: Math.max(8, window.innerWidth - DEFAULT_W * scale - 48 - offset),
        y: 120 + offset,
        w: DEFAULT_W,
        h: DEFAULT_H,
      },
      MIN_W,
      MIN_H,
    )
    zCounter += 1
    windows.value.push({
      id,
      pluginKey: input.pluginKey,
      blockType: input.blockType,
      title: input.title,
      icon: input.icon,
      props: { ...input.props },
      z: zCounter,
      ...bounds,
    })
    if (windows.value.length > MAX_WINDOWS) {
      windows.value = windows.value.slice(-MAX_WINDOWS)
    }
    persist()
    return id
  }

  function focus(id: string) {
    const win = windows.value.find((item) => item.id === id)
    if (!win) return
    Object.assign(win, clampFloatingBounds(win, MIN_W, MIN_H))
    zCounter += 1
    win.z = zCounter
    persist()
  }

  function close(id: string) {
    windows.value = windows.value.filter((win) => win.id !== id)
    persist()
  }

  function updateBounds(id: string, patch: Partial<FloatingBounds>) {
    const win = windows.value.find((item) => item.id === id)
    if (!win) return
    Object.assign(win, clampFloatingBounds({ ...win, ...patch }, MIN_W, MIN_H))
    persist()
  }

  /** 组件内部的 updateProps：合并补丁并写回 localStorage，不影响笔记正文。 */
  function patchProps(id: string, patch: Record<string, unknown>) {
    const win = windows.value.find((item) => item.id === id)
    if (!win || !isProps(patch)) return
    win.props = { ...win.props, ...patch }
    schedulePersist()
  }

  /** 浏览器窗口缩放 / 页面缩放后把全部置顶窗口收回可视区域。 */
  function clampAll() {
    let changed = false
    for (const win of windows.value) {
      const next = clampFloatingBounds(win, MIN_W, MIN_H)
      if (next.x !== win.x || next.y !== win.y || next.w !== win.w || next.h !== win.h) {
        Object.assign(win, next)
        changed = true
      }
    }
    if (changed) persist()
  }

  return {
    windows,
    windowId,
    isOpen,
    open,
    focus,
    close,
    updateBounds,
    patchProps,
    clampAll,
    MIN_W,
    MIN_H,
  }
})

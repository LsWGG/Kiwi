/**
 * 「贴一贴」浮窗：把笔记以独立便签窗口置顶到页面上。
 *
 * 窗口只记录位置 / 尺寸等 UI 状态，笔记正文由窗口自己按 noteId 拉取，
 * 不复用工作区的 currentNote，因此不会打扰主编辑区正在打开的笔记。
 */
import { defineStore } from 'pinia'
import { ref } from 'vue'
import { uiScaleForWidth } from '@/utils/uiScale'
import { clampFloatingBounds } from '@/utils/floatingWindow'
import type { NoteSummary } from './notes'

export interface StickyWindow {
  /** 每篇笔记只保留一个便签窗口，直接用 noteId。 */
  id: string
  noteId: string
  kbId: string
  title: string
  kind: string
  x: number
  y: number
  w: number
  h: number
  z: number
}

const STORAGE_KEY = 'kiwi.sticky.windows'
const MIN_W = 300
const MIN_H = 220
const DEFAULT_W = 420
const DEFAULT_H = 340

function clampToViewport(win: Pick<StickyWindow, 'x' | 'y' | 'w' | 'h'>): {
  x: number
  y: number
  w: number
  h: number
} {
  return clampFloatingBounds(win, MIN_W, MIN_H)
}

function loadSaved(): StickyWindow[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return []
    const parsed = JSON.parse(raw)
    if (!Array.isArray(parsed)) return []
    return parsed
      .filter((item) => item && typeof item.noteId === 'string' && typeof item.kbId === 'string')
      .slice(0, 12)
      .map((item, index) => {
        const bounds = clampToViewport({
          x: Number(item.x) || 120,
          y: Number(item.y) || 96,
          w: Number(item.w) || DEFAULT_W,
          h: Number(item.h) || DEFAULT_H,
        })
        return {
          id: item.noteId,
          noteId: item.noteId,
          kbId: item.kbId,
          title: String(item.title || ''),
          kind: String(item.kind || 'doc'),
          z: 60 + index,
          ...bounds,
        }
      })
  } catch {
    return []
  }
}

export const useStickyNotesStore = defineStore('stickyNotes', () => {
  const windows = ref<StickyWindow[]>(loadSaved())
  let zCounter = windows.value.reduce((max, win) => Math.max(max, win.z), 60)

  function persist() {
    try {
      localStorage.setItem(
        STORAGE_KEY,
        JSON.stringify(
          windows.value.map(({ noteId, kbId, title, kind, x, y, w, h }) => ({
            noteId,
            kbId,
            title,
            kind,
            x,
            y,
            w,
            h,
          })),
        ),
      )
    } catch {
      /* 隐私模式下 localStorage 不可用，浮窗仍可在当前会话使用。 */
    }
  }

  /** 打开 / 聚焦便签；多开时按 24px 层叠偏移，避免完全遮挡。 */
  function open(note: Pick<NoteSummary, 'id' | 'title' | 'kind'>, kbId: string) {
    const existing = windows.value.find((win) => win.noteId === note.id)
    if (existing) {
      existing.kbId = kbId
      existing.title = note.title
      existing.kind = note.kind
      // 浏览器窗口缩小或页面缩放后，旧位置可能整个落在视口外：
      // 命中已有窗口时先收回可视区域，否则「贴一贴」看起来毫无反应。
      Object.assign(existing, clampToViewport(existing))
      focus(existing.id)
      return existing.id
    }
    const offset = (windows.value.length % 6) * 24
    const scale = uiScaleForWidth(window.innerWidth)
    const bounds = clampToViewport({
      x: Math.max(8, window.innerWidth - DEFAULT_W * scale - 48 - offset),
      y: 96 + offset,
      w: DEFAULT_W,
      h: DEFAULT_H,
    })
    zCounter += 1
    windows.value.push({
      id: note.id,
      noteId: note.id,
      kbId,
      title: note.title,
      kind: note.kind,
      z: zCounter,
      ...bounds,
    })
    persist()
    return note.id
  }

  function focus(id: string) {
    const win = windows.value.find((item) => item.id === id)
    if (!win) return
    Object.assign(win, clampToViewport(win))
    zCounter += 1
    win.z = zCounter
    persist()
  }

  /** 视口变化（窗口缩放、页面缩放）后把全部便签收回可视区域。 */
  function clampAll() {
    let changed = false
    for (const win of windows.value) {
      const next = clampToViewport(win)
      if (next.x !== win.x || next.y !== win.y || next.w !== win.w || next.h !== win.h) {
        Object.assign(win, next)
        changed = true
      }
    }
    if (changed) persist()
  }

  function close(id: string) {
    windows.value = windows.value.filter((win) => win.id !== id)
    persist()
  }

  function updateBounds(
    id: string,
    patch: Partial<Pick<StickyWindow, 'x' | 'y' | 'w' | 'h'>>,
  ) {
    const win = windows.value.find((item) => item.id === id)
    if (!win) return
    Object.assign(win, clampToViewport({ ...win, ...patch }))
    persist()
  }

  function rename(id: string, title: string) {
    const win = windows.value.find((item) => item.id === id)
    if (!win) return
    win.title = title
    persist()
  }

  function closeAll() {
    windows.value = []
    persist()
  }

  return {
    windows,
    open,
    focus,
    close,
    closeAll,
    clampAll,
    updateBounds,
    rename,
    MIN_W,
    MIN_H,
  }
})

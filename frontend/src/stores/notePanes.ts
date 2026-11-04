/**
 * 笔记分栏工作区：停靠式布局树 + 活动窗口 + 每知识库持久化。
 *
 * 一个 pane 只承载一个 target（笔记 / 网页 / 文件）；打开已存在的 target
 * 会聚焦而不是重复开栏。超过 MAX_PANES 时替换最久未使用的窗口。
 */
import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import {
  MAX_PANES,
  buildPreset,
  createLeaf,
  findPane,
  flattenPanes,
  leastRecentlyUsed,
  paneUid,
  parseStoredLayout,
  removePane,
  replacePaneTarget,
  sameTarget,
  splitPaneAt,
  swapPaneTargets,
  updateSplitSizes,
  type DockZone,
  type PaneLeaf,
  type PaneNode,
  type PanePreset,
  type PaneSplit,
  type PaneTarget,
} from '@/components/notes/workspace/paneLayout'

const STORAGE_PREFIX = 'kiwi.note.panes.v1.'
const SAVE_DELAY_MS = 300

export const useNotePanesStore = defineStore('notePanes', () => {
  const enabled = ref(false)
  const root = ref<PaneNode | null>(null)
  const activePaneId = ref<string | null>(null)
  const lastUsed = ref<Record<string, number>>({})

  /** 拖拽中的临时 UI 状态，不持久化。 */
  const dragSourceId = ref<string | null>(null)
  const dropHint = ref<{ paneId: string; zone: DockZone } | null>(null)

  let loadedKbId: string | null = null
  let useCounter = 0
  let saveTimer: number | null = null

  const panes = computed(() => flattenPanes(root.value))
  const count = computed(() => panes.value.length)
  const activePane = computed(() => findPane(root.value, activePaneId.value))
  const activeTarget = computed<PaneTarget | null>(() => activePane.value?.target ?? null)

  function storageKey(kbId: string) {
    return `${STORAGE_PREFIX}${kbId}`
  }

  function touch(paneId: string) {
    useCounter += 1
    lastUsed.value = { ...lastUsed.value, [paneId]: useCounter }
  }

  function scheduleSave() {
    if (saveTimer !== null) return
    saveTimer = window.setTimeout(() => {
      saveTimer = null
      saveNow()
    }, SAVE_DELAY_MS)
  }

  function saveNow(kbId: string | null = loadedKbId) {
    if (saveTimer !== null) {
      window.clearTimeout(saveTimer)
      saveTimer = null
    }
    if (!kbId) return
    try {
      if (!root.value) {
        localStorage.removeItem(storageKey(kbId))
        return
      }
      localStorage.setItem(
        storageKey(kbId),
        JSON.stringify({
          version: 1,
          enabled: enabled.value,
          root: root.value,
          activePaneId: activePaneId.value,
          lastUsed: lastUsed.value,
        }),
      )
    } catch {
      /* 隐私模式 / 配额不足时忽略，不阻塞交互 */
    }
  }

  /** 切换知识库时先保存旧库，再恢复目标库的布局；同一 kb 幂等。 */
  function load(kbId: string | null) {
    if (!kbId) {
      if (loadedKbId) saveNow(loadedKbId)
      loadedKbId = null
      enabled.value = false
      root.value = null
      activePaneId.value = null
      lastUsed.value = {}
      return
    }
    if (loadedKbId === kbId) return
    if (loadedKbId) saveNow(loadedKbId)
    loadedKbId = kbId
    enabled.value = false
    root.value = null
    activePaneId.value = null
    lastUsed.value = {}
    try {
      const raw = localStorage.getItem(storageKey(kbId))
      if (!raw) return
      const stored = parseStoredLayout(JSON.parse(raw))
      if (!stored) {
        localStorage.removeItem(storageKey(kbId))
        return
      }
      root.value = stored.root
      enabled.value = stored.enabled
      activePaneId.value = stored.activePaneId
      lastUsed.value = stored.lastUsed
      useCounter = Math.max(0, ...Object.values(stored.lastUsed))
    } catch {
      try {
        localStorage.removeItem(storageKey(kbId))
      } catch {
        /* ignore */
      }
    }
  }

  /** 确保分栏处于开启状态；没有布局时用 noteId 起一栏。 */
  function enter(kbId: string | null, noteId?: string | null) {
    if (!kbId) return
    if (loadedKbId !== kbId) load(kbId)
    enabled.value = true
    if (!root.value) {
      if (noteId) {
        const leaf = createLeaf({ kind: 'note', noteId, kbId })
        root.value = leaf
        activePaneId.value = leaf.id
        touch(leaf.id)
      }
      scheduleSave()
      return
    }
    if (noteId) {
      const existing = panes.value.find(
        (pane) => pane.target.kind === 'note' && pane.target.noteId === noteId,
      )
      if (existing) {
        activePaneId.value = existing.id
        touch(existing.id)
      } else {
        openNote(kbId, noteId)
      }
    } else if (!findPane(root.value, activePaneId.value)) {
      const first = panes.value[0]
      if (first) {
        activePaneId.value = first.id
        touch(first.id)
      }
    }
    scheduleSave()
  }

  function exit() {
    enabled.value = false
    saveNow()
  }

  function activate(paneId: string) {
    if (!findPane(root.value, paneId)) return
    activePaneId.value = paneId
    touch(paneId)
    scheduleSave()
  }

  function addTarget(target: PaneTarget): PaneLeaf | null {
    const existing = panes.value.find((pane) => sameTarget(pane.target, target))
    if (existing) {
      activate(existing.id)
      return existing
    }
    if (!root.value) {
      const leaf = createLeaf(target)
      root.value = leaf
      activePaneId.value = leaf.id
      touch(leaf.id)
      scheduleSave()
      return leaf
    }
    const leaves = panes.value
    const activeId =
      activePaneId.value && findPane(root.value, activePaneId.value)
        ? activePaneId.value
        : leaves[0]?.id ?? null
    if (leaves.length >= MAX_PANES) {
      const victim = leastRecentlyUsed(leaves, lastUsed.value, activeId)
      if (!victim) return null
      root.value = replacePaneTarget(root.value, victim.id, target)
      activePaneId.value = victim.id
      touch(victim.id)
      scheduleSave()
      return { ...victim, target }
    }
    const anchorId = activeId ?? leaves[0]?.id
    if (!anchorId) return null
    const leaf = createLeaf(target)
    root.value = splitPaneAt(root.value, anchorId, leaf, 'right')
    activePaneId.value = leaf.id
    touch(leaf.id)
    scheduleSave()
    return leaf
  }

  function openNote(kbId: string, noteId: string) {
    if (loadedKbId !== kbId) load(kbId)
    return addTarget({ kind: 'note', noteId, kbId })
  }

  function openUrl(target: { url: string; title: string; site?: string }) {
    return addTarget({ kind: 'url', ...target })
  }

  function openFile(target: {
    url: string
    filename: string
    contentType: string
    size?: number
  }) {
    return addTarget({ kind: 'file', ...target })
  }

  /** 关闭一栏，返回关闭后应激活的窗口（布局为空时返回 null）。 */
  function closePane(paneId: string): PaneLeaf | null {
    if (!root.value) return null
    const before = flattenPanes(root.value)
    const index = before.findIndex((pane) => pane.id === paneId)
    if (index < 0) return findPane(root.value, activePaneId.value)
    root.value = removePane(root.value, paneId)
    const nextLastUsed = { ...lastUsed.value }
    delete nextLastUsed[paneId]
    lastUsed.value = nextLastUsed
    if (!root.value) {
      activePaneId.value = null
      enabled.value = false
      saveNow()
      return null
    }
    const after = flattenPanes(root.value)
    if (activePaneId.value === paneId || !findPane(root.value, activePaneId.value)) {
      const neighbor = after[Math.min(index, after.length - 1)] ?? after[0]
      activePaneId.value = neighbor?.id ?? null
      if (activePaneId.value) touch(activePaneId.value)
    }
    scheduleSave()
    return findPane(root.value, activePaneId.value)
  }

  /**
   * 拖动停靠：先把源栏从原位置移除，再按 zone 拆开目标栏；
   * center 交换两栏内容。返回是否发生了变化。
   */
  function movePane(sourceId: string, targetId: string, zone: DockZone): boolean {
    if (!root.value || sourceId === targetId) return false
    const source = findPane(root.value, sourceId)
    const target = findPane(root.value, targetId)
    if (!source || !target) return false
    if (zone === 'center') {
      root.value = swapPaneTargets(root.value, sourceId, targetId)
      activePaneId.value = sourceId
      touch(sourceId)
      scheduleSave()
      return true
    }
    const moved: PaneLeaf = { ...source, id: paneUid() }
    const next = removePane(root.value, sourceId)
    if (!next) return false
    if (!findPane(next, targetId)) return false
    const nextLastUsed = { ...lastUsed.value }
    delete nextLastUsed[sourceId]
    lastUsed.value = nextLastUsed
    root.value = splitPaneAt(next, targetId, moved, zone)
    activePaneId.value = moved.id
    touch(moved.id)
    scheduleSave()
    return true
  }

  function setSplitSizes(splitId: string, sizes: number[]) {
    if (!root.value) return
    root.value = updateSplitSizes(root.value, splitId, sizes)
    scheduleSave()
  }

  function resetSplitSizes(splitId: string) {
    if (!root.value) return
    const split = findSplitById(root.value, splitId)
    if (!split) return
    setSplitSizes(splitId, split.children.map(() => 100 / split.children.length))
  }

  function findSplitById(node: PaneNode, id: string): PaneSplit | null {
    if (node.type === 'pane') return null
    if (node.id === id) return node
    for (const child of node.children) {
      const found = findSplitById(child, id)
      if (found) return found
    }
    return null
  }

  function applyPreset(preset: PanePreset) {
    const leaves = panes.value
    if (leaves.length < 2) return
    root.value = buildPreset(leaves, preset)
    scheduleSave()
  }

  function beginDrag(paneId: string) {
    dragSourceId.value = paneId
    dropHint.value = null
  }

  function setDropHint(paneId: string | null, zone: DockZone = 'center') {
    if (!paneId || paneId === dragSourceId.value) {
      dropHint.value = null
      return
    }
    dropHint.value = { paneId, zone }
  }

  function endDrag() {
    dragSourceId.value = null
    dropHint.value = null
  }

  return {
    enabled,
    root,
    activePaneId,
    lastUsed,
    dragSourceId,
    dropHint,
    panes,
    count,
    activePane,
    activeTarget,
    load,
    saveNow,
    enter,
    exit,
    activate,
    openNote,
    openUrl,
    openFile,
    closePane,
    movePane,
    setSplitSizes,
    resetSplitSizes,
    applyPreset,
    beginDrag,
    setDropHint,
    endDrag,
  }
})

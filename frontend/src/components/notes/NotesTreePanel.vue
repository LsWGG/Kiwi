<script setup lang="ts">
/** 左侧工作区目录：多级分组、拖拽排序/移动、搜索、右键菜单。 */
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import {
  useNotesStore,
  type NoteFolder,
  type NoteOut,
  type NoteSummary,
  type NoteTag,
} from '@/stores/notes'
import KiwiIcon from '@/components/ui/KiwiIcon.vue'
import KiwiConfirm from '@/components/ui/KiwiConfirm.vue'
import KiwiModal from '@/components/ui/KiwiModal.vue'
import KiwiEmpty from '@/components/ui/KiwiEmpty.vue'
import NotesTreeNode from './NotesTreeNode.vue'
import NoteCreateMenu from './NoteCreateMenu.vue'
import NoteContextMenu from './NoteContextMenu.vue'
import LinkCreateDialog from './LinkCreateDialog.vue'
import NoteImportDialog from './NoteImportDialog.vue'
import NoteEmojiPicker from './NoteEmojiPicker.vue'
import NoteTagEditor from './NoteTagEditor.vue'
import NoteMoveKbDialog from './NoteMoveKbDialog.vue'
import NoteLockDialog from './NoteLockDialog.vue'
import NoteTemplatePicker from './NoteTemplatePicker.vue'
import QuickCaptureDialog from './QuickCaptureDialog.vue'
import { useKbsStore } from '@/stores/kbs'
import type { DropPos, TreeRow } from './types'
import { exportActionsFor, runNoteExport, type ExportKey } from './noteExport'
import { toast } from '@/components/ui/toast'

const props = defineProps<{ activeId: string | null }>()
const emit = defineEmits<{
  (e: 'open-note', note: NoteOut | string): void
  (e: 'close-note'): void
  (e: 'open-search'): void
}>()

const notes = useNotesStore()
const kbs = useKbsStore()
const STORAGE_KEY = 'kiwi.notes.expanded'

// ---------- 目录独立收起 / 展开 ----------
const COLLAPSE_KEY = 'kiwi.notes.treeCollapsed'
const collapsed = ref((() => {
  try {
    return localStorage.getItem(COLLAPSE_KEY) === '1'
  } catch {
    return false
  }
})())

watch(collapsed, (value) => {
  try {
    localStorage.setItem(COLLAPSE_KEY, value ? '1' : '0')
  } catch {
    /* 隐私模式下忽略 */
  }
})

// ---------- 目录宽度：拖动调整 + 双击复位 ----------
const WIDTH_KEY = 'kiwi.notes.treeWidth'
const MIN_TREE_WIDTH = 220
const MAX_TREE_WIDTH = 520
const DEFAULT_TREE_WIDTH = 280
const treeWidth = ref((() => {
  try {
    const raw = Number(localStorage.getItem(WIDTH_KEY))
    if (Number.isFinite(raw) && raw > 0) {
      return Math.min(MAX_TREE_WIDTH, Math.max(MIN_TREE_WIDTH, Math.round(raw)))
    }
  } catch {
    /* 隐私模式下忽略 */
  }
  return DEFAULT_TREE_WIDTH
})())
const resizing = ref(false)
let resizeStartX = 0
let resizeStartWidth = 0

function clampTreeWidth(value: number) {
  return Math.min(MAX_TREE_WIDTH, Math.max(MIN_TREE_WIDTH, Math.round(value)))
}

function onResizeMove(event: MouseEvent) {
  if (!resizing.value) return
  // 以按下时的宽度为基准按位移计算，避免目录不在视口最左侧时宽度瞬间跳到鼠标坐标
  treeWidth.value = clampTreeWidth(
    resizeStartWidth + (event.clientX - resizeStartX),
  )
}

function stopResize() {
  if (!resizing.value) return
  resizing.value = false
  document.removeEventListener('mousemove', onResizeMove)
  document.removeEventListener('mouseup', stopResize)
  document.body.style.userSelect = ''
  document.body.style.cursor = ''
  try {
    localStorage.setItem(WIDTH_KEY, String(treeWidth.value))
  } catch {
    /* 隐私模式下忽略 */
  }
}

function startResize(event: MouseEvent) {
  if (collapsed.value) return
  event.preventDefault()
  resizeStartX = event.clientX
  resizeStartWidth = treeWidth.value
  resizing.value = true
  document.body.style.userSelect = 'none'
  document.body.style.cursor = 'col-resize'
  document.addEventListener('mousemove', onResizeMove)
  document.addEventListener('mouseup', stopResize)
}

function resetTreeWidth() {
  treeWidth.value = DEFAULT_TREE_WIDTH
  try {
    localStorage.setItem(WIDTH_KEY, String(treeWidth.value))
  } catch {
    /* 隐私模式下忽略 */
  }
}

onBeforeUnmount(stopResize)

const searchInput = ref<HTMLInputElement | null>(null)

async function expandAndSearch() {
  collapsed.value = false
  await nextTick()
  searchInput.value?.focus()
}

// ---------- 库视图：标签 / 归档 / 回收站 ----------
type LibraryMode = 'tree' | 'tags' | 'archived' | 'trash'

const mode = ref<LibraryMode>('tree')
const modeLoading = ref(false)
const selectedTagIds = ref<string[]>([])
const tagSort = ref<'usage' | 'recent' | 'name'>('usage')

const MODE_TABS: Array<{ key: LibraryMode; label: string; icon: string }> = [
  { key: 'tree', label: '工作区', icon: 'listTree' },
  { key: 'tags', label: '标签', icon: 'hash' },
  { key: 'archived', label: '归档', icon: 'folderOpen' },
  { key: 'trash', label: '回收站', icon: 'trash' },
]

watch(mode, async (next) => {
  if (next === 'tree') return
  modeLoading.value = true
  try {
    if (next === 'tags') await notes.fetchTags()
    else if (next === 'archived') await notes.fetchArchived()
    else if (next === 'trash') await notes.fetchTrash()
  } catch (e: any) {
    toast.error(e.message || '加载失败')
  } finally {
    modeLoading.value = false
  }
})

const selectedTags = computed(() =>
  notes.tags.filter((t) => selectedTagIds.value.includes(t.id)),
)

const TAGS_SORTED = computed(() => {
  const compare = (a: NoteTag, b: NoteTag) => {
    if (tagSort.value === 'name') return a.name.localeCompare(b.name, 'zh-CN')
    if (tagSort.value === 'recent') {
      const at = a.last_used_at ? Date.parse(a.last_used_at) : 0
      const bt = b.last_used_at ? Date.parse(b.last_used_at) : 0
      return bt - at || b.usage_count - a.usage_count
    }
    return b.usage_count - a.usage_count || a.name.localeCompare(b.name, 'zh-CN')
  }
  return [...notes.tags].sort(compare)
})

// 嵌套标签树：按 parent_id 展开，同级按当前排序规则排列
const tagRows = computed(() => {
  const byParent = new Map<string | null, NoteTag[]>()
  const ids = new Set(notes.tags.map((t) => t.id))
  for (const tag of TAGS_SORTED.value) {
    const parent = tag.parent_id && ids.has(tag.parent_id) ? tag.parent_id : null
    const list = byParent.get(parent) || []
    list.push(tag)
    byParent.set(parent, list)
  }
  const out: Array<NoteTag & { depth: number }> = []
  const seen = new Set<string>()
  const walk = (parent: string | null, depth: number) => {
    for (const tag of byParent.get(parent) || []) {
      if (seen.has(tag.id)) continue
      seen.add(tag.id)
      out.push({ ...tag, depth })
      walk(tag.id, depth + 1)
    }
  }
  walk(null, 0)
  // 防御环状 parent，剩余节点平铺
  for (const tag of TAGS_SORTED.value) {
    if (!seen.has(tag.id)) out.push({ ...tag, depth: 0 })
  }
  return out
})

const tagNotes = computed(() =>
  sortedNotes.value.filter((n) =>
    selectedTags.value.every((tag) => n.tags?.includes(tag.name)),
  ),
)

function toggleTag(id: string) {
  selectedTagIds.value = selectedTagIds.value.includes(id)
    ? selectedTagIds.value.filter((t) => t !== id)
    : [...selectedTagIds.value, id]
}

function clearTags() {
  selectedTagIds.value = []
}

function trashDaysLeft(updatedAt: string): number {
  const deleted = new Date(updatedAt).getTime()
  if (!Number.isFinite(deleted)) return 30
  const end = deleted + 30 * 24 * 60 * 60 * 1000
  return Math.max(0, Math.ceil((end - Date.now()) / (24 * 60 * 60 * 1000)))
}

const KIND_ICON: Record<string, string> = {
  doc: 'fileText',
  database: 'database',
  link: 'link2',
  import: 'fileImport',
  canvas: 'pen',
  notebook: 'notebook',
  sheet: 'table',
}

function kindIcon(kind: string): string {
  return KIND_ICON[kind] || 'file'
}

function formatDate(value?: string): string {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  return date.toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit' })
}

async function restoreArchived(id: string) {
  try {
    await notes.unarchiveNote(id)
    toast.success('已恢复到工作区')
  } catch (e: any) {
    toast.error(e.message || '取消归档失败')
  }
}

async function restoreFromTrash(id: string) {
  try {
    await notes.restoreNote(id)
    toast.success('已从回收站恢复')
  } catch (e: any) {
    toast.error(e.message || '恢复失败')
  }
}

const purgeTarget = ref<NoteSummary | null>(null)
const purgeOpen = computed({
  get: () => purgeTarget.value !== null,
  set: (v: boolean) => {
    if (!v) purgeTarget.value = null
  },
})

async function confirmPurge() {
  const target = purgeTarget.value
  purgeTarget.value = null
  if (!target) return
  try {
    await notes.permanentDeleteNote(target.id)
    toast.success('已永久删除')
  } catch (e: any) {
    toast.error(e.message || '永久删除失败')
  }
}

const emptyTrashOpen = ref(false)

async function confirmEmptyTrash() {
  emptyTrashOpen.value = false
  try {
    await notes.emptyTrash()
    toast.success('回收站已清空')
  } catch (e: any) {
    toast.error(e.message || '清空回收站失败')
  }
}

function loadExpanded(): Set<string> | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (raw === null) return null
    const list = JSON.parse(raw)
    return new Set(Array.isArray(list) ? list.filter((x) => typeof x === 'string') : [])
  } catch {
    return new Set()
  }
}

const stored = loadExpanded()
const expanded = ref<Set<string>>(stored ?? new Set())
let seeded = stored !== null

watch(
  expanded,
  (set) => {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify([...set]))
    } catch {
      /* 忽略隐私模式下的写入失败 */
    }
  },
  { deep: true },
)

watch(
  () => notes.folders,
  (folders) => {
    if (seeded || !folders.length) return
    expanded.value = new Set(folders.map((f) => f.id))
    seeded = true
  },
  { immediate: true },
)

const search = ref('')

const notePinned = (note: NoteSummary) => !!note.props_json?.pinned

const sortedFolders = computed(() =>
  [...notes.folders].sort(
    (a, b) =>
      Number(!!b.pinned) - Number(!!a.pinned) ||
      a.sort_order - b.sort_order ||
      a.name.localeCompare(b.name, 'zh-CN'),
  ),
)
const sortedNotes = computed(() =>
  [...notes.notes].sort(
    (a, b) =>
      Number(notePinned(b)) - Number(notePinned(a)) ||
      a.sort_order - b.sort_order ||
      a.title.localeCompare(b.title, 'zh-CN'),
  ),
)

/** 某个父笔记的直接子笔记，沿用同级排序规则。 */
function noteChildren(parentNoteId: string): NoteSummary[] {
  return sortedNotes.value.filter((note) => note.parent_note_id === parentNoteId)
}

/** 顶层「收件箱」分组始终置顶，并使用独立配色。 */
const inboxRoots = computed(() =>
  sortedFolders.value.filter((f) => !f.parent_id && f.name.trim() === '收件箱'),
)
const inboxIds = computed(() => new Set(inboxRoots.value.map((folder) => folder.id)))

/** 置顶项统一提升到根级（与收件箱同级），不再留在原目录内。 */
const pinnedFolders = computed(() =>
  sortedFolders.value.filter(
    (folder) => !!folder.pinned && !inboxIds.value.has(folder.id),
  ),
)
const pinnedNotes = computed(() => sortedNotes.value.filter(notePinned))

type MixedNode =
  | {
      type: 'folder'
      id: string
      pinned: boolean
      sort_order: number
      label: string
      folder: NoteFolder
    }
  | {
      type: 'note'
      id: string
      pinned: boolean
      sort_order: number
      label: string
      note: NoteSummary
    }

/** 同一层级的分组 + 活跃笔记，按共享 sort_order 混合排序。 */
function mixedChildren(parentId: string | null): MixedNode[] {
  const list: MixedNode[] = [
    ...sortedFolders.value
      .filter((folder) => folder.parent_id === parentId)
      .map((folder) => ({
        type: 'folder' as const,
        id: folder.id,
        pinned: !!folder.pinned,
        sort_order: folder.sort_order,
        label: folder.name,
        folder,
      })),
    ...sortedNotes.value
      // 子笔记只挂在父笔记下，不重复出现在分组层级
      .filter((note) => note.folder_id === parentId && !note.parent_note_id)
      .map((note) => ({
        type: 'note' as const,
        id: note.id,
        pinned: notePinned(note),
        sort_order: note.sort_order,
        label: note.title || '无标题',
        note,
      })),
  ]
  return list.sort(
    (a, b) =>
      Number(b.pinned) - Number(a.pinned) ||
      a.sort_order - b.sort_order ||
      a.label.localeCompare(b.label, 'zh-CN'),
  )
}

const rows = computed<TreeRow[]>(() => {
  const q = search.value.trim().toLowerCase()
  if (q) {
    return sortedNotes.value
      .filter((n) => (n.title || '无标题').toLowerCase().includes(q))
      .map((n) => ({ type: 'note', id: n.id, depth: 0, note: n }))
  }
  const out: TreeRow[] = []
  // 防御异常数据造成的父子环，保证任何情况下目录都能渲染完成。
  const seenNotes = new Set<string>()
  const walkNote = (note: NoteSummary, depth: number, hoisted: boolean) => {
    if (seenNotes.has(note.id)) return
    seenNotes.add(note.id)
    const children = noteChildren(note.id)
    out.push({
      type: 'note',
      id: note.id,
      depth,
      note,
      hoisted,
      hasChildren: children.length > 0,
    })
    if (children.length && expanded.value.has(note.id)) {
      for (const child of children) walkNote(child, depth + 1, hoisted)
    }
  }
  const walk = (parentId: string | null, depth: number, hoisted = false) => {
    // 分组与笔记共用 sort_order：按混合顺序逐行输出，笔记可以排在分组上方。
    for (const node of mixedChildren(parentId)) {
      if (node.type === 'folder') {
        const folder = node.folder!
        if (!parentId && inboxIds.value.has(folder.id)) continue
        out.push({ type: 'folder', id: folder.id, depth, folder, hoisted })
        if (expanded.value.has(folder.id)) walk(folder.id, depth + 1, hoisted)
      } else {
        walkNote(node.note!, depth, hoisted)
      }
    }
  }
  const pushFolder = (
    folder: NoteFolder,
    depth: number,
    inbox = false,
    hoisted = false,
  ) => {
    out.push({ type: 'folder', id: folder.id, depth, folder, inbox, hoisted })
    if (expanded.value.has(folder.id)) walk(folder.id, depth + 1, hoisted)
  }

  // 1) 收件箱（含已展开的子项）永远第一
  for (const folder of inboxRoots.value) pushFolder(folder, 0, true)
  const inboxEnd = out.length

  // 2) 置顶区：根级快捷入口，同时原目录仍保留一项
  const pinnedStart = out.length
  for (const note of pinnedNotes.value) {
    out.push({ type: 'note', id: note.id, depth: 0, note, hoisted: true })
  }
  for (const folder of pinnedFolders.value) pushFolder(folder, 0, false, true)
  const pinnedEnd = out.length

  // 3) 其余根级目录与笔记
  walk(null, 0)

  // 收件箱与置顶区之间、置顶区与普通目录之间各加一条分割线。
  if (inboxRoots.value.length && pinnedStart < out.length) {
    out[pinnedStart].separatorBefore = true
  }
  if (pinnedStart < pinnedEnd && pinnedEnd < out.length) {
    out[pinnedEnd].separatorBefore = true
  } else if (!pinnedFolders.value.length && !pinnedNotes.value.length && inboxEnd < out.length) {
    out[inboxEnd].separatorBefore = true
  }
  return out
})

const total = computed(() => notes.notes.length)

// ---------- 打开笔记时在目录树中追踪其原位置 ----------
const treeScrollEl = ref<HTMLElement | null>(null)
let revealedActive: string | null = null

async function revealActiveNote(id: string | null, force = false) {
  if (!id || (!force && revealedActive === id)) return
  const note = notes.notes.find((n) => n.id === id)
  if (!note) return
  // 展开所有上级分组与父笔记，保证原目录中的那一行可见。
  const next = new Set(expanded.value)
  let parentId = note.folder_id
  let guard = 0
  while (parentId && guard++ < 100) {
    next.add(parentId)
    parentId = notes.folders.find((f) => f.id === parentId)?.parent_id ?? null
  }
  const byId = new Map(notes.notes.map((n) => [n.id, n]))
  let parentNoteId = note.parent_note_id
  guard = 0
  while (parentNoteId && guard++ < 100) {
    next.add(parentNoteId)
    parentNoteId = byId.get(parentNoteId)?.parent_note_id ?? null
  }
  if (next.size !== expanded.value.size) expanded.value = next
  await nextTick()
  const el = treeScrollEl.value?.querySelector<HTMLElement>(
    `[data-origin-note="${id}"]`,
  )
  el?.scrollIntoView({ block: 'nearest' })
  revealedActive = id
}

watch(
  () => props.activeId,
  (id) => {
    revealedActive = null
    revealActiveNote(id)
  },
  { immediate: true },
)

// 深链场景：activeId 先到、目录树后加载完成时补一次定位。
watch(
  () => notes.notes,
  () => { revealActiveNote(props.activeId) },
)

// ---------- 多选（Shift 连选 / Ctrl 间隔选） ----------
const selectedIds = ref<Set<string>>(new Set())
/** Shift 连选的起点 */
let anchorId: string | null = null

/** 可见的笔记行顺序，用于 Shift 区间选择（忽略分组行）。 */
function visibleNoteIds(): string[] {
  return rows.value.filter((r) => r.type === 'note').map((r) => r.id)
}

function noteRange(fromId: string, toId: string): string[] {
  const ids = visibleNoteIds()
  const a = ids.indexOf(fromId)
  const b = ids.indexOf(toId)
  if (a < 0 || b < 0) return [toId]
  const [lo, hi] = a < b ? [a, b] : [b, a]
  return ids.slice(lo, hi + 1)
}

function clearSelection() {
  selectedIds.value = new Set()
  anchorId = null
}

// 树刷新 / 搜索后剔除已不存在的选中项
watch(rows, (list) => {
  const alive = new Set(list.filter((r) => r.type === 'note').map((r) => r.id))
  const next = new Set<string>()
  let changed = false
  for (const id of selectedIds.value) {
    if (alive.has(id)) next.add(id)
    else changed = true
  }
  if (changed) selectedIds.value = next
  if (anchorId && !alive.has(anchorId)) anchorId = null
})

function toggle(row: TreeRow) {
  if (Date.now() < suppressClickUntil) return
  const set = new Set(expanded.value)
  if (set.has(row.id)) set.delete(row.id)
  else set.add(row.id)
  expanded.value = set
}
function expand(id: string) {
  if (expanded.value.has(id)) return
  const set = new Set(expanded.value)
  set.add(id)
  expanded.value = set
}

function isDescendant(candidateId: string, ancestorId: string): boolean {
  let current = notes.folders.find((f) => f.id === candidateId)
  let guard = 0
  while (current?.parent_id && guard++ < 100) {
    if (current.parent_id === ancestorId) return true
    current = notes.folders.find((f) => f.id === current!.parent_id)
  }
  return false
}

// ---------- 拖拽（指针实现，避免浏览器原生 DnD 的差异） ----------
const dragRow = ref<TreeRow | null>(null)
const dropState = ref<{ id: string; pos: DropPos } | null>(null)
const rootOver = ref(false)
const dragActive = ref(false)
const pointer = ref({ x: 0, y: 0 })
/** 按下时指针在行内的偏移：浮窗按同一握持点跟随，视觉上不会从指针旁边“飘”出去。 */
const grabOffset = ref({ x: 0, y: 0 })
/** 指针拖拽结束后短暂屏蔽 click，避免松手时顺手打开 / 折叠目标条目。 */
let suppressClickUntil = 0
let pointerStart: { x: number; y: number; row: TreeRow } | null = null
let pointerSession = false
let autoScrollTimer: number | null = null

const dragGhost = computed(() => {
  const row = dragRow.value
  if (!row) return null
  if (row.type === 'folder') {
    return { label: row.folder?.name || '分组', icon: 'folder', tone: 'text-amber-500' }
  }
  const kind = row.note?.kind ?? 'doc'
  const icon =
    kind === 'database'
      ? 'database'
      : kind === 'canvas'
        ? 'pen'
        : kind === 'link'
          ? 'link2'
          : kind === 'import'
            ? 'fileImport'
            : kind === 'notebook'
              ? 'notebook'
              : kind === 'sheet'
                ? 'table'
                : 'fileText'
  return { label: row.note?.title || '无标题', icon, tone: 'text-kiwi-500' }
})

const ghostEl = ref<HTMLElement | null>(null)
const ghostWidth = ref(0)

/** 浮窗左上角：保持按下时指针在行内的相对位置，让指针始终“握”在浮窗上。 */
const ghostPos = computed(() => {
  // 抓取点靠行尾时，把水平偏移收缩到浮窗宽度内，避免指针落在浮窗右侧外面。
  const maxX = ghostWidth.value ? Math.max(ghostWidth.value - 24, 0) : Infinity
  const dx = Math.min(grabOffset.value.x, maxX)
  return {
    x: pointer.value.x - dx,
    y: pointer.value.y - grabOffset.value.y,
  }
})

// 浮窗渲染后量一次宽度，用于上面的握持点收缩；每次拖拽开始时重置。
watch(dragActive, async (active) => {
  ghostWidth.value = 0
  if (!active) return
  await nextTick()
  ghostWidth.value = ghostEl.value?.getBoundingClientRect().width ?? 0
})

/** 子笔记是否为某篇笔记的后代（用于阻止把笔记拖进自己的子树）。 */
function isNoteDescendant(candidateId: string, ancestorId: string): boolean {
  const byId = new Map(notes.notes.map((n) => [n.id, n]))
  let current = byId.get(candidateId)
  let guard = 0
  while (current?.parent_note_id && guard++ < 200) {
    if (current.parent_note_id === ancestorId) return true
    current = byId.get(current.parent_note_id)
  }
  return false
}

/** 拖拽悬停时自动展开折叠的分组 / 父笔记，避免必须先手动展开。 */
let autoExpand: { id: string; timer: number } | null = null

function cancelAutoExpand() {
  if (!autoExpand) return
  window.clearTimeout(autoExpand.timer)
  autoExpand = null
}

function scheduleAutoExpand(id: string, pos: DropPos) {
  if (pos !== 'into' || expanded.value.has(id)) {
    cancelAutoExpand()
    return
  }
  if (autoExpand?.id === id) return
  cancelAutoExpand()
  const timer = window.setTimeout(() => {
    autoExpand = null
    expand(id)
  }, 550)
  autoExpand = { id, timer }
}

/** 根据指针落在行内的相对位置，计算插入位置；返回 null 表示该目标不合法。 */
function resolveDropPos(
  drag: TreeRow,
  row: TreeRow,
  rect: DOMRect,
  clientY: number,
): DropPos | null {
  if (drag.type === row.type && drag.id === row.id) return null
  const rel = (clientY - rect.top) / Math.max(rect.height, 1)
  if (row.type === 'folder') {
    if (drag.type === 'folder' && isDescendant(row.folder!.id, drag.id)) return null
    // 上下边缘 = 与分组同级排序（可把笔记拖到分组上方），中间 = 放入分组。
    return rel < 0.26 ? 'before' : rel > 0.74 ? 'after' : 'into'
  }
  if (drag.type === 'note') {
    if (isNoteDescendant(row.id, drag.id)) return null
    // 中间 = 变成目标笔记的子笔记，上下边缘 = 与目标笔记同级排序。
    return rel < 0.3 ? 'before' : rel > 0.7 ? 'after' : 'into'
  }
  // 分组不能放进笔记；只允许在根级笔记旁参与同一分组层级的排序。
  if (row.note!.parent_note_id) return null
  return rel < 0.5 ? 'before' : 'after'
}

function updateDropFromPoint(x: number, y: number) {
  pointer.value = { x, y }
  const drag = dragRow.value
  if (!drag) return
  const target = document.elementFromPoint(x, y) as Element | null
  if (target?.closest('[data-tree-root-drop]')) {
    dropState.value = null
    cancelAutoExpand()
    rootOver.value = true
    return
  }
  rootOver.value = false
  const rowEl = target?.closest('[data-tree-row]') as HTMLElement | null
  if (!rowEl || rowEl.dataset.treeRowHoisted) {
    dropState.value = null
    cancelAutoExpand()
    return
  }
  const key = rowEl.dataset.treeRow
  const row = rows.value.find((item) => `${item.type}:${item.id}` === key)
  if (!row) {
    dropState.value = null
    cancelAutoExpand()
    return
  }
  const pos = resolveDropPos(drag, row, rowEl.getBoundingClientRect(), y)
  if (!pos) {
    dropState.value = null
    cancelAutoExpand()
    return
  }
  dropState.value = { id: row.id, pos }
  scheduleAutoExpand(row.id, pos)
}

function stopAutoScroll() {
  if (autoScrollTimer === null) return
  window.clearInterval(autoScrollTimer)
  autoScrollTimer = null
}

/** 拖到目录上下边缘时自动滚动，便于跨屏移动。 */
function startAutoScroll() {
  stopAutoScroll()
  autoScrollTimer = window.setInterval(() => {
    const el = treeScrollEl.value
    if (!dragActive.value || !el) return
    const rect = el.getBoundingClientRect()
    const { x, y } = pointer.value
    if (x < rect.left || x > rect.right) return
    const edge = 32
    let delta = 0
    if (y < rect.top + edge) delta = -12
    else if (y > rect.bottom - edge) delta = 12
    if (!delta) return
    const before = el.scrollTop
    el.scrollTop = before + delta
    if (el.scrollTop !== before) updateDropFromPoint(x, y)
  }, 50)
}

function onRowPointerDown(event: PointerEvent, row: TreeRow) {
  if (event.button !== 0 || event.pointerType === 'touch') return
  if (row.hoisted || row.inbox) return
  const target = event.target as Element | null
  if (target?.closest('button, input, a, [contenteditable="true"]')) return
  const rowEl = target?.closest('[data-tree-row]') as HTMLElement | null
  if (rowEl) {
    const rect = rowEl.getBoundingClientRect()
    grabOffset.value = {
      x: Math.min(Math.max(event.clientX - rect.left, 0), rect.width),
      y: Math.min(Math.max(event.clientY - rect.top, 0), rect.height),
    }
  } else {
    grabOffset.value = { x: 0, y: 0 }
  }
  pointerStart = { x: event.clientX, y: event.clientY, row }
  pointerSession = true
  window.addEventListener('pointermove', onWindowPointerMove)
  window.addEventListener('pointerup', onWindowPointerUp)
  window.addEventListener('pointercancel', onWindowPointerUp)
  window.addEventListener('keydown', onDragKeyDown)
}

function onWindowPointerMove(event: PointerEvent) {
  if (!pointerSession) return
  if ((event.buttons & 1) === 0) {
    cleanupPointerSession()
    return
  }
  if (!dragActive.value) {
    const start = pointerStart
    if (!start) return
    if (Math.hypot(event.clientX - start.x, event.clientY - start.y) < 4) return
    dragActive.value = true
    dragRow.value = start.row
    document.body.classList.add('kiwi-tree-dragging')
    startAutoScroll()
  }
  event.preventDefault()
  updateDropFromPoint(event.clientX, event.clientY)
}

function cleanupPointerSession() {
  pointerSession = false
  pointerStart = null
  dragActive.value = false
  dragRow.value = null
  dropState.value = null
  rootOver.value = false
  grabOffset.value = { x: 0, y: 0 }
  stopAutoScroll()
  cancelAutoExpand()
  document.body.classList.remove('kiwi-tree-dragging')
  window.removeEventListener('pointermove', onWindowPointerMove)
  window.removeEventListener('pointerup', onWindowPointerUp)
  window.removeEventListener('pointercancel', onWindowPointerUp)
  window.removeEventListener('keydown', onDragKeyDown)
}

function onDragKeyDown(event: KeyboardEvent) {
  if (event.key === 'Escape') cleanupPointerSession()
}

async function moveDragToRoot(drag: TreeRow) {
  if (drag.type === 'note' && drag.note) {
    await notes.moveNoteTo(drag.note.id, { folder_id: null, parent_note_id: null })
  } else if (drag.type === 'folder' && drag.folder) {
    await notes.updateFolder(drag.folder.id, { parent_id: null })
  }
}

async function onWindowPointerUp() {
  if (!pointerSession) return
  const active = dragActive.value
  const drag = dragRow.value
  const state = dropState.value
  const overRoot = rootOver.value
  cleanupPointerSession()
  if (!active || !drag) return
  // 拖动结束后浏览器仍会派发一次 click，短暂屏蔽避免误打开。
  suppressClickUntil = Date.now() + 400
  try {
    if (overRoot) {
      await moveDragToRoot(drag)
      return
    }
    if (!state) return
    const row = rows.value.find((item) => item.id === state.id)
    if (!row) return
    if (drag.type === 'note' && drag.note) await dropNote(drag.note, row, state.pos)
    else if (drag.type === 'folder' && drag.folder) await dropFolder(drag.folder, row, state.pos)
  } catch (e: any) {
    toast.error(e.message || '移动失败')
    await notes.fetchTree()
  }
}

/**
 * 构造目标层级的完整混合排序列表（分组 + 笔记），把拖拽项插到目标位置。
 * 后端 tree-reorder 要求提交该层级的全部节点。
 */
function mixedReorderItems(
  parentId: string | null,
  moving: { type: 'folder' | 'note'; id: string },
  target: { type: 'folder' | 'note'; id: string },
  after: boolean,
) {
  const items = mixedChildren(parentId)
    .filter((node) => !(node.type === moving.type && node.id === moving.id))
    .map((node) => ({ type: node.type, id: node.id }))
  const index = items.findIndex(
    (node) => node.type === target.type && node.id === target.id,
  )
  if (index < 0) return null
  items.splice(index + (after ? 1 : 0), 0, moving)
  return items
}

/** 构造某个父笔记下全部直接子笔记的顺序，用于子笔记排序。 */
function childNoteReorderIds(
  parentNoteId: string,
  movingId: string,
  targetId: string,
  after: boolean,
): string[] | null {
  const ids = noteChildren(parentNoteId)
    .filter((note) => note.id !== movingId)
    .map((note) => note.id)
  const index = ids.indexOf(targetId)
  if (index < 0) return null
  ids.splice(index + (after ? 1 : 0), 0, movingId)
  return ids
}

async function dropNote(note: NoteSummary, target: TreeRow, pos: DropPos) {
  // 落在分组中部 = 放入分组内部；落在笔记中部 = 成为该笔记的子笔记。
  if (target.type === 'folder' && pos === 'into') {
    await notes.moveNoteTo(note.id, {
      folder_id: target.folder!.id,
      parent_note_id: null,
    })
    expand(target.id)
    return
  }
  if (target.type === 'note' && pos === 'into') {
    const parent = target.note!
    if (parent.id === note.id || isNoteDescendant(parent.id, note.id)) {
      toast.error('不能把笔记移到自己的子笔记下')
      return
    }
    await notes.moveNoteTo(note.id, {
      folder_id: parent.folder_id,
      parent_note_id: parent.id,
    })
    expand(parent.id)
    return
  }

  if (target.type === 'folder') {
    // 与分组同级排序（笔记可以排到分组上方）。
    const folderId = target.folder!.parent_id
    if (note.parent_note_id !== null || note.folder_id !== folderId) {
      await notes.moveNoteTo(note.id, { folder_id: folderId, parent_note_id: null })
    }
    const items = mixedReorderItems(
      folderId,
      { type: 'note', id: note.id },
      { type: 'folder', id: target.id },
      pos === 'after',
    )
    if (items) await notes.reorderTree(folderId, items)
    return
  }

  const targetNote = target.note!
  const parentNoteId = targetNote.parent_note_id
  if (
    parentNoteId === note.id ||
    (parentNoteId !== null && isNoteDescendant(parentNoteId, note.id))
  ) {
    toast.error('不能把笔记移到自己的子笔记下')
    return
  }

  if (parentNoteId === null) {
    // 根级笔记：与同分组内的分组 / 笔记混合排序。
    if (note.parent_note_id !== null || note.folder_id !== targetNote.folder_id) {
      await notes.moveNoteTo(note.id, {
        folder_id: targetNote.folder_id,
        parent_note_id: null,
      })
    }
    const items = mixedReorderItems(
      targetNote.folder_id,
      { type: 'note', id: note.id },
      { type: 'note', id: targetNote.id },
      pos === 'after',
    )
    if (items) await notes.reorderTree(targetNote.folder_id, items)
    return
  }

  // 子笔记之间排序：分组随父笔记，排序按父笔记下的完整子集提交。
  if (note.parent_note_id !== parentNoteId || note.folder_id !== targetNote.folder_id) {
    await notes.moveNoteTo(note.id, {
      folder_id: targetNote.folder_id,
      parent_note_id: parentNoteId,
    })
  }
  const ids = childNoteReorderIds(
    parentNoteId,
    note.id,
    targetNote.id,
    pos === 'after',
  )
  if (ids) await notes.reorder(null, 'note', ids, parentNoteId)
}

async function dropFolder(folder: NoteFolder, target: TreeRow, pos: DropPos | null) {
  if (target.type === 'folder' && (pos === 'into' || !pos)) {
    const targetFolder = target.folder!
    if (targetFolder.id === folder.id || isDescendant(targetFolder.id, folder.id)) {
      toast.error('不能把分组移到自己的子分组中')
      return
    }
    await notes.updateFolder(folder.id, { parent_id: targetFolder.id })
    expand(targetFolder.id)
    return
  }

  if (target.type === 'note') {
    // 分组只能与根级笔记 / 分组共用层级；子笔记的内层没有分组。
    const targetNote = target.note!
    if (targetNote.parent_note_id) {
      toast.error('分组不能放到子笔记层级')
      return
    }
    if (!pos) return
    const parentId = targetNote.folder_id
    if (parentId === folder.id || (parentId && isDescendant(parentId, folder.id))) {
      toast.error('不能把分组移到自己的子分组中')
      return
    }
    if (folder.parent_id !== parentId) {
      await notes.updateFolder(folder.id, { parent_id: parentId })
    }
    const items = mixedReorderItems(
      parentId,
      { type: 'folder', id: folder.id },
      { type: 'note', id: targetNote.id },
      pos === 'after',
    )
    if (items) await notes.reorderTree(parentId, items)
    return
  }

  if (!pos) return
  const parentId = target.folder!.parent_id
  if (parentId === folder.id || (parentId && isDescendant(parentId, folder.id))) {
    toast.error('不能把分组移到自己的子分组中')
    return
  }
  if (folder.parent_id !== parentId) {
    await notes.updateFolder(folder.id, { parent_id: parentId })
  }
  const items = mixedReorderItems(
    parentId,
    { type: 'folder', id: folder.id },
    { type: 'folder', id: target.id },
    pos === 'after',
  )
  if (items) await notes.reorderTree(parentId, items)
}

// ---------- 右键 / 重命名 / 删除 ----------
const menu = ref<{ open: boolean; x: number; y: number; row: TreeRow | null }>({
  open: false,
  x: 0,
  y: 0,
  row: null,
})
const renamingId = ref<string | null>(null)

function openMenu(event: MouseEvent, row: TreeRow) {
  if (row.type === 'note') {
    // 右击已选中的条目保留整组选择；否则把选择收缩到当前条目
    if (!selectedIds.value.has(row.id)) {
      selectedIds.value = new Set([row.id])
      anchorId = row.id
    }
  } else {
    clearSelection()
  }
  menu.value = { open: true, x: event.clientX, y: event.clientY, row }
}

const menuSelectionCount = computed(() =>
  menu.value.row?.type === 'note' ? Math.max(1, selectedIds.value.size) : 1,
)

/** 笔记右键菜单按类型提供不同导出格式；分组与多选不展示。 */
const menuExportActions = computed(() => {
  const row = menu.value.row
  if (!row || row.type !== 'note' || menuSelectionCount.value > 1) return []
  return exportActionsFor(row.note?.kind)
})

async function exportFromMenu(key: string) {
  const note = menu.value.row?.note
  if (!note) return
  try {
    await runNoteExport(note, key as ExportKey)
    toast.success(`已导出「${note.title || '无标题'}」`)
  } catch (e: any) {
    toast.error(e.message || '导出失败')
  }
}

function beginRenameFromMenu() {
  const row = menu.value.row
  if (row) renamingId.value = row.id
}

/** 置顶 / 取消置顶：分组写入 pinned 列，笔记写入 props_json.pinned。 */
async function setRowPinned(row: TreeRow, next: boolean) {
  try {
    if (row.type === 'folder') {
      if (!row.folder || row.inbox) return
      await notes.updateFolder(row.id, { pinned: next })
    } else {
      if (!row.note) return
      await notes.updateNote(row.id, { props_json: { pinned: next } })
    }
    toast.success(next ? '已置顶' : '已取消置顶')
  } catch (e: any) {
    toast.error(e.message || '置顶失败')
  }
}

async function togglePinFromMenu() {
  const row = menu.value.row
  if (!row) return
  const pinned = row.type === 'folder' ? !!row.folder?.pinned : notePinned(row.note!)
  await setRowPinned(row, !pinned)
}

/** 行尾图钉：一键取消置顶（置顶副本与原目录中的图标都可用）。 */
async function unpinFromRow(row: TreeRow) {
  const pinned = row.type === 'folder' ? !!row.folder?.pinned : notePinned(row.note!)
  if (!pinned) return
  await setRowPinned(row, false)
}

// 表情：右键菜单打开面板，选择后写入 props_json.emoji
const emojiPicker = ref<{ open: boolean; x: number; y: number; row: TreeRow | null }>({
  open: false,
  x: 0,
  y: 0,
  row: null,
})

function openEmojiFromMenu() {
  const row = menu.value.row
  if (!row || row.type !== 'note') return
  emojiPicker.value = { open: true, x: menu.value.x, y: menu.value.y, row }
}

// 标签：右键菜单打开设置弹窗（页头也有常驻入口）
const tagEditor = ref<{ open: boolean; row: TreeRow | null; tags: string[] }>({
  open: false,
  row: null,
  tags: [],
})

function openTagsFromMenu() {
  const row = menu.value.row
  if (!row || row.type !== 'note' || !row.note) return
  tagEditor.value = { open: true, row, tags: [...(row.note.tags || [])] }
}

async function onPickEmoji(emoji: string) {
  const row = emojiPicker.value.row
  emojiPicker.value.open = false
  if (!row?.note) return
  try {
    await notes.updateNote(row.id, { props_json: { emoji } })
  } catch (e: any) {
    toast.error(e.message || '设置表情失败')
  }
}

// 密码锁：设置 / 移除后刷新目录树上的锁标记
const locking = ref<TreeRow | null>(null)

function openLockFromMenu() {
  const row = menu.value.row
  if (row?.note) locking.value = row
}

async function onLockChanged() {
  const activeTarget = props.activeId && locking.value?.note?.id === props.activeId
  await notes.fetchTree()
  // 当前打开的就是这篇笔记时，同步一次状态（上锁 / 解锁都会改变可读性）。
  if (activeTarget && props.activeId) {
    await notes.getNote(props.activeId).catch(() => {})
  }
}

// 复制 / 归档 / 跨知识库移动
async function copyFromMenu() {
  const row = menu.value.row
  if (!row?.note) return
  try {
    const copy = await notes.copyNote(row.id)
    toast.success('已复制')
    emit('open-note', copy)
  } catch (e: any) {
    toast.error(e.message || '复制失败')
  }
}

async function archiveFromMenu() {
  const row = menu.value.row
  if (!row?.note) return
  try {
    await notes.archiveNote(row.id)
    if (props.activeId === row.id) emit('close-note')
    toast.success('已归档，可在「归档」视图中找回')
  } catch (e: any) {
    toast.error(e.message || '归档失败')
  }
}

const templateOpen = ref(false)
/** 快速捕获不再占用新建菜单，统一由全局快捷键唤起。 */
const captureOpen = ref(false)

/** Ctrl/Cmd + Shift + Space：随时呼出快速捕获。 */
function onQuickCaptureKey(event: KeyboardEvent) {
  if (!(event.ctrlKey || event.metaKey) || !event.shiftKey) return
  if (event.code !== 'Space') return
  const target = event.target as HTMLElement | null
  if (target?.isContentEditable) return
  event.preventDefault()
  captureOpen.value = true
}

onMounted(() => window.addEventListener('keydown', onQuickCaptureKey))
onBeforeUnmount(() => window.removeEventListener('keydown', onQuickCaptureKey))

// 窗口失焦 / 按 Esc 时取消拖拽，避免拖拽状态残留。
onMounted(() => window.addEventListener('blur', cleanupPointerSession))
onBeforeUnmount(() => {
  window.removeEventListener('blur', cleanupPointerSession)
  cleanupPointerSession()
})

function onTemplateCreated(note: NoteOut) {
  emit('open-note', note)
}

function onCaptured(note: NoteOut) {
  emit('open-note', note)
}

const moving = ref<TreeRow | null>(null)
const moveOpen = computed({
  get: () => moving.value !== null,
  set: (v: boolean) => {
    if (!v) moving.value = null
  },
})

function openMoveFromMenu() {
  const row = menu.value.row
  if (!row?.note) return
  moving.value = row
}

async function confirmMove(payload: { kbId: string; folderId: string | null }) {
  const row = moving.value
  if (!row?.note) return
  try {
    await notes.transferNote(row.note.id, payload.kbId, payload.folderId)
    if (props.activeId === row.note.id) emit('close-note')
    moving.value = null
    toast.success('已移动到目标知识库')
  } catch (e: any) {
    toast.error(e.message || '移动失败')
  }
}

async function onRename(row: TreeRow, name: string) {
  renamingId.value = null
  try {
    if (row.type === 'folder') await notes.updateFolder(row.id, { name })
    else await notes.updateNote(row.id, { title: name })
  } catch (e: any) {
    toast.error(e.message || '重命名失败')
    await notes.fetchTree()
  }
}

const deleting = ref<TreeRow | null>(null)
const deleteOpen = computed({
  get: () => deleting.value !== null,
  set: (v: boolean) => {
    if (!v) deleting.value = null
  },
})

/** 右键菜单的删除：多选时走批量删除，否则删除当前条目。 */
function deleteFromMenu() {
  const row = menu.value.row
  if (!row) return
  if (row.type === 'note' && selectedIds.value.size > 1) {
    batchIds.value = [...selectedIds.value]
    return
  }
  deleting.value = row
}

const batchIds = ref<string[]>([])
const batchDeleting = ref(false)
const batchOpen = computed({
  get: () => batchIds.value.length > 0,
  set: (v: boolean) => {
    if (!v) batchIds.value = []
  },
})

async function confirmBatchDelete() {
  const ids = [...batchIds.value]
  if (!ids.length) return
  batchDeleting.value = true
  let done = 0
  let failed = 0
  for (const id of ids) {
    try {
      await notes.deleteNote(id)
      done += 1
    } catch {
      failed += 1
    }
  }
  batchDeleting.value = false
  batchIds.value = []
  clearSelection()
  if (props.activeId && ids.includes(props.activeId)) emit('close-note')
  if (failed) toast.error(`已删除 ${done} 项，${failed} 项删除失败`)
  else toast.success(`已删除 ${done} 项`)
}

async function confirmDelete() {
  const row = deleting.value
  if (!row) return
  const wasActive = row.type === 'note' && props.activeId === row.id
  try {
    if (row.type === 'folder') await notes.deleteFolder(row.id)
    else await notes.deleteNote(row.id)
    if (row.type === 'note') {
      const next = new Set(selectedIds.value)
      next.delete(row.id)
      selectedIds.value = next
    }
    if (wasActive) emit('close-note')
    else if (props.activeId && row.type === 'folder') {
      const stillThere = notes.notes.some((n) => n.id === props.activeId)
      if (!stillThere) emit('close-note')
    }
    toast.success('已删除')
  } catch (e: any) {
    toast.error(e.message || '删除失败')
  } finally {
    deleting.value = null
  }
}

// ---------- 新建 ----------
const folderDialog = ref<{ open: boolean; parentId: string | null; name: string }>({
  open: false,
  parentId: null,
  name: '',
})
const folderInput = ref<HTMLInputElement | null>(null)

async function openFolderDialog(parentId: string | null = null) {
  folderDialog.value = { open: true, parentId, name: '' }
  await nextTick()
  folderInput.value?.focus()
}

async function confirmFolder() {
  const name = folderDialog.value.name.trim()
  if (!name) return
  const parentId = folderDialog.value.parentId
  try {
    const folder = await notes.createFolder(name, parentId)
    if (parentId) expand(parentId)
    folderDialog.value.open = false
    renamingId.value = folder.id
  } catch (e: any) {
    toast.error(e.message || '创建分组失败')
  }
}

/** 新建时的目标分组：顶部新建菜单为根级，右键菜单为当前条目所在层级。 */
const createFolderId = ref<string | null>(null)

async function createNoteAt(
  kind: 'doc' | 'canvas' | 'database' | 'notebook' | 'sheet',
  folderId: string | null = null,
  parentNoteId: string | null = null,
) {
  const titles = {
    doc: '无标题文档',
    canvas: '无标题画布',
    database: '无标题数据表',
    notebook: '无标题 Notebook',
    sheet: '无标题表格',
  } as const
  const names = {
    doc: '创建文档',
    canvas: '创建画布',
    database: '创建数据表',
    notebook: '创建 Notebook',
    sheet: '创建表格',
  } as const
  try {
    const note = await notes.createNote({
      title: titles[kind],
      kind,
      folder_id: folderId,
      parent_note_id: parentNoteId,
    })
    expandCreateTarget(folderId, parentNoteId)
    emit('open-note', note)
    renamingId.value = note.id
  } catch (e: any) {
    toast.error(e.message || `${names[kind]}失败`)
  }
}

/** 展开新建目标，保证新条目在目录树中立即可见。 */
function expandCreateTarget(folderId: string | null, parentNoteId: string | null) {
  if (parentNoteId) expand(parentNoteId)
  else if (folderId) expand(folderId)
}

const createDoc = (folderId: string | null = null) => createNoteAt('doc', folderId)
const createCanvas = (folderId: string | null = null) => createNoteAt('canvas', folderId)
const createDatabase = (folderId: string | null = null) => createNoteAt('database', folderId)
const createNotebook = (folderId: string | null = null) => createNoteAt('notebook', folderId)
const createSheet = (folderId: string | null = null) => createNoteAt('sheet', folderId)

const importOpen = ref(false)
const importFolderId = ref<string | null>(null)
const importParentNoteId = ref<string | null>(null)
const linkOpen = ref(false)
const linkFolderId = ref<string | null>(null)
const linkParentNoteId = ref<string | null>(null)
const templateFolderId = ref<string | null>(null)
const templateParentNoteId = ref<string | null>(null)

function openImport(folderId: string | null = null, parentNoteId: string | null = null) {
  importFolderId.value = folderId
  importParentNoteId.value = parentNoteId
  expandCreateTarget(folderId, parentNoteId)
  importOpen.value = true
}

function openLink(folderId: string | null = null, parentNoteId: string | null = null) {
  linkFolderId.value = folderId
  linkParentNoteId.value = parentNoteId
  expandCreateTarget(folderId, parentNoteId)
  linkOpen.value = true
}

function openTemplates(folderId: string | null = null, parentNoteId: string | null = null) {
  templateFolderId.value = folderId
  templateParentNoteId.value = parentNoteId
  expandCreateTarget(folderId, parentNoteId)
  templateOpen.value = true
}

function onCreated(note: NoteOut) {
  emit('open-note', note)
}

/** 右键菜单的新建目标：分组内新建；笔记下新建子笔记。 */
function menuCreateTarget(): { folderId: string | null; parentNoteId: string | null } {
  const row = menu.value.row
  if (!row) return { folderId: null, parentNoteId: null }
  if (row.type === 'folder') return { folderId: row.id, parentNoteId: null }
  return { folderId: row.note?.folder_id ?? null, parentNoteId: row.id }
}

function createFromMenu(kind: string) {
  const { folderId, parentNoteId } = menuCreateTarget()
  menu.value.open = false
  switch (kind) {
    case 'doc':
      void createNoteAt('doc', folderId, parentNoteId)
      break
    case 'canvas':
      void createNoteAt('canvas', folderId, parentNoteId)
      break
    case 'database':
      void createNoteAt('database', folderId, parentNoteId)
      break
    case 'notebook':
      void createNoteAt('notebook', folderId, parentNoteId)
      break
    case 'sheet':
      void createNoteAt('sheet', folderId, parentNoteId)
      break
    case 'import':
      openImport(folderId, parentNoteId)
      break
    case 'link':
      openLink(folderId, parentNoteId)
      break
    case 'template':
      openTemplates(folderId, parentNoteId)
      break
    case 'folder':
      // 分组只能存在于工作区分组层级，笔记内层不提供子分组。
      if (!parentNoteId) void openFolderDialog(folderId)
      break
  }
}

function onSelect(row: TreeRow, event?: MouseEvent) {
  if (Date.now() < suppressClickUntil) return
  if (!row.note) return
  const shift = !!event?.shiftKey
  const toggle = !!(event?.ctrlKey || event?.metaKey)

  if (shift && anchorId) {
    const range = noteRange(anchorId, row.id)
    const next = new Set(toggle ? [...selectedIds.value, ...range] : range)
    selectedIds.value = next
    return
  }
  if (toggle) {
    const next = new Set(selectedIds.value)
    if (next.has(row.id)) next.delete(row.id)
    else next.add(row.id)
    selectedIds.value = next
    anchorId = row.id
    return
  }
  selectedIds.value = new Set([row.id])
  anchorId = row.id
  emit('open-note', row.id)
  // 从置顶副本打开时，滚动并高亮其在原目录中的位置。
  revealActiveNote(row.id, true)
}

const createFolderMenu = () => openFolderDialog(null)
</script>

<template>
  <aside
    class="relative z-20 shrink-0 h-full flex flex-col sidebar-glass"
    :class="[collapsed ? 'w-14' : '', resizing ? '' : 'transition-[width] duration-300 ease-out']"
    :style="collapsed ? undefined : { width: `${treeWidth}px` }"
  >
    <div
      v-if="!collapsed"
      class="group/resize absolute inset-y-0 -right-1 z-30 w-2 cursor-col-resize touch-none"
      title="拖动调整目录宽度，双击恢复默认"
      @mousedown="startResize"
      @dblclick.prevent="resetTreeWidth"
    >
      <span
        class="pointer-events-none absolute inset-y-0 left-[2px] w-px transition-colors"
        :class="resizing ? 'bg-kiwi-400' : 'bg-transparent group-hover/resize:bg-kiwi-300'"
      />
    </div>
    <!-- 收起态：图标轨道 -->
    <template v-if="collapsed">
      <div class="flex flex-1 flex-col items-center gap-1 pt-3">
        <button
          type="button"
          class="w-8 h-8 grid place-items-center rounded-lg text-slate-400 transition-colors hover:bg-kiwi-50 hover:text-kiwi-700"
          title="展开目录"
          @click="collapsed = false"
        >
          <KiwiIcon name="panelLeftOpen" :size="16" />
        </button>
        <div class="my-1 h-px w-6 bg-slate-200/70" />
        <NoteCreateMenu
          @template="openTemplates()"
          @doc="createDoc()"
          @canvas="createCanvas()"
          @database="createDatabase()"
          @sheet="createSheet()"
          @notebook="createNotebook()"
          @import="openImport()"
          @folder="createFolderMenu"
          @link="openLink()"
        />
        <button
          type="button"
          class="w-8 h-8 grid place-items-center rounded-lg text-slate-400 transition-colors hover:bg-kiwi-50 hover:text-kiwi-700"
          title="搜索文档"
          @click="expandAndSearch"
        >
          <KiwiIcon name="search" :size="15" />
        </button>
      </div>
      <div class="pb-3 text-center text-[10px] tabular-nums text-slate-300">{{ total }}</div>
    </template>

    <!-- 展开态 -->
    <template v-else>
    <div class="h-12 shrink-0 flex items-center gap-2 px-3 border-b border-slate-200/50">
      <KiwiIcon name="note" :size="15" class="text-kiwi-500" />
      <span class="text-[13px] font-semibold text-slate-700">工作区</span>
      <span class="text-[10px] text-slate-400 tabular-nums">{{ total }}</span>
      <div class="flex-1" />
      <NoteCreateMenu
        @template="openTemplates()"
        @doc="createDoc()"
        @canvas="createCanvas()"
        @database="createDatabase()"
        @sheet="createSheet()"
        @notebook="createNotebook()"
        @import="openImport()"
        @folder="createFolderMenu"
        @link="openLink()"
      />
      <button
        type="button"
        class="w-7 h-7 grid place-items-center rounded-lg text-slate-400 transition-colors hover:bg-kiwi-50 hover:text-kiwi-700"
        title="收起目录"
        @click="collapsed = true"
      >
        <KiwiIcon name="panelLeftClose" :size="14" />
      </button>
    </div>

    <!-- 全文搜索：放在工作区最上方，任何库视图下都可直接唤起 -->
    <div class="shrink-0 px-2.5 pt-2">
      <button
        type="button"
        class="w-full h-7 rounded-lg border border-kiwi-100 bg-kiwi-50/50 inline-flex items-center justify-center gap-1.5 text-[10.5px] text-kiwi-600 transition-colors hover:border-kiwi-200 hover:bg-kiwi-50"
        @click="emit('open-search')"
      >
        <KiwiIcon name="sparkle" :size="11" class="text-kiwi-400" />
        全文搜索全部笔记
        <kbd class="rounded border border-kiwi-200/70 bg-white/80 px-1 text-[9px] text-kiwi-400">Ctrl K</kbd>
      </button>
    </div>

    <!-- 库视图切换 -->
    <div class="shrink-0 flex items-center gap-0.5 px-2 pt-1.5">
      <button
        v-for="tab in MODE_TABS"
        :key="tab.key"
        type="button"
        class="flex-1 h-7 rounded-md text-[10.5px] inline-flex items-center justify-center gap-1 transition-colors"
        :class="
          mode === tab.key
            ? 'bg-white/80 text-kiwi-700 shadow-sm border border-slate-200/60'
            : 'text-slate-400 hover:text-slate-600 hover:bg-white/50'
        "
        @click="mode = tab.key"
      >
        <KiwiIcon :name="tab.icon" :size="11" />
        {{ tab.label }}
      </button>
    </div>

    <template v-if="mode === 'tree'">
    <div class="px-2.5 py-2 shrink-0">
      <div class="relative">
        <span class="absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-300">
          <KiwiIcon name="search" :size="13" />
        </span>
        <input
          ref="searchInput"
          v-model="search"
          name="note-tree-search"
          autocomplete="off"
          spellcheck="false"
          class="w-full h-8 pl-8 pr-7 rounded-lg border border-slate-200/80 bg-white/70 text-[12px] text-slate-600 placeholder:text-slate-400 outline-none transition-all focus:border-kiwi-300 focus:ring-2 focus:ring-kiwi-200/70"
          placeholder="搜索文档…"
        />
        <button
          v-if="search"
          class="absolute right-1.5 top-1/2 -translate-y-1/2 w-5 h-5 grid place-items-center rounded text-slate-400 hover:text-slate-600"
          @click="search = ''"
        >
          <KiwiIcon name="close" :size="11" />
        </button>
      </div>
    </div>

    <div
      ref="treeScrollEl"
      class="flex-1 min-h-0 overflow-y-auto px-1.5 pb-2"
      @dragstart.prevent
    >
      <template
        v-for="row in rows"
        :key="`${row.type}:${row.id}:${row.hoisted ? 'pin' : 'origin'}`"
      >
        <div
          v-if="row.separatorBefore"
          class="mx-2 my-1.5 h-px bg-slate-200/90"
          role="separator"
        />
        <NotesTreeNode
          :row="row"
          :active-id="activeId"
          :open="expanded.has(row.id)"
          :renaming="renamingId === row.id && !row.hoisted"
          :dragging="dragRow?.id === row.id && !row.hoisted"
          :selected="row.type === 'note' && !row.hoisted && selectedIds.has(row.id)"
          :drop-target="dropState?.id === row.id ? dropState.pos : null"
          @select="onSelect"
          @toggle="toggle"
          @menu="openMenu"
          @pointerdown="onRowPointerDown"
          @rename="onRename"
          @rename-cancel="renamingId = null"
          @unpin="unpinFromRow(row)"
        />
      </template>

      <div v-if="!rows.length && !notes.treeLoading" class="px-3 pt-8">
        <KiwiEmpty
          v-if="search"
          icon="search"
          title="没有匹配的文档"
          desc="试试其他关键词"
        />
        <KiwiEmpty
          v-else
          icon="note"
          title="工作区还是空的"
          desc="新建文档、导入文件，或把网页收藏为链接"
        >
          <button class="kiwi-btn-primary !py-1.5 !px-3 text-xs" @click="createDoc()">
            <KiwiIcon name="plus" :size="13" /> 新建文档
          </button>
        </KiwiEmpty>
      </div>

      <!-- 拖拽时固定在底部的根目录投放区，长列表也不用滚到底 -->
      <div v-if="dragActive" class="sticky bottom-0 z-10 -mx-1 px-1 pb-1">
        <div
          data-tree-root-drop
          class="h-10 rounded-lg border border-dashed transition-colors grid place-items-center text-[10px]"
          :class="rootOver ? 'border-kiwi-400 bg-kiwi-50/95 text-kiwi-500' : 'border-kiwi-200 bg-white/90 text-kiwi-400'"
        >
          松开移到根目录
        </div>
      </div>
    </div>

    <div class="shrink-0 border-t border-slate-200/50">
      <RouterLink
        to="/sources"
        class="flex items-center gap-1.5 px-3 py-1.5 text-[10.5px] text-slate-500 transition-colors hover:bg-white/60 hover:text-kiwi-700"
        title="笔记与导入素材统一编译进 Wiki，追踪解析质量与任务进度"
      >
        <KiwiIcon name="bookOpen" :size="12" class="shrink-0 text-kiwi-400" />
        编译任务
        <KiwiIcon name="arrowRight" :size="10" class="ml-auto text-slate-300" />
      </RouterLink>
      <div class="flex items-center gap-1.5 px-3 pb-2 pt-0.5 text-[10px] text-slate-400">
        <KiwiIcon name="sparkle" :size="11" class="text-kiwi-300" />
        拖拽移动 · Shift 连选 · Ctrl 多选
      </div>
    </div>
    </template>

    <!-- 标签库：多选筛选 + 嵌套层级 + 常用/最近/名称排序 -->
    <div v-else-if="mode === 'tags'" class="flex-1 min-h-0 overflow-y-auto px-2 pb-2 pt-2">
      <div v-if="modeLoading" class="py-10 text-center text-[11px] text-slate-400">
        <KiwiIcon name="loader" :size="16" spin class="mx-auto mb-1.5" />
        加载标签…
      </div>
      <template v-else>
        <div class="px-1 pb-1.5 flex items-center gap-1.5">
          <span class="text-[10.5px] text-slate-400">按标签筛选</span>
          <span class="text-[9.5px] text-slate-300 tabular-nums">{{ tagRows.length }} 个</span>
          <select
            v-model="tagSort"
            class="ml-auto h-[22px] rounded-md border border-slate-200/70 bg-white/70 px-1 text-[10px] text-slate-500 outline-none"
            title="标签排序"
          >
            <option value="usage">常用优先</option>
            <option value="recent">最近使用</option>
            <option value="name">按名称</option>
          </select>
        </div>

        <button
          v-for="tag in tagRows"
          :key="tag.id"
          type="button"
          class="w-full flex items-center gap-1.5 rounded-lg py-1.5 pr-2 text-left transition-colors hover:bg-white/70"
          :class="selectedTagIds.includes(tag.id) ? 'bg-kiwi-50/80' : ''"
          :style="{ paddingLeft: `${8 + tag.depth * 14}px` }"
          @click="toggleTag(tag.id)"
        >
          <span
            class="grid h-3.5 w-3.5 shrink-0 place-items-center rounded border text-[8px]"
            :class="
              selectedTagIds.includes(tag.id)
                ? 'border-kiwi-400 bg-kiwi-500 text-white'
                : 'border-slate-300 text-transparent'
            "
          >
            ✓
          </span>
          <span class="flex-1 min-w-0 text-[12px] text-slate-600 truncate">{{ tag.name }}</span>
          <span
            class="text-[10px] tabular-nums"
            :class="tag.usage_count ? 'text-slate-400' : 'text-slate-300'"
          >
            {{ tag.usage_count }}
          </span>
        </button>
        <p
          v-if="!tagRows.length"
          class="px-2 pt-8 text-center text-[11px] leading-relaxed text-slate-400"
        >
          还没有标签。<br />
          在笔记页头点击「添加标签」，或右键笔记选择「设置标签」。
        </p>

        <template v-if="selectedTags.length">
          <div class="mt-2 border-t border-slate-200/60 pt-2">
            <div class="px-1.5 pb-1.5 flex items-center gap-1 flex-wrap">
              <span
                v-for="tag in selectedTags"
                :key="tag.id"
                class="inline-flex items-center gap-0.5 rounded-md border border-kiwi-100 bg-kiwi-50 px-1.5 py-0.5 text-[10.5px] text-kiwi-700"
              >
                {{ tag.name }}
                <button
                  type="button"
                  class="ml-0.5 text-kiwi-400 hover:text-kiwi-700"
                  @click.stop="toggleTag(tag.id)"
                >
                  ×
                </button>
              </span>
              <button
                type="button"
                class="ml-auto text-[10px] text-slate-400 hover:text-slate-600"
                @click="clearTags"
              >
                清除
              </button>
            </div>
            <div class="px-1.5 pb-1.5 text-[10px] text-slate-300">
              {{ tagNotes.length }} 篇同时包含以上标签
            </div>
            <button
              v-for="note in tagNotes"
              :key="note.id"
              type="button"
              class="w-full flex items-center gap-2 rounded-lg px-2 py-1.5 text-left transition-colors hover:bg-white/70"
              :class="activeId === note.id ? 'bg-white/80 shadow-sm' : ''"
              @click="emit('open-note', note.id)"
            >
              <span v-if="note.props_json?.emoji" class="text-[12px]">{{
                note.props_json.emoji
              }}</span>
              <KiwiIcon
                v-else
                :name="kindIcon(note.kind)"
                :size="12"
                class="text-slate-300 shrink-0"
              />
              <span class="flex-1 text-[12px] text-slate-600 truncate">{{
                note.title || '无标题'
              }}</span>
              <span class="text-[9.5px] text-slate-300">{{
                formatDate(note.updated_at)
              }}</span>
            </button>
            <p
              v-if="!tagNotes.length"
              class="px-2 pt-6 text-center text-[11px] text-slate-400"
            >
              没有同时包含以上标签的活跃笔记
            </p>
          </div>
        </template>
      </template>
    </div>

    <!-- 归档 -->
    <div v-else-if="mode === 'archived'" class="flex-1 min-h-0 overflow-y-auto px-2 pb-2 pt-2">
      <div class="px-1 pb-1.5 flex items-center justify-between">
        <span class="text-[10.5px] text-slate-400">已归档笔记仍参与搜索与反向链接</span>
        <span class="text-[9.5px] text-slate-300 tabular-nums">{{ notes.archived.length }}</span>
      </div>
      <div v-if="modeLoading" class="py-10 text-center text-[11px] text-slate-400">
        <KiwiIcon name="loader" :size="16" spin class="mx-auto mb-1.5" />
        加载归档…
      </div>
      <template v-else>
        <div
          v-for="note in notes.archived"
          :key="note.id"
          class="group flex items-center gap-2 rounded-lg px-2 py-1.5 hover:bg-white/70"
        >
          <button
            type="button"
            class="flex-1 min-w-0 flex items-center gap-2 text-left"
            @click="emit('open-note', note.id)"
          >
            <span v-if="note.props_json?.emoji" class="text-[12px]">{{ note.props_json.emoji }}</span>
            <KiwiIcon v-else :name="kindIcon(note.kind)" :size="12" class="text-slate-300 shrink-0" />
            <span class="flex-1 text-[12px] text-slate-600 truncate">{{ note.title || '无标题' }}</span>
            <span class="text-[9.5px] text-slate-300">{{ formatDate(note.updated_at) }}</span>
          </button>
          <button
            class="shrink-0 rounded px-1.5 py-0.5 text-[9.5px] text-kiwi-600 opacity-0 group-hover:opacity-100 hover:bg-kiwi-50"
            @click.stop="restoreArchived(note.id)"
          >
            恢复
          </button>
        </div>
        <p v-if="!notes.archived.length" class="px-2 pt-8 text-center text-[11px] text-slate-400">
          没有已归档的笔记
        </p>
      </template>
    </div>

    <!-- 回收站 -->
    <div v-else class="flex-1 min-h-0 overflow-y-auto px-2 pb-2 pt-2">
      <div class="px-1 pb-1.5 flex items-center justify-between">
        <span class="text-[10.5px] text-slate-400">
          保留 {{ notes.trash?.retention_days ?? 30 }} 天 · 到期自动清理
        </span>
        <button
          v-if="notes.trash?.items.length"
          class="text-[9.5px] text-rose-400 hover:text-rose-600"
          @click="emptyTrashOpen = true"
        >
          清空
        </button>
      </div>
      <div v-if="modeLoading" class="py-10 text-center text-[11px] text-slate-400">
        <KiwiIcon name="loader" :size="16" spin class="mx-auto mb-1.5" />
        加载回收站…
      </div>
      <template v-else>
        <div
          v-for="note in notes.trash?.items || []"
          :key="note.id"
          class="group rounded-lg px-2 py-1.5 hover:bg-white/70"
        >
          <div class="flex items-center gap-2">
            <span v-if="note.props_json?.emoji" class="text-[12px]">{{ note.props_json.emoji }}</span>
            <KiwiIcon v-else :name="kindIcon(note.kind)" :size="12" class="text-slate-300 shrink-0" />
            <span class="flex-1 text-[12px] text-slate-500 truncate">{{ note.title || '无标题' }}</span>
            <span class="text-[9px] tabular-nums text-slate-300">
              剩 {{ trashDaysLeft(note.updated_at) }} 天
            </span>
          </div>
          <div class="mt-1 flex items-center gap-1 pl-6 opacity-0 transition-opacity group-hover:opacity-100">
            <button
              class="rounded px-1.5 py-0.5 text-[9.5px] text-kiwi-600 hover:bg-kiwi-50"
              @click="restoreFromTrash(note.id)"
            >
              恢复
            </button>
            <button
              class="rounded px-1.5 py-0.5 text-[9.5px] text-rose-400 hover:bg-rose-50 hover:text-rose-600"
              @click="purgeTarget = note"
            >
              永久删除
            </button>
          </div>
        </div>
        <p v-if="!(notes.trash?.items || []).length" class="px-2 pt-8 text-center text-[11px] leading-relaxed text-slate-400">
          回收站是空的。<br />
          删除的笔记会在这里保留 30 天，可随时恢复。
        </p>
      </template>
    </div>

    <NoteContextMenu
      :open="menu.open"
      :x="menu.x"
      :y="menu.y"
      :row="menu.row"
      :selection-count="menuSelectionCount"
      :export-actions="menuExportActions"
      @close="menu.open = false"
      @rename="beginRenameFromMenu"
      @pin="togglePinFromMenu"
      @copy="copyFromMenu"
      @move-kb="openMoveFromMenu"
      @emoji="openEmojiFromMenu"
      @tags="openTagsFromMenu"
      @lock="openLockFromMenu"
      @archive="archiveFromMenu"
      @export="exportFromMenu"
      @delete="deleteFromMenu"
      @create="createFromMenu"
    />

    <NoteEmojiPicker
      :open="emojiPicker.open"
      :x="emojiPicker.x"
      :y="emojiPicker.y"
      :current="emojiPicker.row?.note?.props_json?.emoji ?? ''"
      @select="onPickEmoji"
      @close="emojiPicker.open = false"
    />

    <KiwiModal
      :open="tagEditor.open"
      title="设置标签"
      max-w="max-w-sm"
      @close="tagEditor.open = false"
    >
      <div v-if="tagEditor.row" class="space-y-3">
        <p class="truncate text-xs text-slate-500">
          {{ tagEditor.row.note?.title || '无标题' }}
        </p>
        <NoteTagEditor
          :note-id="tagEditor.row.id"
          :tags="tagEditor.tags"
          @updated="tagEditor.tags = $event"
        />
        <div class="flex justify-end pt-1">
          <button class="kiwi-btn-primary" @click="tagEditor.open = false">完成</button>
        </div>
      </div>
    </KiwiModal>

    <NoteLockDialog
      :open="!!locking"
      :note="locking?.note ?? null"
      @close="locking = null"
      @changed="onLockChanged"
    />

    <NoteMoveKbDialog
      :open="moveOpen"
      :current-kb-id="kbs.currentKbId"
      :note-title="moving?.note?.title ?? ''"
      @close="moving = null"
      @move="confirmMove"
    />

    <KiwiConfirm
      v-model="deleteOpen"
      danger
      :title="deleting?.type === 'folder' ? '删除分组' : '删除条目'"
      :message="
        deleting?.type === 'folder'
          ? '子分组会一并删除，其中的文档会移动到上一级分组。'
          : '条目会移入回收站，可在 30 天内恢复；导入与链接来源记录会保留。'
      "
      confirm-text="删除"
      @confirm="confirmDelete"
    />

    <KiwiConfirm
      v-model="batchOpen"
      danger
      title="批量删除"
      :message="`将选中的 ${batchIds.length} 个条目移入回收站，可在 30 天内恢复；导入与链接来源记录会保留。`"
      :confirm-text="batchDeleting ? '删除中…' : '删除'"
      @confirm="confirmBatchDelete"
    />

    <KiwiConfirm
      v-model="purgeOpen"
      danger
      title="永久删除"
      :message="`「${purgeTarget?.title || '无标题'}」将被永久删除，无法恢复。`"
      confirm-text="永久删除"
      @confirm="confirmPurge"
    />

    <KiwiConfirm
      v-model="emptyTrashOpen"
      danger
      title="清空回收站"
      :message="`回收站中的 ${notes.trash?.items.length || 0} 个条目将被永久删除，无法恢复。`"
      confirm-text="清空"
      @confirm="confirmEmptyTrash"
    />
    </template>

    <KiwiModal
      :open="folderDialog.open"
      title="新建分组"
      max-w="max-w-sm"
      @close="folderDialog.open = false"
    >
      <input
        ref="folderInput"
        v-model="folderDialog.name"
        class="kiwi-input"
        placeholder="分组名称"
        @keyup.enter="confirmFolder"
      />
      <div class="flex justify-end gap-2 mt-4">
        <button class="kiwi-btn-secondary" @click="folderDialog.open = false">取消</button>
        <button class="kiwi-btn-primary" :disabled="!folderDialog.name.trim()" @click="confirmFolder">
          创建
        </button>
      </div>
    </KiwiModal>

    <NoteImportDialog
      :open="importOpen"
      :folder-id="importFolderId"
      :parent-note-id="importParentNoteId"
      @close="importOpen = false"
      @created="onCreated"
    />
    <LinkCreateDialog
      :open="linkOpen"
      :folder-id="linkFolderId"
      :parent-note-id="linkParentNoteId"
      @close="linkOpen = false"
      @created="onCreated"
    />
    <NoteTemplatePicker
      :open="templateOpen"
      :folder-id="templateFolderId"
      :parent-note-id="templateParentNoteId"
      @close="templateOpen = false"
      @created="onTemplateCreated"
    />
    <QuickCaptureDialog
      :open="captureOpen"
      @close="captureOpen = false"
      @created="onCaptured"
    />

    <!-- 指针拖拽时跟随光标的浮动标签：按抓取点锚定，与原生拖拽手感一致。
         外层挂到 <html> 下用视口坐标（不受 body zoom 影响），内层按 --ui-scale 放大。 -->
    <Teleport to="html">
      <div
        v-if="dragActive && dragGhost"
        class="pointer-events-none fixed z-[300]"
        :style="{ left: `${ghostPos.x}px`, top: `${ghostPos.y}px` }"
      >
        <div
          ref="ghostEl"
          class="flex h-8 max-w-[260px] items-center gap-1.5 rounded-lg border border-kiwi-300/80 bg-white/95 px-2.5 text-[12.5px] text-slate-700 shadow-lifted backdrop-blur"
          :style="{ zoom: 'var(--ui-scale)' }"
        >
          <KiwiIcon :name="dragGhost.icon" :size="14" :class="dragGhost.tone" />
          <span class="truncate">{{ dragGhost.label }}</span>
        </div>
      </div>
    </Teleport>
  </aside>
</template>

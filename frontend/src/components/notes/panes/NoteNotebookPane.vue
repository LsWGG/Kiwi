<script setup lang="ts">
/**
 * Notebook 笔记：Jupyter 风格单元格 + 持久 Python 内核。
 * 文档保存在 props_json.notebook_doc；代码在 bubblewrap 沙箱中执行。
 *
 * - 编辑 / 分屏 / 阅读三种模式；
 * - CodeMirror 编辑器、Jupyter 快捷键（Shift+Enter / Ctrl+Enter / A / B / M / Y / DD）；
 * - 沙箱开启网络，可使用 !命令、%pip、%uv 安装依赖；
 * - 可写虚拟环境 /work/.venv 继承项目依赖（pandas、numpy、matplotlib 等）。
 */
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useNotesStore, type NoteOut } from '@/stores/notes'
import { useDesktopStore } from '@/stores/desktop'
import { IS_DESKTOP } from '@/desktop/env'
import { useAutosave } from '@/composables/useAutosave'
import { useSaveShortcut } from '@/composables/useSaveShortcut'
import { useSyncedScroll } from '@/composables/useSyncedScroll'
import NoteTitleBreadcrumb from '@/components/notes/NoteTitleBreadcrumb.vue'
import NoteTagButton from '@/components/notes/NoteTagButton.vue'
import KiwiIcon from '@/components/ui/KiwiIcon.vue'
import KiwiConfirm from '@/components/ui/KiwiConfirm.vue'
import KiwiModal from '@/components/ui/KiwiModal.vue'
import { toast } from '@/components/ui/toast'
import NotebookCell from '@/components/notes/notebook/NotebookCell.vue'
import NotebookPreview from '@/components/notes/notebook/NotebookPreview.vue'
import NoteReadingTools from '@/components/notes/reading/NoteReadingTools.vue'
import {
  executeCell,
  kernelStatus,
  restartKernel,
  type KernelStatus,
} from '@/components/notes/notebook/api'
import {
  countCodeCells,
  emptyNotebook,
  newCell,
  normalizeNotebook,
  type NotebookCell as Cell,
  type NotebookCellType,
  type NotebookDoc,
} from '@/components/notes/notebook/types'

const props = defineProps<{ note: NoteOut }>()
const notes = useNotesStore()
const desktop = useDesktopStore()

type ViewMode = 'edit' | 'split' | 'read'

const VIEW_MODES: { key: ViewMode; label: string; icon: string; hint: string }[] = [
  { key: 'edit', label: '编辑', icon: 'edit', hint: '逐个编辑并运行单元格' },
  { key: 'split', label: '分屏', icon: 'columns', hint: '左侧源码，右侧实时预览与输出' },
  { key: 'read', label: '阅读', icon: 'bookOpen', hint: '只读渲染整个 Notebook' },
]

function normalizeViewMode(value: unknown): ViewMode {
  return value === 'split' || value === 'read' ? value : 'edit'
}

const title = ref(props.note.title)
const doc = ref<NotebookDoc>(normalizeNotebook(props.note.props_json?.notebook_doc))
const viewMode = ref<ViewMode>(
  normalizeViewMode(props.note.props_json?.notebook_view_mode),
)
const cellsEl = ref<HTMLElement | null>(null)
const previewScrollEl = ref<HTMLElement | null>(null)
const selectedCellId = ref<string | null>(null)
const editingCellId = ref<string | null>(null)
const cellRefs = new Map<string, InstanceType<typeof NotebookCell>>()

const kernel = ref<KernelStatus | null>(null)
const kernelError = ref('')
const runningCellId = ref<string | null>(null)
const runningAll = ref(false)
const runAllTotal = ref(0)
const runAllDone = ref(0)
const timeoutSeconds = ref(60)
const restartOpen = ref(false)
const shortcutsOpen = ref(false)
const clearing = ref(false)
let lastDAt = 0

const autosave = useAutosave(async () => {
  await notes.updateNote(props.note.id, {
    title: title.value.trim() || '无标题 Notebook',
    props_json: {
      notebook_doc: doc.value,
      notebook_view_mode: viewMode.value,
    },
  })
})

useSaveShortcut(() => autosave.flushNow())

const codeCount = computed(() => countCodeCells(doc.value))
const busy = computed(() => runningCellId.value !== null || runningAll.value)
const readMode = computed(() => viewMode.value === 'read')
const splitMode = computed(() => viewMode.value === 'split')

// 阅读演示层：激光点、演示笔、缩放与全屏，与其他笔记类型保持一致
const readAreaEl = ref<HTMLElement | null>(null)
const readScrollEl = ref<HTMLElement | null>(null)
const readZoom = ref(1)
const readZen = ref(false)

watch(readMode, (on) => {
  if (on) return
  readZoom.value = 1
  readZen.value = false
})

useSyncedScroll(cellsEl, previewScrollEl, splitMode)
const desktopExecDisabled = computed(
  () => IS_DESKTOP && desktop.ready && !desktop.localCodeEnabled,
)
const sandboxAvailable = computed(() => kernel.value?.sandbox?.available !== false)
const sandboxNetwork = computed(() => kernel.value?.sandbox?.network === true)
const sandboxLabel = computed(() => {
  if (IS_DESKTOP) {
    if (desktopExecDisabled.value) return '本机执行已关闭'
    if (!desktop.localCodeAvailable) return '本机执行组件未就绪'
    return '本机执行（非隔离）'
  }
  if (kernel.value?.sandbox?.available === false) return '安全沙箱不可用'
  return sandboxNetwork.value ? '沙箱执行 · 网络已开启' : '沙箱执行 · 无网络'
})
const sandboxHint = computed(() => {
  if (IS_DESKTOP) {
    if (desktopExecDisabled.value) {
      return '桌面版本机代码执行默认关闭，可在「设置 → 桌面」中开启。'
    }
    return [
      'Windows Job Object：限制内存与进程数，超时终止进程树',
      '不是文件系统沙箱：代码可以读取当前用户可访问的文件',
      '不提供 %pip / %uv / !shell 与网络访问',
      '请只运行你信任的代码',
    ].join('；')
  }
  if (!sandboxAvailable.value) return kernelError.value || '安全沙箱不可用'
  return [
    'bubblewrap：独立 PID / 挂载命名空间，仅 /work 与 /tmp 可写',
    '项目目录、数据库与密钥在沙箱内不可见',
    sandboxNetwork.value ? '已开启网络，支持 pip / uv 安装依赖' : '当前无网络',
    '/work/.venv 可写并继承项目依赖',
  ].join('；')
})
const kernelLabel = computed(() => {
  if (kernelError.value) return '内核不可用'
  if (!kernel.value) return '内核未启动'
  if (!kernel.value.running) return '内核未启动'
  return `Python ${kernel.value.python_version || ''} · 第 ${kernel.value.execution_count} 次执行`
})
const runAllLabel = computed(() => {
  if (!runningAll.value) return '运行全部'
  return runAllTotal.value ? `运行中 ${runAllDone.value}/${runAllTotal.value}` : '运行中…'
})

function onTitleInput() {
  autosave.schedule()
}

watch(
  () => props.note.title,
  (value) => {
    if (value !== title.value && !autosave.saving.value) title.value = value
  },
)

watch(viewMode, () => autosave.schedule())

async function refreshKernel() {
  try {
    kernel.value = await kernelStatus(props.note.kb_id, props.note.id)
    kernelError.value = kernel.value.sandbox?.available === false ? '安全沙箱不可用' : ''
  } catch (e: any) {
    kernelError.value = e?.message || '无法读取内核状态'
  }
}

onMounted(() => {
  void refreshKernel()
  window.addEventListener('keydown', onWindowKeydown)
})
onBeforeUnmount(() => window.removeEventListener('keydown', onWindowKeydown))

function setViewMode(mode: ViewMode) {
  if (viewMode.value === mode) return
  viewMode.value = mode
  editingCellId.value = null
  if (mode === 'read') selectedCellId.value = null
}

// ---------- 单元格引用与选择 ----------
function setCellRef(id: string, instance: unknown) {
  if (instance) cellRefs.set(id, instance as InstanceType<typeof NotebookCell>)
  else cellRefs.delete(id)
}

function focusCell(cellId: string) {
  selectedCellId.value = cellId
  editingCellId.value = cellId
  void nextTick(() => cellRefs.get(cellId)?.focusEditor())
}

function selectCell(cell: Cell) {
  selectedCellId.value = cell.id
  editingCellId.value = null
  scrollCellIntoView(cell.id)
}

function onCellFocus(cell: Cell) {
  selectedCellId.value = cell.id
  editingCellId.value = cell.id
}

function onCellEscape(cell: Cell) {
  editingCellId.value = null
  selectedCellId.value = cell.id
}

function scrollCellIntoView(cellId: string) {
  void nextTick(() => {
    const el = cellsEl.value?.querySelector<HTMLElement>(
      `[data-cell-id="${cellId}"]`,
    )
    el?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
  })
}

function isTypingTarget(target: EventTarget | null): boolean {
  const el = target as HTMLElement | null
  if (!el?.closest) return false
  return Boolean(
    el.closest(
      'input, textarea, select, [contenteditable="true"], .cm-editor, button, a, [role="button"]',
    ),
  )
}

function onWindowKeydown(event: KeyboardEvent) {
  if (readMode.value) return
  if (!selectedCellId.value || editingCellId.value) return
  if (isTypingTarget(event.target)) return
  const cells = doc.value.cells
  const index = cells.findIndex((cell) => cell.id === selectedCellId.value)
  if (index < 0) return
  const cell = cells[index]
  const key = event.key
  const lower = key.toLowerCase()
  const mod = event.metaKey || event.ctrlKey

  if (key === 'ArrowDown') {
    event.preventDefault()
    if (index < cells.length - 1) {
      selectedCellId.value = cells[index + 1].id
      scrollCellIntoView(cells[index + 1].id)
    }
    return
  }
  if (key === 'ArrowUp') {
    event.preventDefault()
    if (index > 0) {
      selectedCellId.value = cells[index - 1].id
      scrollCellIntoView(cells[index - 1].id)
    }
    return
  }
  if (key === 'Enter') {
    event.preventDefault()
    if (event.shiftKey) void runCell(cell, 'next')
    else if (mod) void runCell(cell, 'stay')
    else focusCell(cell.id)
    return
  }
  if (key === 'Escape') {
    // 已在命令模式：保留当前选中格，仅清除 DD 的半完成状态。
    lastDAt = 0
    return
  }
  if (mod || event.altKey) return
  if (lower === 'a') {
    event.preventDefault()
    insertCell('code', index, true)
    return
  }
  if (lower === 'b') {
    event.preventDefault()
    insertCell('code', index + 1, true)
    return
  }
  if (lower === 'm') {
    event.preventDefault()
    changeType(cell, 'markdown')
    return
  }
  if (lower === 'y') {
    event.preventDefault()
    changeType(cell, 'code')
    return
  }
  if (lower === 'd') {
    event.preventDefault()
    const now = Date.now()
    if (now - lastDAt < 900) {
      lastDAt = 0
      removeCell(index)
    } else {
      lastDAt = now
      toast.info('再按一次 D 删除当前单元格')
    }
  }
}

function insertCell(
  type: NotebookCellType,
  index = doc.value.cells.length,
  focus = true,
) {
  if (readMode.value) return
  const cell = newCell(type)
  doc.value.cells.splice(Math.max(0, Math.min(index, doc.value.cells.length)), 0, cell)
  autosave.schedule()
  selectedCellId.value = cell.id
  if (focus) focusCell(cell.id)
  scrollCellIntoView(cell.id)
  return cell
}

function onInsertBelow(index: number) {
  return insertCell('code', index + 1)
}

function onInsertAbove(index: number) {
  return insertCell('code', index)
}

function updateSource(cell: Cell, value: string) {
  cell.source = value
  autosave.schedule()
}

function removeCell(index: number) {
  const cell = doc.value.cells[index]
  if (!cell) return
  if (runningCellId.value === cell.id) {
    toast.error('单元格正在执行，请等待结束')
    return
  }
  doc.value.cells.splice(index, 1)
  if (!doc.value.cells.length) doc.value.cells.push(...emptyNotebook().cells)
  const next = doc.value.cells[Math.min(index, doc.value.cells.length - 1)]
  selectedCellId.value = next?.id ?? null
  editingCellId.value = null
  autosave.schedule()
}

function moveCell(index: number, delta: number) {
  const target = index + delta
  const cells = doc.value.cells
  if (target < 0 || target >= cells.length) return
  const [cell] = cells.splice(index, 1)
  cells.splice(target, 0, cell)
  selectedCellId.value = cell.id
  autosave.schedule()
  scrollCellIntoView(cell.id)
}

function changeType(cell: Cell, type: NotebookCellType, focus = false) {
  if (cell.type === type) return
  if (runningCellId.value === cell.id) {
    toast.error('单元格正在执行，请等待结束')
    return
  }
  cell.type = type
  cell.execution_count = null
  cell.outputs = []
  autosave.schedule()
  if (focus) focusCell(cell.id)
}

function resetExecutionCounts() {
  for (const cell of doc.value.cells) {
    if (cell.type === 'code') cell.execution_count = null
  }
}

function applyResult(cell: Cell, result: Awaited<ReturnType<typeof executeCell>>) {
  const outputs = result.outputs.length
    ? result.outputs
    : result.error
      ? [{ type: 'error' as const, text: result.error }]
      : []
  cell.outputs = outputs
  if (result.execution_count) cell.execution_count = result.execution_count
  if (result.kernel_restarted) {
    resetExecutionCounts()
    if (cell.execution_count) cell.execution_count = null
    toast.error('Python 内核已重启，之前的变量状态已丢失')
  }
  if (result.busy) {
    toast.error(result.error || '内核正在执行其他单元格，请稍候')
  } else if (result.timed_out) {
    toast.error(`运行超过 ${timeoutSeconds.value} 秒，已中断`)
  } else if (!result.ok && !result.error) {
    toast.error('代码执行失败，请查看单元格输出')
  }
}

/** 返回值用于区分「执行完成」「空单元格」「内核忙」「沙箱不可用」。 */
async function executeOne(cell: Cell): Promise<'done' | 'empty' | 'busy' | 'blocked'> {
  if (cell.type !== 'code' || !cell.source.trim()) return 'empty'
  if (runningCellId.value) return 'busy'
  if (desktopExecDisabled.value) {
    toast.error('桌面版本机代码执行默认关闭，请在「设置 → 桌面」中开启')
    return 'blocked'
  }
  if (!IS_DESKTOP && !sandboxAvailable.value) {
    toast.error(kernelError.value || '安全沙箱不可用，已拒绝执行')
    return 'blocked'
  }
  runningCellId.value = cell.id
  selectedCellId.value = cell.id
  try {
    const result = await executeCell(
      props.note.kb_id,
      props.note.id,
      cell.id,
      cell.source,
      timeoutSeconds.value,
    )
    applyResult(cell, result)
    autosave.schedule()
  } catch (e: any) {
    cell.outputs = [{ type: 'error', text: e?.message || '执行失败' }]
    toast.error(e?.message || '执行失败')
    autosave.schedule()
  } finally {
    runningCellId.value = null
    void refreshKernel()
  }
  return 'done'
}

/** advance：stay 停留；next 跳到下一格；insert 在下方插入新格。 */
async function runCell(cell: Cell, advance: 'stay' | 'next' | 'insert' = 'stay') {
  if (readMode.value) return
  if (!cell) return
  const index = doc.value.cells.findIndex((item) => item.id === cell.id)
  selectedCellId.value = cell.id
  if (cell.type === 'code') {
    const status = await executeOne(cell)
    if (status === 'busy') {
      toast.info('内核正在执行其他单元格，请稍候再运行')
      return
    }
    if (status === 'blocked') return
  }
  if (advance === 'insert') {
    insertCell('code', index + 1, true)
    return
  }
  if (advance === 'next') {
    const next = doc.value.cells[index + 1]
    if (next) {
      selectedCellId.value = next.id
      editingCellId.value = null
      scrollCellIntoView(next.id)
    } else {
      insertCell('code', doc.value.cells.length, true)
    }
    return
  }
  if (cell.type === 'code') {
    editingCellId.value = cell.id
    focusCell(cell.id)
  } else {
    editingCellId.value = null
  }
}

function clearCellOutput(cell: Cell) {
  if (runningCellId.value === cell.id) {
    toast.error('单元格正在执行，请等待结束')
    return
  }
  cell.outputs = []
  cell.execution_count = null
  autosave.schedule()
}

async function runAll() {
  if (busy.value || readMode.value) return
  if (desktopExecDisabled.value) {
    toast.error('桌面版本机代码执行默认关闭，请在「设置 → 桌面」中开启')
    return
  }
  const targets = doc.value.cells.filter(
    (cell) => cell.type === 'code' && cell.source.trim(),
  )
  if (!targets.length) {
    toast.info('没有可运行的代码单元格')
    return
  }
  runningAll.value = true
  runAllTotal.value = targets.length
  runAllDone.value = 0
  try {
    for (const cell of targets) {
      if (!sandboxAvailable.value) break
      selectedCellId.value = cell.id
      scrollCellIntoView(cell.id)
      await executeOne(cell)
      runAllDone.value += 1
    }
  } finally {
    runningAll.value = false
    runAllTotal.value = 0
    runAllDone.value = 0
  }
}

function clearOutputs() {
  if (busy.value) {
    toast.error('请等待当前单元格执行结束')
    return
  }
  clearing.value = true
  try {
    for (const cell of doc.value.cells) {
      if (cell.type === 'code') {
        cell.outputs = []
        cell.execution_count = null
      }
    }
    autosave.schedule()
    toast.success('已清除全部输出')
  } finally {
    clearing.value = false
  }
}

async function doRestart() {
  if (busy.value) {
    toast.error('请等待当前单元格执行结束')
    return
  }
  try {
    kernel.value = await restartKernel(props.note.kb_id, props.note.id)
    resetExecutionCounts()
    kernelError.value = ''
    toast.success('内核已重启，运行状态已清空')
  } catch (e: any) {
    kernelError.value = e?.message || '重启内核失败'
    toast.error(kernelError.value)
  }
}

const SHORTCUTS: { keys: string; label: string }[] = [
  { keys: 'Shift + Enter', label: '运行并跳到下一格（最后一格自动新建）' },
  { keys: 'Ctrl / Cmd + Enter', label: '运行并停留在当前格' },
  { keys: 'Alt + Enter', label: '运行并在下方插入新格' },
  { keys: 'Tab / Shift + Tab', label: '增加 / 减少缩进' },
  { keys: 'Ctrl / Cmd + /', label: '注释 / 取消注释选中行' },
  { keys: 'Esc', label: '离开编辑，进入命令模式' },
  { keys: 'Enter', label: '命令模式：编辑选中格' },
  { keys: '↑ / ↓', label: '命令模式：选择上一格 / 下一格' },
  { keys: 'A / B', label: '命令模式：在上方 / 下方插入代码格' },
  { keys: 'M / Y', label: '命令模式：切换为 Markdown / 代码' },
  { keys: 'D D', label: '命令模式：删除选中格' },
  { keys: 'Ctrl / Cmd + S', label: '立即保存' },
]
</script>

<template>
  <div class="h-full flex flex-col">
    <header class="shrink-0 h-11 flex items-center gap-2 px-4 border-b border-slate-200/50 bg-white/40">
      <NoteTitleBreadcrumb
        v-model:title="title"
        :note-id="note.id"
        :emoji="note.props_json?.emoji"
        kind="notebook"
        :folder-id="note.folder_id"
        placeholder="无标题 Notebook"
        :readonly="readMode"
        @input="onTitleInput"
      />
      <span
        class="shrink-0 rounded-md border border-indigo-100 bg-indigo-50 px-1.5 py-0.5 text-[10px] text-indigo-500"
      >
        Notebook
      </span>
      <div class="flex-1" />
      <span class="text-[10px] text-slate-400 tabular-nums">
        <template v-if="autosave.saving.value">
          <KiwiIcon name="loader" :size="10" spin class="inline -mt-px mr-1" />保存中…
        </template>
        <template v-else-if="autosave.savedAt.value">已保存 {{ autosave.savedAt.value }}</template>
        <template v-else>自动保存</template>
      </span>
      <NoteTagButton :note="note" />
    </header>

    <!-- 工具栏 -->
    <div
      class="shrink-0 flex flex-wrap items-center gap-1.5 border-b border-slate-200/50 bg-white/55 px-3 py-1.5"
    >
      <template v-if="!readMode">
        <button
          type="button"
          class="kiwi-btn-primary !px-2.5 !py-1 text-[11px]"
          :disabled="busy || !sandboxAvailable"
          title="依次运行所有代码单元格"
          @click="runAll"
        >
          <KiwiIcon :name="runningAll ? 'loader' : 'play'" :size="11" :spin="runningAll" />
          {{ runAllLabel }}
        </button>
        <button
          type="button"
          class="kiwi-btn-secondary !px-2.5 !py-1 text-[11px]"
          :disabled="busy"
          title="在末尾添加代码单元格"
          @click="insertCell('code')"
        >
          <KiwiIcon name="plus" :size="11" />
          代码
        </button>
        <button
          type="button"
          class="kiwi-btn-secondary !px-2.5 !py-1 text-[11px]"
          :disabled="busy"
          title="在末尾添加 Markdown 单元格"
          @click="insertCell('markdown')"
        >
          <KiwiIcon name="type" :size="11" />
          文本
        </button>

        <span class="mx-0.5 h-4 w-px bg-slate-200/80" />

        <button
          type="button"
          class="kiwi-btn-ghost !px-2 !py-1 text-[11px]"
          :disabled="busy"
          title="重启 Python 内核并清空变量"
          @click="restartOpen = true"
        >
          <KiwiIcon name="refresh" :size="11" />
          重启内核
        </button>
        <button
          type="button"
          class="kiwi-btn-ghost !px-2 !py-1 text-[11px]"
          :disabled="busy || clearing"
          title="清除所有输出与执行序号"
          @click="clearOutputs"
        >
          <KiwiIcon name="eraser" :size="11" />
          清除输出
        </button>
        <button
          type="button"
          class="kiwi-btn-ghost !px-2 !py-1 text-[11px]"
          title="查看 Jupyter 风格快捷键"
          @click="shortcutsOpen = true"
        >
          <KiwiIcon name="terminal" :size="11" />
          快捷键
        </button>

        <label class="ml-1 flex items-center gap-1 text-[10.5px] text-slate-400">
          超时
          <select
            v-model.number="timeoutSeconds"
            class="rounded-md border border-slate-200/80 bg-white/80 px-1 py-0.5 text-[10.5px] text-slate-600 outline-none focus:border-kiwi-300"
            :disabled="busy"
          >
            <option :value="15">15 秒</option>
            <option :value="30">30 秒</option>
            <option :value="60">60 秒</option>
            <option :value="120">120 秒</option>
            <option :value="300">300 秒</option>
          </select>
        </label>
      </template>
      <span
        v-else
        class="inline-flex items-center gap-1 rounded-md bg-slate-100/80 px-2 py-1 text-[10.5px] text-slate-500"
      >
        <KiwiIcon name="bookOpen" :size="11" />
        阅读模式 · 只读渲染
      </span>

      <div class="flex-1" />

      <div class="inline-flex rounded-lg border border-slate-200/80 bg-white/70 p-0.5">
        <button
          v-for="mode in VIEW_MODES"
          :key="mode.key"
          type="button"
          class="inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-[10.5px] transition-colors"
          :class="
            viewMode === mode.key
              ? 'bg-kiwi-50 font-medium text-kiwi-700 shadow-sm'
              : 'text-slate-400 hover:text-slate-600'
          "
          :title="mode.hint"
          @click="setViewMode(mode.key)"
        >
          <KiwiIcon :name="mode.icon" :size="10" />
          {{ mode.label }}
        </button>
      </div>

      <span
        class="hidden items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] md:inline-flex"
        :class="
          sandboxAvailable
            ? 'border-emerald-200/70 bg-emerald-50/70 text-emerald-600'
            : 'border-rose-200 bg-rose-50 text-rose-600'
        "
        :title="sandboxHint"
      >
        <KiwiIcon name="shield" :size="10" />
        {{ sandboxLabel }}
      </span>
      <span
        class="rounded-full border border-slate-200/80 bg-white/70 px-2 py-0.5 text-[10px] text-slate-500"
        :class="kernel?.running ? 'text-kiwi-600' : ''"
        :title="kernelError || `工作目录 ${kernel?.workdir || '/work'}`"
      >
        <span
          class="mr-1 inline-block h-1.5 w-1.5 rounded-full align-middle"
          :class="kernelError ? 'bg-rose-400' : kernel?.running ? 'bg-emerald-400' : 'bg-slate-300'"
        />
        {{ kernelLabel }}
      </span>
    </div>

    <!-- 编辑 / 分屏 / 阅读 -->
    <div class="min-h-0 flex flex-1">
      <div
        v-if="!readMode"
        ref="cellsEl"
        class="min-h-0 overflow-auto"
        :class="splitMode ? 'w-1/2 border-r border-slate-200/60' : 'flex-1'"
      >
        <div class="mx-auto w-full max-w-[940px] px-3 py-3 pb-20 sm:px-5">
          <div
            v-if="splitMode"
            class="mb-2 flex items-center gap-1.5 px-1 text-[10px] font-medium uppercase tracking-wide text-slate-400"
          >
            <KiwiIcon name="code" :size="11" />
            源码
          </div>
          <NotebookCell
            v-for="(cell, index) in doc.cells"
            :key="cell.id"
            :ref="(el) => setCellRef(cell.id, el)"
            :data-cell-id="cell.id"
            :cell="cell"
            :index="index"
            :total="doc.cells.length"
            :mode="splitMode ? 'source' : 'edit'"
            :selected="selectedCellId === cell.id"
            :running="runningCellId === cell.id"
            :disabled="
              (!!runningCellId && runningCellId !== cell.id) ||
              (runningAll && runningCellId !== cell.id)
            "
            @update:source="updateSource(cell, $event)"
            @run="runCell(cell, 'stay')"
            @run-next="runCell(cell, 'next')"
            @run-insert="runCell(cell, 'insert')"
            @select="selectCell(cell)"
            @focus="onCellFocus(cell)"
            @escape="onCellEscape(cell)"
            @remove="removeCell(index)"
            @move-up="moveCell(index, -1)"
            @move-down="moveCell(index, 1)"
            @insert-above="onInsertAbove(index)"
            @insert-below="onInsertBelow(index)"
            @change-type="changeType(cell, $event)"
            @clear-output="clearCellOutput(cell)"
            @copied="toast.success('已复制单元格源码')"
          />

          <div class="mt-3 flex items-center gap-2">
            <button
              type="button"
              class="flex flex-1 items-center justify-center gap-1.5 rounded-lg border border-dashed border-slate-200/90 bg-white/40 py-2 text-[11.5px] text-slate-400 transition-colors hover:border-kiwi-300 hover:bg-kiwi-50/40 hover:text-kiwi-600"
              :disabled="busy"
              @click="insertCell('code')"
            >
              <KiwiIcon name="plus" :size="12" />
              添加代码单元格
            </button>
            <button
              type="button"
              class="flex flex-1 items-center justify-center gap-1.5 rounded-lg border border-dashed border-slate-200/90 bg-white/40 py-2 text-[11.5px] text-slate-400 transition-colors hover:border-kiwi-300 hover:bg-kiwi-50/40 hover:text-kiwi-600"
              :disabled="busy"
              @click="insertCell('markdown')"
            >
              <KiwiIcon name="type" :size="12" />
              添加文本单元格
            </button>
          </div>

          <p class="mt-3 text-center text-[10.5px] leading-relaxed text-slate-300">
            共 {{ doc.cells.length }} 个单元格 · {{ codeCount }} 个代码单元格 ·
            Shift+Enter 运行并跳转 · Ctrl+Enter 运行 ·
            点击格标题后按 A/B 插入、M/Y 切换类型、DD 删除
          </p>
          <p class="mt-1 text-center text-[10.5px] leading-relaxed text-slate-300">
            代码在安全沙箱中执行，可直接导入 pandas / numpy / matplotlib；
            支持 !命令、%pip install、%uv pip install 安装依赖（网络已开启）
          </p>
        </div>
      </div>

      <div
        v-if="splitMode"
        ref="previewScrollEl"
        class="min-h-0 w-1/2 overflow-auto bg-slate-50/30"
      >
        <div class="mx-auto w-full max-w-[940px] px-4 py-3">
          <div
            class="mb-2 flex items-center gap-1.5 px-1 text-[10px] font-medium uppercase tracking-wide text-slate-400"
          >
            <KiwiIcon name="bookOpen" :size="11" />
            预览与输出
            <span v-if="runningCellId" class="ml-auto inline-flex items-center gap-1 text-kiwi-500">
              <KiwiIcon name="loader" :size="10" spin />
              执行中
            </span>
          </div>
          <NotebookPreview
            :doc="doc"
            :running-cell-id="runningCellId"
            empty-hint="还没有单元格，左侧添加后这里会实时预览"
          />
        </div>
      </div>

      <div
        v-if="readMode"
        ref="readAreaEl"
        class="min-h-0 flex flex-1 relative"
        :class="{ 'reading-zen': readZen }"
      >
        <div
          ref="readScrollEl"
          class="h-full min-w-0 flex-1 overflow-auto cursor-none"
        >
          <div class="mx-auto w-full max-w-[900px] px-5 py-5 pb-24" :style="{ zoom: readZoom }">
            <NotebookPreview
              :doc="doc"
              :running-cell-id="runningCellId"
              empty-hint="这个 Notebook 还没有内容"
              collapse-code
            />
            <p class="mt-6 text-center text-[10.5px] text-slate-300">
              阅读模式为只读预览 · 代码默认折叠，点击可展开 · 切换到「编辑」或「分屏」可修改并运行
            </p>
          </div>
        </div>

        <!-- 阅读模式：激光点 + 演示笔 + 缩放 / 全屏 -->
        <NoteReadingTools
          :area-el="readAreaEl"
          :scroller-el="readScrollEl"
          :zoom="readZoom"
          :zen="readZen"
          @update:zoom="readZoom = $event"
          @update:zen="readZen = $event"
        />
      </div>
    </div>

    <KiwiConfirm
      v-model="restartOpen"
      title="重启 Python 内核？"
      message="所有已定义的变量与导入将被清空，单元格输出会保留。"
      confirm-text="重启内核"
      @confirm="doRestart"
    />

    <KiwiModal
      :open="shortcutsOpen"
      title="Notebook 快捷键"
      max-w="max-w-2xl"
      @close="shortcutsOpen = false"
    >
      <div class="grid grid-cols-1 gap-x-8 gap-y-1.5 text-[12px] sm:grid-cols-2">
        <div
          v-for="item in SHORTCUTS"
          :key="item.keys"
          class="flex items-start justify-between gap-3 border-b border-slate-100/80 py-1"
        >
          <span class="text-slate-500">{{ item.label }}</span>
          <kbd
            class="shrink-0 rounded border border-slate-200 bg-slate-50 px-1.5 py-0.5 font-mono text-[10px] text-slate-500"
          >{{ item.keys }}</kbd>
        </div>
      </div>
      <p class="mt-4 rounded-lg bg-kiwi-50/60 px-3 py-2 text-[11px] leading-relaxed text-kiwi-700/80">
        命令模式：在单元格内按 Esc，或点击单元格标题。支持 <code>!pip install</code>、
        <code>%pip install</code>、<code>%uv pip install</code>、<code>%%bash</code> 等
        Jupyter 常用写法。
      </p>
    </KiwiModal>
  </div>
</template>

<style scoped>
.reading-zen {
  position: fixed;
  inset: 0;
  z-index: 100;
  overflow: hidden;
  background: #f8fafc;
}
</style>

<script setup lang="ts">
/** Word / Excel / PPT 在线预览：按需加载渲染库，避免拖慢主包。 */
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import KiwiIcon from '@/components/ui/KiwiIcon.vue'

const props = withDefaults(
  defineProps<{
    url: string
    filename: string
    contentType?: string
    /** 大屏预览：放大表格字号，让内容铺满可视区域 */
    large?: boolean
    /**
     * PPT 尺寸策略：
     * - contain：在可用宽高内等比放下并垂直居中（大屏预览）
     * - width：按容器宽度铺满，高度随幻灯片比例收缩（正文内嵌，避免底部留白）
     */
    fit?: 'contain' | 'width'
  }>(),
  { contentType: '', large: false, fit: 'contain' },
)

type OfficeKind = 'word' | 'excel' | 'ppt'

const ext = computed(
  () => props.filename.match(/\.([a-z0-9]+)$/i)?.[1]?.toLowerCase() ?? '',
)
const kind = computed<OfficeKind | null>(() => {
  const mime = (props.contentType ?? '').toLowerCase()
  if (ext.value === 'docx' || mime.includes('wordprocessingml.document')) return 'word'
  if (['xlsx', 'xlsm', 'xlsb', 'xls'].includes(ext.value)) return 'excel'
  if (mime.includes('spreadsheetml.sheet') || mime.includes('ms-excel')) return 'excel'
  if (ext.value === 'pptx' || mime.includes('presentationml.presentation')) return 'ppt'
  return null
})

const host = ref<HTMLElement | null>(null)
const loading = ref(false)
const error = ref('')
const sheets = ref<{ name: string; rows: string[][] }[]>([])
const activeSheet = ref(0)
const truncated = ref(false)

const MAX_ROWS = 300
const MAX_COLS = 40

interface PptxPreviewer {
  preview(file: ArrayBuffer): Promise<unknown>
  destroy?: () => void
  pptx?: { width?: number; height?: number }
}

let previewer: PptxPreviewer | null = null
let runToken = 0
let observer: ResizeObserver | null = null
let resizeTimer: number | null = null
let lastPptSize = { width: 0, height: 0 }
/** 幻灯片实际比例（高 / 宽）；首次按 16:9 估算，渲染后按文件真实尺寸校正。 */
let pptRatio = 9 / 16

const activeRows = computed(() => sheets.value[activeSheet.value]?.rows ?? [])

const pptAutoHeight = computed(() => kind.value === 'ppt' && props.fit === 'width')

/** 幻灯片按容器宽高等比适配；width 模式只受宽度约束，高度随比例收缩。 */
function pptSize(el: HTMLElement) {
  const availW = Math.max(320, el.clientWidth - 32)
  if (props.fit === 'width') {
    const width = availW
    return { width, height: Math.round(width * pptRatio) }
  }
  const availH = Math.max(180, el.clientHeight - 32)
  const width = Math.max(320, Math.min(availW, Math.round(availH / pptRatio)))
  return { width, height: Math.round(width * pptRatio) }
}

function schedulePptRerender() {
  if (kind.value !== 'ppt' || loading.value || !host.value) return
  const next = pptSize(host.value)
  if (
    Math.abs(next.width - lastPptSize.width) < 24 &&
    Math.abs(next.height - lastPptSize.height) < 24
  ) {
    return
  }
  if (resizeTimer !== null) window.clearTimeout(resizeTimer)
  resizeTimer = window.setTimeout(() => {
    resizeTimer = null
    void render()
  }, 250)
}

function teardown() {
  previewer?.destroy?.()
  previewer = null
  if (host.value) host.value.innerHTML = ''
}

async function render() {
  const token = ++runToken
  teardown()
  loading.value = true
  error.value = ''
  sheets.value = []
  activeSheet.value = 0
  truncated.value = false

  try {
    const res = await fetch(props.url)
    if (!res.ok) throw new Error(`读取文件失败（${res.status}）`)
    const buffer = await res.arrayBuffer()
    if (token !== runToken) return
    await nextTick()
    const el = host.value
    if (!el) return

    if (kind.value === 'word') {
      const { renderAsync } = await import('docx-preview')
      el.innerHTML = ''
      await renderAsync(buffer, el, el, {
        className: 'kiwi-docx',
        inWrapper: true,
        breakPages: true,
        ignoreLastRenderedPageBreak: true,
        useBase64URL: true,
        renderHeaders: true,
        renderFooters: true,
      })
    } else if (kind.value === 'excel') {
      const XLSX = await import('xlsx')
      const workbook = XLSX.read(buffer, { type: 'array' })
      const parsed: { name: string; rows: string[][] }[] = []
      let cut = false
      for (const name of workbook.SheetNames) {
        const sheet = workbook.Sheets[name]
        if (!sheet) continue
        const matrix = XLSX.utils.sheet_to_json<string[]>(sheet, {
          header: 1,
          raw: false,
          defval: '',
          blankrows: false,
        }) as unknown as unknown[][]
        if (matrix.length > MAX_ROWS || matrix.some((row) => row.length > MAX_COLS)) cut = true
        parsed.push({
          name,
          rows: matrix.slice(0, MAX_ROWS).map((row) =>
            row.slice(0, MAX_COLS).map((cell) => (cell == null ? '' : String(cell))),
          ),
        })
      }
      sheets.value = parsed.length ? parsed : [{ name: 'Sheet1', rows: [] }]
      truncated.value = cut
    } else if (kind.value === 'ppt') {
      const { init } = await import('pptx-preview')
      el.innerHTML = ''
      let size = pptSize(el)
      lastPptSize = size
      previewer = init(el, size)
      await previewer.preview(buffer)
      if (token !== runToken) return
      // 按文件真实宽高比校正一次（4:3 等非 16:9 幻灯片此前会多出一截底色）
      const rawW = Number(previewer.pptx?.width) || 0
      const rawH = Number(previewer.pptx?.height) || 0
      if (rawW > 0 && rawH > 0) {
        const ratio = rawH / rawW
        if (Math.abs(ratio - pptRatio) > 0.002) {
          pptRatio = ratio
          const next = pptSize(el)
          if (Math.abs(next.width - size.width) > 2 || Math.abs(next.height - size.height) > 2) {
            teardown()
            el.innerHTML = ''
            size = next
            lastPptSize = size
            previewer = init(el, size)
            await previewer.preview(buffer)
          }
        }
      }
    }
  } catch (e: any) {
    if (token === runToken) error.value = e?.message || '无法预览该文件'
  } finally {
    if (token === runToken) loading.value = false
  }
}

watch(
  () => [props.url, props.filename] as const,
  () => void render(),
  { immediate: true },
)

onMounted(() => {
  observer = new ResizeObserver(schedulePptRerender)
  if (host.value) observer.observe(host.value)
})

onBeforeUnmount(() => {
  runToken += 1
  observer?.disconnect()
  observer = null
  if (resizeTimer !== null) window.clearTimeout(resizeTimer)
  teardown()
})
</script>

<template>
  <div
    class="office-preview relative flex h-full min-h-0 w-full flex-col bg-slate-100"
    :class="[large ? 'is-large' : '', pptAutoHeight ? 'is-ppt-width' : '']"
  >
    <div
      v-if="kind === 'excel' && !error"
      class="flex shrink-0 items-center gap-1 overflow-x-auto border-b border-slate-200 bg-white px-2 py-1.5"
    >
      <button
        v-for="(sheet, index) in sheets"
        :key="sheet.name"
        type="button"
        class="shrink-0 rounded-md px-2 py-1 text-[11px] transition-colors"
        :class="index === activeSheet ? 'bg-emerald-50 text-emerald-700 font-medium' : 'text-slate-500 hover:bg-slate-100'"
        @click="activeSheet = index"
      >
        {{ sheet.name }}
      </button>
      <span v-if="truncated" class="ml-auto shrink-0 text-[10px] text-amber-500">
        仅展示前 {{ MAX_ROWS }} 行 / {{ MAX_COLS }} 列
      </span>
    </div>

    <div
      ref="host"
      class="office-host min-h-0 flex-1 overflow-auto"
      :class="{ 'is-ppt': kind === 'ppt', 'is-ppt-auto': pptAutoHeight }"
    >
      <div v-if="kind === 'excel' && !error" class="office-sheet p-3">
        <table v-if="activeRows.length" class="office-table">
          <tbody>
            <tr v-for="(row, rowIndex) in activeRows" :key="rowIndex">
              <th class="office-row-index">{{ rowIndex + 1 }}</th>
              <td v-for="(cell, colIndex) in row" :key="colIndex">{{ cell }}</td>
            </tr>
          </tbody>
        </table>
        <div v-else class="grid h-40 place-items-center text-[12px] text-slate-400">
          这个工作表没有内容
        </div>
      </div>
    </div>

    <div
      v-if="loading"
      class="absolute inset-0 z-10 grid place-items-center bg-slate-100/80 backdrop-blur-[1px]"
    >
      <span class="inline-flex items-center gap-2 text-[12px] text-slate-500">
        <KiwiIcon name="loader" :size="15" spin />
        正在渲染{{ kind === 'word' ? ' Word' : kind === 'excel' ? ' Excel' : ' PPT' }} 预览…
      </span>
    </div>

    <div v-if="error" class="absolute inset-0 grid place-items-center bg-slate-50 px-6">
      <div class="text-center">
        <KiwiIcon name="alert" :size="26" class="mx-auto text-amber-400" />
        <p class="mt-2 text-[12px] text-slate-500">{{ error }}</p>
        <a
          :href="url"
          :download="filename"
          class="kiwi-btn-primary mt-3 !py-1.5 !text-xs"
        >
          <KiwiIcon name="download" :size="13" />
          下载文件
        </a>
      </div>
    </div>
  </div>
</template>

<style scoped>
.office-host {
  background: #eef2f7;
}
/* PPT 在可用区域内垂直居中；内容超高时回退到顶部，保证滚动条可达 */
.office-host.is-ppt {
  display: flex;
  flex-direction: column;
  justify-content: safe center;
}
/* 正文内嵌：高度跟随幻灯片比例，避免卡片底部出现大片空白 */
.office-preview.is-ppt-width {
  height: auto;
}
.office-host.is-ppt-auto {
  flex: none;
  overflow: visible;
}
/* docx-preview 的 className 选项会把默认 .docx-wrapper 改名，这里必须用实际类名 */
.office-host :deep(.kiwi-docx-wrapper) {
  padding: 14px;
  background: #eef2f7;
  min-width: min-content;
  /* 页面比容器矮时也铺满底色，避免下方露出白色底边 */
  min-height: 100%;
  box-sizing: border-box;
}
.office-host :deep(.kiwi-docx-wrapper > section.kiwi-docx) {
  margin: 0 auto 14px;
  box-shadow: 0 6px 22px rgba(15, 23, 42, 0.08);
}
.office-sheet {
  min-width: min-content;
}
.office-table {
  border-collapse: collapse;
  background: #fff;
  font-size: 12.5px;
  color: #334155;
}
/* 大屏预览下放大字号与行高，避免整页表格缩成一小块 */
.office-preview.is-large .office-table {
  font-size: 15px;
  /* 大屏下让表格铺满可用宽度，而不是缩在左上角 */
  min-width: 100%;
}
.office-preview.is-large .office-table td,
.office-preview.is-large .office-table th {
  padding: 6px 11px;
  min-width: 88px;
}
.office-preview.is-large .office-row-index {
  width: 40px;
  min-width: 40px;
  max-width: 40px;
}
.office-preview.is-large .office-sheet {
  padding: 18px;
}
.office-table td,
.office-table th {
  border: 1px solid #e2e8f0;
  padding: 4px 8px;
  max-width: 320px;
  min-width: 64px;
  white-space: pre-wrap;
  word-break: break-word;
  vertical-align: top;
}
.office-table tr:first-child td {
  background: #f8fafc;
  font-weight: 500;
}
.office-row-index {
  position: sticky;
  left: 0;
  z-index: 1;
  width: 32px;
  min-width: 32px;
  max-width: 32px;
  background: #f1f5f9;
  color: #94a3b8;
  font-weight: 400;
  text-align: center;
}
</style>

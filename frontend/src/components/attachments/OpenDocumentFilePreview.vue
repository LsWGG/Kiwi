<script setup lang="ts">
/**
 * OpenDocument（.odt / .ods / .odp）预览：解压 content.xml 后离线渲染。
 * 不依赖 Office 或第三方渲染服务，保留标题、段落、列表、表格与图片的基本版式。
 */
import { computed, ref, watch } from 'vue'
import type JSZip from 'jszip'
import DOMPurify from 'dompurify'
import KiwiIcon from '@/components/ui/KiwiIcon.vue'

const props = defineProps<{
  url: string
  filename: string
  /** fill：铺满父容器；block：按内容高度展示，用于正文内嵌预览。 */
  fit?: 'fill' | 'block'
}>()

const isBlock = computed(() => props.fit === 'block')
const ext = computed(() => props.filename.match(/\.([a-z0-9]+)$/i)?.[1]?.toLowerCase() ?? '')
const kind = computed<'odt' | 'ods' | 'odp' | null>(() => {
  if (ext.value === 'ods') return 'ods'
  if (ext.value === 'odp') return 'odp'
  if (ext.value === 'odt') return 'odt'
  return null
})

const loading = ref(false)
const error = ref('')

const documentHtml = ref('')
const slides = ref<{ name: string; html: string }[]>([])
const sheets = ref<{ name: string; rows: string[][] }[]>([])
const activeSheet = ref(0)
const truncated = ref(false)

const MAX_ROWS = 300
const MAX_COLS = 40
const MAX_PAGES = 30
const MAX_DEPTH = 8
const MAX_IMAGE_BYTES = 8 * 1024 * 1024

const activeRows = computed(() => sheets.value[activeSheet.value]?.rows ?? [])

const escapeHtml = (value: string) =>
  value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')

const escapeAttr = (value: string) => escapeHtml(value).replace(/'/g, '&#39;')

/** 行内内容：文本、空格、制表符、换行、超链接与嵌套 span。 */
function inlineHtml(el: Element): string {
  let out = ''
  for (const node of Array.from(el.childNodes)) {
    if (node.nodeType === Node.TEXT_NODE) {
      out += escapeHtml(node.textContent ?? '')
      continue
    }
    if (node.nodeType !== Node.ELEMENT_NODE) continue
    const child = node as Element
    switch (child.localName) {
      case 's':
        out += ' '.repeat(Math.min(40, Number(child.getAttribute('text:c')) || 1))
        break
      case 'tab':
        out += '&emsp;'
        break
      case 'line-break':
        out += '<br>'
        break
      case 'a': {
        const inner = inlineHtml(child)
        const href = child.getAttribute('xlink:href') || ''
        out += /^https?:/i.test(href)
          ? `<a href="${escapeAttr(href)}" target="_blank" rel="noopener noreferrer">${inner}</a>`
          : inner
        break
      }
      case 'note':
        break
      default:
        out += inlineHtml(child)
    }
  }
  return out
}

async function zipImageSrc(zip: JSZip, href: string): Promise<string> {
  if (!href) return ''
  if (/^(https?:|data:)/i.test(href)) return href
  const path = decodeURIComponent(href.replace(/^\.\//, ''))
  const file = zip.file(path)
  if (!file) return ''
  const suffix = path.split('.').pop()?.toLowerCase() ?? 'png'
  const mime =
    {
      png: 'image/png',
      jpg: 'image/jpeg',
      jpeg: 'image/jpeg',
      gif: 'image/gif',
      svg: 'image/svg+xml',
      webp: 'image/webp',
      bmp: 'image/bmp',
    }[suffix] ?? 'application/octet-stream'
  const uncompressed = Number(
    (file as unknown as { _data?: { uncompressedSize?: number } })._data?.uncompressedSize ?? 0,
  )
  if (uncompressed > MAX_IMAGE_BYTES) return ''
  const base64 = await file.async('base64')
  return `data:${mime};base64,${base64}`
}

async function frameHtml(frame: Element, zip: JSZip): Promise<string> {
  const image = frame.getElementsByTagName('draw:image')[0]
  if (image) {
    const href = image.getAttribute('xlink:href') || ''
    const src = await zipImageSrc(zip, href)
    if (src) {
      const title = frame.getElementsByTagName('svg:title')[0]?.textContent?.trim() || ''
      return `<figure class="odf-image"><img src="${escapeAttr(src)}" alt="${escapeAttr(title)}" /></figure>`
    }
  }
  const boxes = Array.from(frame.getElementsByTagName('draw:text-box'))
  if (!boxes.length) return ''
  let out = ''
  for (const box of boxes) out += await blockChildrenHtml(box, zip, 1)
  return out
}

async function blockChildrenHtml(parent: Element, zip: JSZip, depth: number): Promise<string> {
  if (depth > MAX_DEPTH) return ''
  let out = ''
  for (const child of Array.from(parent.children)) {
    out += await blockNodeHtml(child, zip, depth)
  }
  return out
}

async function blockNodeHtml(node: Element, zip: JSZip, depth: number): Promise<string> {
  switch (node.localName) {
    case 'h': {
      const level = Math.min(6, Math.max(1, Number(node.getAttribute('text:outline-level')) || 1))
      return `<h${level}>${inlineHtml(node)}</h${level}>`
    }
    case 'p':
      return `<p>${inlineHtml(node)}</p>`
    case 'list':
      return listHtml(node, zip, depth)
    case 'table':
      return tableHtml(node)
    case 'frame':
      return frameHtml(node, zip)
    case 'section':
    case 'text-box':
      return blockChildrenHtml(node, zip, depth + 1)
    default:
      return blockChildrenHtml(node, zip, depth + 1)
  }
}

async function listHtml(list: Element, zip: JSZip, depth: number): Promise<string> {
  if (depth > MAX_DEPTH) return ''
  let out = '<ul>'
  for (const item of Array.from(list.children)) {
    if (item.localName !== 'list-item') continue
    let inner = ''
    for (const child of Array.from(item.children)) {
      inner += await blockNodeHtml(child, zip, depth + 1)
    }
    out += `<li>${inner}</li>`
  }
  return `${out}</ul>`
}

function cellTextHtml(cell: Element): string {
  const paragraphs = Array.from(cell.children).filter((child) => child.localName === 'p')
  if (paragraphs.length) return paragraphs.map((p) => inlineHtml(p)).join('<br>')
  return inlineHtml(cell)
}

function tableHtml(table: Element): string {
  const rowElements: Element[] = []
  for (const child of Array.from(table.children)) {
    if (child.localName === 'table-row') rowElements.push(child)
    else if (child.localName === 'table-header-rows') {
      rowElements.push(
        ...Array.from(child.children).filter((row) => row.localName === 'table-row'),
      )
    }
  }
  const headerCount = rowElements.filter((row) => row.parentElement?.localName === 'table-header-rows').length
  const bodyParts: string[] = []
  for (const [rowIndex, row] of rowElements.slice(0, MAX_ROWS).entries()) {
    const cells: string[] = []
    for (const cell of Array.from(row.children)) {
      if (cell.localName !== 'table-cell' && cell.localName !== 'covered-table-cell') continue
      const repeat = Math.min(
        MAX_COLS,
        Math.max(1, Number(cell.getAttribute('table:number-columns-repeated')) || 1),
      )
      const text = cellTextHtml(cell)
      for (let index = 0; index < repeat && cells.length < MAX_COLS; index += 1) {
        cells.push(text)
      }
    }
    const tag = rowIndex < headerCount ? 'th' : 'td'
    bodyParts.push(`<tr>${cells.map((cell) => `<${tag}>${cell}</${tag}>`).join('')}</tr>`)
  }
  return `<table>${bodyParts.join('')}</table>`
}

async function buildText(root: Element, zip: JSZip) {
  const body = root.getElementsByTagName('office:text')[0]
  if (!body) throw new Error('文档正文为空')
  const html = await blockChildrenHtml(body, zip, 0)
  if (!html.trim()) throw new Error('文档正文为空')
  documentHtml.value = DOMPurify.sanitize(html)
}

async function buildPresentation(root: Element, zip: JSZip) {
  const pages = Array.from(root.getElementsByTagName('draw:page')).slice(0, MAX_PAGES)
  if (!pages.length) throw new Error('演示文稿没有幻灯片')
  const result: { name: string; html: string }[] = []
  for (const [index, page] of pages.entries()) {
    const html = await blockChildrenHtml(page, zip, 0)
    result.push({
      name: page.getAttribute('draw:name') || `第 ${index + 1} 页`,
      html: DOMPurify.sanitize(html),
    })
  }
  slides.value = result
}

async function buildSheet(root: Element, zip: JSZip) {
  void zip
  const tables = Array.from(root.getElementsByTagName('table:table'))
  const parsed: { name: string; rows: string[][] }[] = []
  let cut = false
  for (const table of tables) {
    const rows: string[][] = []
    const rowElements = Array.from(table.getElementsByTagName('table:table-row'))
    for (const rowElement of rowElements) {
      if (rows.length >= MAX_ROWS) {
        cut = true
        break
      }
      const repeatRows = Math.min(
        MAX_ROWS - rows.length,
        Math.max(1, Number(rowElement.getAttribute('table:number-rows-repeated')) || 1),
      )
      const cells: string[] = []
      for (const cell of Array.from(rowElement.children)) {
        if (cell.localName !== 'table-cell' && cell.localName !== 'covered-table-cell') continue
        let value = ''
        const paragraphs = Array.from(cell.children).filter((child) => child.localName === 'p')
        if (paragraphs.length) {
          value = paragraphs
            .map((p) => (p.textContent ?? '').trim())
            .filter(Boolean)
            .join('\n')
        }
        if (!value) {
          value =
            cell.getAttribute('office:value') ??
            cell.getAttribute('office:string-value') ??
            cell.getAttribute('office:date-value') ??
            ''
        }
        const repeat = Math.min(
          MAX_COLS,
          Math.max(1, Number(cell.getAttribute('table:number-columns-repeated')) || 1),
        )
        for (let index = 0; index < repeat && cells.length < MAX_COLS; index += 1) {
          cells.push(value)
        }
        if (cells.length >= MAX_COLS) cut = true
      }
      while (cells.length && cells[cells.length - 1] === '') cells.pop()
      for (let index = 0; index < repeatRows; index += 1) rows.push([...cells])
    }
    while (rows.length && !rows[rows.length - 1].some((cell) => cell !== '')) rows.pop()
    parsed.push({
      name: table.getAttribute('table:name') || `工作表 ${parsed.length + 1}`,
      rows,
    })
  }
  if (!parsed.length) throw new Error('表格没有工作表')
  sheets.value = parsed
  activeSheet.value = 0
  truncated.value = cut
}

async function load() {
  loading.value = true
  error.value = ''
  documentHtml.value = ''
  slides.value = []
  sheets.value = []
  activeSheet.value = 0
  truncated.value = false
  if (!kind.value) {
    error.value = '不支持的 OpenDocument 类型'
    loading.value = false
    return
  }
  try {
    const res = await fetch(props.url)
    if (!res.ok) throw new Error(`读取失败（${res.status}）`)
    const buffer = await res.arrayBuffer()
    const { default: JSZipCtor } = await import('jszip')
    const zip = await JSZipCtor.loadAsync(buffer)
    const contentFile = zip.file('content.xml')
    if (!contentFile) throw new Error('不是有效的 OpenDocument 文件（缺少 content.xml）')
    const xml = await contentFile.async('text')
    const doc = new DOMParser().parseFromString(xml, 'application/xml')
    if (doc.querySelector('parsererror')) throw new Error('content.xml 解析失败')
    const root = doc.documentElement
    if (kind.value === 'ods') await buildSheet(root, zip)
    else if (kind.value === 'odp') await buildPresentation(root, zip)
    else await buildText(root, zip)
  } catch (e: any) {
    error.value = e?.message || '无法预览该文件'
  } finally {
    loading.value = false
  }
}

watch(() => [props.url, kind.value] as const, () => void load(), { immediate: true })
</script>

<template>
  <div
    class="relative flex w-full flex-col bg-white"
    :class="isBlock ? 'max-h-[560px] overflow-auto' : 'h-full min-h-0'"
  >
    <div v-if="loading" class="grid place-items-center py-16 text-[12px] text-slate-400">
      <span class="inline-flex items-center gap-2">
        <KiwiIcon name="loader" :size="15" spin />
        正在解析 OpenDocument…
      </span>
    </div>

    <div v-else-if="error" class="grid place-items-center py-16">
      <div class="text-center px-6">
        <KiwiIcon name="alert" :size="26" class="mx-auto text-amber-400" />
        <p class="mt-2 text-[12px] text-slate-500">{{ error }}</p>
        <a :href="url" :download="filename" class="kiwi-btn-primary mt-3 !py-1.5 !text-xs">
          <KiwiIcon name="download" :size="13" />
          下载文件
        </a>
      </div>
    </div>

    <!-- 文字文档 -->
    <div
      v-else-if="kind === 'odt'"
      class="w-full"
      :class="isBlock ? '' : 'flex-1 min-h-0 overflow-auto'"
    >
      <div class="prose-wiki odf-doc px-6 py-5" v-html="documentHtml" />
    </div>

    <!-- 演示文稿：每页一张卡片 -->
    <div
      v-else-if="kind === 'odp'"
      class="w-full bg-slate-50"
      :class="isBlock ? '' : 'flex-1 min-h-0 overflow-auto'"
    >
      <section
        v-for="(slide, index) in slides"
        :key="index"
        class="odf-slide"
      >
        <p class="odf-slide-name">{{ slide.name }}</p>
        <div class="prose-wiki odf-slide-body px-5 py-4" v-html="slide.html" />
      </section>
    </div>

    <!-- 电子表格：工作表切换 -->
    <template v-else-if="kind === 'ods'">
      <div class="flex shrink-0 items-center gap-1 overflow-x-auto border-b border-slate-200 bg-white px-2 py-1.5">
        <button
          v-for="(sheet, index) in sheets"
          :key="sheet.name"
          type="button"
          class="shrink-0 rounded-md px-2 py-1 text-[11px] transition-colors"
          :class="index === activeSheet ? 'bg-emerald-50 font-medium text-emerald-700' : 'text-slate-500 hover:bg-slate-100'"
          @click="activeSheet = index"
        >
          {{ sheet.name }}
        </button>
        <span v-if="truncated" class="ml-auto shrink-0 text-[10px] text-amber-500">
          仅展示前 {{ MAX_ROWS }} 行 / {{ MAX_COLS }} 列
        </span>
      </div>
      <div class="w-full" :class="isBlock ? 'p-3' : 'flex-1 min-h-0 overflow-auto p-3'">
        <table v-if="activeRows.length" class="odf-table">
          <tbody>
            <tr v-for="(row, rowIndex) in activeRows" :key="rowIndex">
              <th class="odf-row-index">{{ rowIndex + 1 }}</th>
              <td v-for="(cell, colIndex) in row" :key="colIndex">{{ cell }}</td>
            </tr>
          </tbody>
        </table>
        <div v-else class="grid h-40 place-items-center text-[12px] text-slate-400">
          这个工作表没有内容
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.odf-doc {
  font-size: 14px;
  line-height: 1.8;
  color: #334155;
}
.odf-doc :deep(img),
.odf-slide-body :deep(img) {
  max-width: 100%;
  height: auto;
}
.odf-doc :deep(.odf-image) {
  margin: 12px 0;
}
.odf-slide {
  margin: 14px;
  padding: 4px 0 10px;
  background: #fff;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  box-shadow: 0 1px 2px rgb(15 23 42 / 0.04);
  overflow: hidden;
}
.odf-slide-name {
  margin: 0;
  padding: 7px 16px;
  border-bottom: 1px solid #eef2f6;
  background: #f8fafc;
  font-size: 10.5px;
  color: #94a3b8;
}
.odf-slide-body {
  font-size: 14px;
  line-height: 1.8;
  color: #334155;
  min-height: 96px;
}
.odf-slide-body :deep(h1) {
  font-size: 1.5em;
}
.odf-table {
  border-collapse: collapse;
  min-width: 100%;
  width: max-content;
  background: #fff;
  font-size: 12.5px;
  color: #334155;
}
.odf-table td,
.odf-table th {
  border: 1px solid #e2e8f0;
  padding: 4px 8px;
  max-width: 320px;
  min-width: 64px;
  white-space: pre-wrap;
  word-break: break-word;
  vertical-align: top;
  text-align: left;
}
.odf-table tr:first-child td {
  background: #f8fafc;
  font-weight: 500;
}
.odf-row-index {
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

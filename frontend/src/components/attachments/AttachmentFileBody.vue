<script setup lang="ts">
/**
 * 附件正文预览：图片 / PDF / Office / 音视频 / 网页 / Markdown / 表格 / JSON / YAML / XML /
 * JSONL / Notebook / 差异 / 配置 / 压缩包 / 文本。
 */
import { computed, ref, watch } from 'vue'
import MarkdownIt from 'markdown-it'
import DOMPurify from 'dompurify'
import KiwiIcon from '@/components/ui/KiwiIcon.vue'
import OfficeFilePreview from '@/components/attachments/OfficeFilePreview.vue'
import OpenDocumentFilePreview from '@/components/attachments/OpenDocumentFilePreview.vue'
import JsonTree from '@/components/attachments/JsonTree.vue'
import NotebookFilePreview from '@/components/attachments/NotebookFilePreview.vue'

const props = defineProps<{
  url: string
  filename: string
  contentType?: string
  size?: number
  /** fill：铺满父容器；block：按内容高度展示（最多 560px），用于正文内嵌预览。 */
  fit?: 'fill' | 'block'
}>()

const isBlock = computed(() => props.fit === 'block')

const text = ref('')
const textLoading = ref(false)
const textError = ref('')
const textTruncated = ref(false)

const MAX_TEXT_BYTES = 512 * 1024
const MAX_CSV_ROWS = 1000
const MAX_CSV_COLS = 30

const ext = computed(() => props.filename.match(/\.([a-z0-9]+)$/i)?.[1]?.toLowerCase() ?? '')
const baseName = computed(
  () => (props.filename.split(/[\\/]/).pop() ?? '').toLowerCase(),
)
const mime = computed(() => (props.contentType ?? '').toLowerCase())
const kind = computed<
  | 'image'
  | 'pdf'
  | 'video'
  | 'audio'
  | 'html'
  | 'markdown'
  | 'json'
  | 'jsonl'
  | 'csv'
  | 'yaml'
  | 'toml'
  | 'xml'
  | 'ipynb'
  | 'diff'
  | 'config'
  | 'archive'
  | 'text'
  | 'word'
  | 'excel'
  | 'ppt'
  | 'odf'
  | 'other'
>(() => {
  if (
    mime.value.startsWith('image/') ||
    ['png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp', 'avif', 'svg'].includes(ext.value)
  ) {
    return 'image'
  }
  if (mime.value === 'application/pdf' || ext.value === 'pdf') return 'pdf'
  // CSV 有时会被浏览器标成 application/vnd.ms-excel，先于 Office 判断。
  if (ext.value === 'csv' || ext.value === 'tsv' || mime.value === 'text/csv') return 'csv'
  if (
    ['docx', 'docm', 'dotx', 'dotm'].includes(ext.value) ||
    mime.value.includes('wordprocessingml') ||
    mime.value.includes('ms-word')
  ) {
    return 'word'
  }
  if (
    ['xlsx', 'xlsm', 'xlsb', 'xls', 'xltx', 'xltm'].includes(ext.value) ||
    mime.value.includes('spreadsheetml') ||
    mime.value.includes('ms-excel')
  ) {
    return 'excel'
  }
  if (
    ['pptx', 'pptm', 'potx', 'potm', 'ppsx', 'ppsm'].includes(ext.value) ||
    mime.value.includes('presentationml') ||
    mime.value.includes('ms-powerpoint')
  ) {
    return 'ppt'
  }
  if (['odt', 'ods', 'odp'].includes(ext.value) || mime.value.includes('opendocument')) {
    return 'odf'
  }
  if (
    mime.value.startsWith('video/') ||
    ['mp4', 'webm', 'mov', 'mkv', 'avi', 'm4v'].includes(ext.value)
  ) {
    return 'video'
  }
  if (mime.value.startsWith('audio/') || ['mp3', 'wav', 'ogg', 'flac', 'm4a'].includes(ext.value)) {
    return 'audio'
  }
  // 网页与 Markdown 直接渲染为可视内容，而不是展示源码。
  if (
    ext.value === 'html' ||
    ext.value === 'htm' ||
    ext.value === 'xhtml' ||
    mime.value === 'text/html' ||
    mime.value === 'application/xhtml+xml'
  ) {
    return 'html'
  }
  if (['md', 'markdown', 'mdx'].includes(ext.value) || mime.value.includes('markdown')) {
    return 'markdown'
  }
  // 结构化 / 文档类格式先于通用 JSON / text 判断，避免被更宽的 MIME 规则吞掉。
  if (ext.value === 'ipynb' || mime.value.includes('ipynb')) return 'ipynb'
  if (ext.value === 'jsonl' || ext.value === 'ndjson' || mime.value.includes('ndjson')) {
    return 'jsonl'
  }
  if (['yaml', 'yml'].includes(ext.value) || mime.value.includes('yaml')) return 'yaml'
  if (ext.value === 'toml' || mime.value.includes('toml')) return 'toml'
  if (
    ['xml', 'xsd', 'xsl', 'xslt', 'rss', 'atom', 'plist'].includes(ext.value) ||
    mime.value.includes('xml')
  ) {
    return 'xml'
  }
  if (['diff', 'patch'].includes(ext.value) || mime.value.includes('diff')) return 'diff'
  if (['zip', 'jar', 'war', 'whl', 'apk'].includes(ext.value) || mime.value.includes('zip')) {
    return 'archive'
  }
  if (
    ['ini', 'cfg', 'conf', 'properties', 'env'].includes(ext.value) ||
    baseName.value === '.env' ||
    baseName.value.startsWith('.env.')
  ) {
    return 'config'
  }
  if (['json', 'geojson', 'jsonc'].includes(ext.value) || mime.value.includes('json')) {
    return 'json'
  }
  if (
    mime.value.startsWith('text/') ||
    mime.value.includes('javascript') ||
    [
      'txt', 'log', 'text',
      'js', 'mjs', 'ts', 'jsx', 'tsx', 'vue', 'py', 'sh', 'bash', 'zsh', 'sql',
      'css', 'scss', 'less',
    ].includes(ext.value)
  ) {
    return 'text'
  }
  return 'other'
})

const TEXT_KINDS = [
  'text',
  'markdown',
  'json',
  'jsonl',
  'csv',
  'yaml',
  'toml',
  'xml',
  'ipynb',
  'diff',
  'config',
] as const
const isTextLike = computed(() => (TEXT_KINDS as readonly string[]).includes(kind.value))

async function loadText(url: string) {
  text.value = ''
  textError.value = ''
  textTruncated.value = false
  textLoading.value = true
  try {
    const res = await fetch(url)
    if (!res.ok) throw new Error(`读取失败（${res.status}）`)
    const blob = await res.blob()
    if (blob.size > MAX_TEXT_BYTES) {
      text.value = await blob.slice(0, MAX_TEXT_BYTES).text()
      textTruncated.value = true
    } else {
      text.value = await blob.text()
    }
  } catch (e: any) {
    textError.value = e?.message || '无法读取文件内容'
  } finally {
    textLoading.value = false
  }
}

watch(
  () => [props.url, kind.value] as const,
  ([url, current]) => {
    if (url && (TEXT_KINDS as readonly string[]).includes(current)) void loadText(url)
  },
  { immediate: true },
)

// ---------- 压缩包 ----------
const MAX_ARCHIVE_BYTES = 80 * 1024 * 1024
const MAX_ARCHIVE_ENTRIES = 500

interface ArchiveEntry {
  path: string
  name: string
  depth: number
  dir: boolean
  size: number
}

const archiveEntries = ref<ArchiveEntry[]>([])
const archiveLoading = ref(false)
const archiveError = ref('')
const archiveTruncated = ref(false)

function formatBytes(value: number) {
  if (!value) return ''
  if (value < 1024) return `${value} B`
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`
  return `${(value / (1024 * 1024)).toFixed(1)} MB`
}

async function loadArchive(url: string) {
  archiveEntries.value = []
  archiveError.value = ''
  archiveTruncated.value = false
  if (props.size && props.size > MAX_ARCHIVE_BYTES) {
    archiveError.value = '压缩包超过 80 MB，请下载后查看'
    return
  }
  archiveLoading.value = true
  try {
    const res = await fetch(url)
    if (!res.ok) throw new Error(`读取失败（${res.status}）`)
    const buffer = await res.arrayBuffer()
    if (buffer.byteLength > MAX_ARCHIVE_BYTES) {
      archiveError.value = '压缩包超过 80 MB，请下载后查看'
      return
    }
    const { default: JSZip } = await import('jszip')
    const zip = await JSZip.loadAsync(buffer)
    const entries: ArchiveEntry[] = []
    const seen = new Set<string>()
    for (const file of Object.values(zip.files)) {
      const path = file.name.replace(/\\/g, '/').replace(/\/$/, '')
      if (!path || seen.has(path)) continue
      seen.add(path)
      entries.push({
        path,
        name: path.split('/').pop() ?? path,
        depth: Math.max(0, path.split('/').length - 1),
        dir: file.dir,
        size:
          Number(
            (file as unknown as { _data?: { uncompressedSize?: number } })._data
              ?.uncompressedSize ?? 0,
          ) || 0,
      })
    }
    // 部分打包工具不写入目录条目，从文件路径补齐父级文件夹，列表才能呈树状。
    for (const entry of [...entries]) {
      const parts = entry.path.split('/')
      for (let index = 1; index < parts.length; index += 1) {
        const dirPath = parts.slice(0, index).join('/')
        if (seen.has(dirPath)) continue
        seen.add(dirPath)
        entries.push({ path: dirPath, name: parts[index - 1], depth: index - 1, dir: true, size: 0 })
      }
    }
    entries.sort((a, b) => a.path.localeCompare(b.path, 'zh-Hans-CN'))
    archiveEntries.value = entries.slice(0, MAX_ARCHIVE_ENTRIES)
    archiveTruncated.value = entries.length > MAX_ARCHIVE_ENTRIES
  } catch (e: any) {
    archiveError.value = e?.message || '无法读取压缩包'
  } finally {
    archiveLoading.value = false
  }
}

watch(
  () => [props.url, kind.value] as const,
  ([url, current]) => {
    if (url && current === 'archive') void loadArchive(url)
  },
  { immediate: true },
)

// ---------- YAML / TOML ----------
const structured = ref<{
  status: 'idle' | 'loading' | 'ok' | 'empty' | 'error'
  value?: unknown
  error?: string
}>({ status: 'idle' })
let structuredToken = 0

watch(
  () => [kind.value, text.value] as const,
  async ([current, source]) => {
    if (current !== 'yaml' && current !== 'toml') {
      structured.value = { status: 'idle' }
      return
    }
    if (!source) {
      structured.value = { status: 'empty' }
      return
    }
    const token = ++structuredToken
    structured.value = { status: 'loading' }
    try {
      let value: unknown
      if (current === 'yaml') {
        const { parseAllDocuments } = await import('yaml')
        const docs = parseAllDocuments(source)
        const firstError = docs.flatMap((doc) => doc.errors)[0]
        if (firstError) throw firstError
        const values = docs.map((doc) => doc.toJS())
        value = values.length === 1 ? values[0] : values
      } else {
        const { parse } = await import('smol-toml')
        value = parse(source)
      }
      if (token !== structuredToken) return
      structured.value = { status: 'ok', value }
    } catch (e: any) {
      if (token !== structuredToken) return
      structured.value = { status: 'error', error: e?.message || '解析失败' }
    }
  },
  { immediate: true },
)

// ---------- XML ----------
function xmlElementToValue(el: Element): unknown {
  const record: Record<string, unknown> = {}
  for (const attr of Array.from(el.attributes)) record[`@${attr.name}`] = attr.value
  const children = Array.from(el.children)
  if (!children.length) {
    const value = (el.textContent ?? '').trim()
    if (!Object.keys(record).length) return value
    if (value) record['#text'] = value
    return record
  }
  for (const child of children) {
    const key = child.nodeName
    const value = xmlElementToValue(child)
    if (key in record) {
      const existing = record[key]
      if (Array.isArray(existing)) existing.push(value)
      else record[key] = [existing, value]
    } else {
      record[key] = value
    }
  }
  const ownText = Array.from(el.childNodes)
    .filter((node) => node.nodeType === Node.TEXT_NODE)
    .map((node) => node.textContent ?? '')
    .join('')
    .trim()
  if (ownText) record['#text'] = ownText
  return record
}

const xmlTree = computed<{ error: string; value: unknown } | null>(() => {
  if (kind.value !== 'xml' || !text.value) return null
  const doc = new DOMParser().parseFromString(text.value, 'application/xml')
  if (doc.querySelector('parsererror')) return { error: 'XML 解析失败', value: null }
  const root = doc.documentElement
  if (!root) return { error: 'XML 内容为空', value: null }
  return { error: '', value: { [root.nodeName]: xmlElementToValue(root) } }
})

// ---------- JSON Lines ----------
const MAX_JSONL_RECORDS = 50

interface JsonlRecord {
  line: number
  value?: unknown
  raw: string
  error: string
}

const jsonlView = computed(() => {
  if (kind.value !== 'jsonl' || !text.value) return null
  const lines = text.value.split(/\r?\n/).filter((line) => line.trim())
  const records: JsonlRecord[] = lines.slice(0, MAX_JSONL_RECORDS).map((raw, index) => {
    try {
      return { line: index + 1, value: JSON.parse(raw), raw, error: '' }
    } catch (e: any) {
      return { line: index + 1, raw, error: e?.message || '解析失败' }
    }
  })
  return { records, total: lines.length, shown: records.length }
})

function jsonlPreview(value: unknown): string {
  if (Array.isArray(value)) return `[ ${value.length} 项 ]`
  if (value && typeof value === 'object') {
    const keys = Object.keys(value as Record<string, unknown>)
    return keys.length ? keys.slice(0, 6).join(' · ') : '{}'
  }
  return String(value)
}

// ---------- 差异文件 ----------
type DiffLineType = 'ctx' | 'add' | 'del' | 'hunk' | 'meta'

const diffLines = computed<{ line: number; text: string; type: DiffLineType }[] | null>(() => {
  if (kind.value !== 'diff' || !text.value.trim()) return null
  return text.value
    .replace(/\r\n?/g, '\n')
    .split('\n')
    .map((line, index) => {
      let type: DiffLineType = 'ctx'
      if (line.startsWith('@@')) type = 'hunk'
      else if (
        line.startsWith('+++') ||
        line.startsWith('---') ||
        line.startsWith('diff ') ||
        line.startsWith('index ') ||
        line.startsWith('new file') ||
        line.startsWith('deleted file') ||
        line.startsWith('similarity index') ||
        line.startsWith('rename ') ||
        line.startsWith('\\ No newline')
      ) {
        type = 'meta'
      } else if (line.startsWith('+')) type = 'add'
      else if (line.startsWith('-')) type = 'del'
      return { line: index + 1, text: line, type }
    })
})

// ---------- INI / ENV / properties ----------
interface ConfigEntry {
  section: string
  key: string
  value: string
}

const configView = computed<ConfigEntry[] | null>(() => {
  if (kind.value !== 'config' || !text.value) return null
  let section = ''
  const entries: ConfigEntry[] = []
  for (const raw of text.value.replace(/\r\n?/g, '\n').split('\n')) {
    const trimmed = raw.trim()
    if (
      !trimmed ||
      trimmed.startsWith('#') ||
      trimmed.startsWith(';') ||
      trimmed.startsWith('//')
    ) {
      continue
    }
    const heading = trimmed.match(/^\[(.+)\]$/)
    if (heading) {
      section = heading[1].trim()
      continue
    }
    const eq = raw.indexOf('=')
    if (eq < 0) continue
    const key = raw.slice(0, eq).trim().replace(/^export\s+/, '')
    if (!key) continue
    let value = raw.slice(eq + 1).trim()
    if (
      (value.startsWith('"') && value.endsWith('"')) ||
      (value.startsWith("'") && value.endsWith("'"))
    ) {
      value = value.slice(1, -1)
    }
    entries.push({ section, key, value })
  }
  return entries.length ? entries : null
})

// ---------- Markdown ----------
/** Markdown 内的相对图片 / 链接按文件自身地址解析，绝对地址原样保留。 */
function resolveAssetUrl(value: string): string {
  const raw = (value || '').trim()
  if (!raw || raw.startsWith('#') || raw.startsWith('/') || /^[a-z][a-z0-9+.-]*:/i.test(raw)) {
    return raw
  }
  try {
    return new URL(raw, new URL(props.url, window.location.href)).toString()
  } catch {
    return raw
  }
}

const md = new MarkdownIt({
  html: true,
  linkify: true,
  breaks: false,
  typographer: false,
})

md.core.ruler.push('kiwi_resolve_relative_urls', (state) => {
  for (const token of state.tokens) {
    if (token.type !== 'inline' || !token.children) continue
    for (const child of token.children) {
      const attr = child.type === 'image' ? 'src' : child.type === 'link_open' ? 'href' : ''
      if (!attr) continue
      const index = child.attrIndex(attr)
      const value = index >= 0 ? child.attrs?.[index]?.[1] : ''
      if (value) child.attrs![index][1] = resolveAssetUrl(value)
    }
  }
})

const markdownHtml = computed(() => {
  if (!text.value) return ''
  return DOMPurify.sanitize(md.render(text.value))
})

// ---------- JSON ----------
const jsonParsed = computed<
  { ok: true; value: unknown } | { ok: false; error: string }
>(() => {
  try {
    return { ok: true, value: JSON.parse(text.value) }
  } catch (e: any) {
    return { ok: false, error: e?.message || 'JSON 解析失败' }
  }
})

// ---------- CSV / TSV ----------
interface CsvView {
  header: string[]
  rows: string[][]
  totalRows: number
  columnCount: number
  truncatedRows: boolean
  truncatedCols: boolean
}

function detectDelimiter(source: string): string {
  if (ext.value === 'tsv') return '\t'
  const firstLine = source.split(/\r?\n/, 1)[0] ?? ''
  const count = (char: string) => firstLine.split(char).length - 1
  if (count('\t') > count(',')) return '\t'
  if (count(';') > count(',')) return ';'
  return ','
}

function parseDelimited(source: string, delimiter: string) {
  const rows: string[][] = []
  let row: string[] = []
  let field = ''
  let quoted = false
  let truncated = false
  const input = source.replace(/^﻿/, '')

  for (let i = 0; i < input.length; i += 1) {
    const char = input[i]
    if (quoted) {
      if (char === '"') {
        if (input[i + 1] === '"') {
          field += '"'
          i += 1
        } else {
          quoted = false
        }
      } else {
        field += char
      }
      continue
    }
    if (char === '"' && field === '') {
      quoted = true
    } else if (char === delimiter) {
      row.push(field)
      field = ''
    } else if (char === '\r') {
      // 忽略 CR，兼容 CRLF
    } else if (char === '\n') {
      row.push(field)
      rows.push(row)
      row = []
      field = ''
      if (rows.length >= MAX_CSV_ROWS + 1) {
        truncated = true
        break
      }
    } else {
      field += char
    }
  }
  if (!truncated && (field !== '' || row.length > 0)) {
    row.push(field)
    rows.push(row)
  }
  return { rows, truncated }
}

const csvView = computed<CsvView | null>(() => {
  if (kind.value !== 'csv' || !text.value) return null
  const { rows, truncated } = parseDelimited(text.value, detectDelimiter(text.value))
  if (!rows.length) return null
  const columnCount = rows.reduce((max, row) => Math.max(max, row.length), 0)
  const visibleCols = Math.min(columnCount, MAX_CSV_COLS)
  const totalRows = rows.length
  // 统一补齐到相同列数，短行 / 短表头也能保持规整的表格网格。
  const pad = (row: string[]) =>
    Array.from({ length: visibleCols }, (_, index) => row[index] ?? '')
  return {
    header: pad(rows[0] ?? []),
    rows: rows.slice(1).map(pad),
    totalRows,
    columnCount,
    truncatedRows: truncated,
    truncatedCols: columnCount > MAX_CSV_COLS,
  }
})
</script>

<template>
  <div class="w-full" :class="isBlock ? 'max-h-[560px] overflow-auto' : 'h-full min-h-0'">
    <div
      v-if="isTextLike && textLoading"
      class="w-full grid place-items-center bg-white text-[12px] text-slate-400"
      :class="isBlock ? 'py-16' : 'h-full'"
    >
      载入中…
    </div>

    <div
      v-else-if="isTextLike && textError"
      class="w-full grid place-items-center bg-white"
      :class="isBlock ? 'py-16' : 'h-full'"
    >
      <div class="text-center px-6">
        <KiwiIcon name="file" :size="34" class="mx-auto text-slate-300" />
        <p class="mt-3 text-[12.5px] text-slate-500">{{ textError }}</p>
        <a :href="url" :download="filename" class="kiwi-btn-primary mt-4 !py-1.5 !text-xs">
          <KiwiIcon name="download" :size="13" />
          下载文件
        </a>
      </div>
    </div>

    <template v-else>
      <div v-if="kind === 'image'" class="w-full h-full grid place-items-center bg-slate-100 p-2">
        <img :src="url" :alt="filename" class="max-w-full max-h-full object-contain" />
      </div>

      <iframe
        v-else-if="kind === 'pdf'"
        :src="url"
        class="w-full h-full border-0"
        :title="filename"
      />

      <OfficeFilePreview
        v-else-if="kind === 'word' || kind === 'excel' || kind === 'ppt'"
        :url="url"
        :filename="filename"
        :content-type="contentType || ''"
        :fit="isBlock ? 'width' : 'contain'"
        large
      />

      <OpenDocumentFilePreview
        v-else-if="kind === 'odf'"
        :url="url"
        :filename="filename"
        :fit="isBlock ? 'block' : 'fill'"
      />

      <div v-else-if="kind === 'video'" class="w-full h-full grid place-items-center bg-black">
        <video :src="url" controls class="max-w-full max-h-full" />
      </div>

      <div v-else-if="kind === 'audio'" class="w-full h-full grid place-items-center bg-slate-50">
        <audio :src="url" controls class="w-[min(560px,86%)]" />
      </div>

      <!-- 网页：无同源权限的沙箱 iframe，脚本可运行但拿不到应用登录态。 -->
      <iframe
        v-else-if="kind === 'html'"
        :src="url"
        class="w-full border-0 bg-white"
        :class="isBlock ? 'h-[520px]' : 'h-full'"
        :title="filename"
        sandbox="allow-scripts allow-forms allow-popups allow-popups-to-escape-sandbox allow-modals allow-downloads"
        referrerpolicy="no-referrer"
      />

      <div
        v-else-if="kind === 'markdown'"
        class="w-full bg-white"
        :class="isBlock ? '' : 'h-full overflow-auto'"
      >
        <div class="prose-wiki md-file-preview px-6 py-5" v-html="markdownHtml" />
      </div>

      <div
        v-else-if="kind === 'json'"
        class="w-full flex flex-col bg-white"
        :class="isBlock ? '' : 'h-full'"
      >
        <div
          v-if="jsonParsed.ok"
          class="px-4 py-3"
          :class="isBlock ? '' : 'flex-1 min-h-0 overflow-auto'"
        >
          <JsonTree :value="jsonParsed.value" />
        </div>
        <div v-else :class="isBlock ? '' : 'flex-1 min-h-0 overflow-auto'">
          <p class="m-0 border-b border-amber-100 bg-amber-50/60 px-4 py-1.5 text-[10.5px] text-amber-700">
            不是合法的 JSON{{ textTruncated ? '（文件较大，已截断）' : '' }}，以下为原文
          </p>
          <pre class="m-0 p-4 text-[12px] leading-relaxed text-slate-700 whitespace-pre-wrap break-words">{{ text }}</pre>
        </div>
        <p
          v-if="textTruncated && jsonParsed.ok"
          class="shrink-0 border-t border-slate-200 bg-amber-50/60 px-4 py-1.5 text-[10.5px] text-amber-700"
        >
          文件较大，仅显示前 512 KB，可下载后查看完整内容。
        </p>
      </div>

      <div
        v-else-if="kind === 'csv'"
        class="w-full flex flex-col bg-white"
        :class="isBlock ? '' : 'h-full'"
      >
        <div v-if="csvView" :class="isBlock ? '' : 'flex-1 min-h-0 overflow-auto'">
          <table class="kiwi-file-table">
            <thead>
              <tr>
                <th class="kiwi-file-rownum">#</th>
                <th v-for="(cell, index) in csvView.header" :key="index">
                  {{ cell || `列 ${index + 1}` }}
                </th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(row, rowIndex) in csvView.rows" :key="rowIndex">
                <td class="kiwi-file-rownum">{{ rowIndex + 1 }}</td>
                <td v-for="(cell, cellIndex) in row" :key="cellIndex">{{ cell }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <p v-else class="m-auto text-[12px] text-slate-400">空表格</p>
        <p
          v-if="csvView && (csvView.truncatedRows || csvView.truncatedCols)"
          class="shrink-0 border-t border-slate-200 bg-amber-50/60 px-4 py-1.5 text-[10.5px] text-amber-700"
        >
          {{ csvView.truncatedRows ? `仅显示前 ${MAX_CSV_ROWS} 行` : '' }}
          {{ csvView.truncatedRows && csvView.truncatedCols ? '，' : '' }}
          {{ csvView.truncatedCols ? `仅显示前 ${MAX_CSV_COLS} 列（共 ${csvView.columnCount} 列）` : '' }}
          ，可下载后查看完整内容。
        </p>
      </div>

      <!-- YAML / TOML：解析为可折叠结构树 -->
      <div
        v-else-if="kind === 'yaml' || kind === 'toml'"
        class="w-full bg-white"
        :class="isBlock ? '' : 'h-full overflow-auto'"
      >
        <div v-if="structured.status === 'ok'" class="px-4 py-3">
          <JsonTree :value="structured.value" />
        </div>
        <div v-else-if="structured.status === 'error'">
          <p class="m-0 border-b border-amber-100 bg-amber-50/60 px-4 py-1.5 text-[10.5px] text-amber-700">
            {{ kind === 'yaml' ? 'YAML' : 'TOML' }} 解析失败（{{ structured.error }}），以下为原文
          </p>
          <pre class="m-0 p-4 text-[12px] leading-relaxed text-slate-700 whitespace-pre-wrap break-words">{{ text }}</pre>
        </div>
        <div
          v-else-if="structured.status === 'empty'"
          class="grid place-items-center py-16 text-[12px] text-slate-400"
        >
          文件为空
        </div>
        <div v-else class="grid place-items-center py-16 text-[12px] text-slate-400">解析中…</div>
      </div>

      <!-- XML：元素、属性与文本转为结构树 -->
      <div
        v-else-if="kind === 'xml'"
        class="w-full bg-white"
        :class="isBlock ? '' : 'h-full overflow-auto'"
      >
        <div v-if="xmlTree && !xmlTree.error" class="px-4 py-3">
          <JsonTree :value="xmlTree.value" />
        </div>
        <div v-else-if="xmlTree && xmlTree.error">
          <p class="m-0 border-b border-amber-100 bg-amber-50/60 px-4 py-1.5 text-[10.5px] text-amber-700">
            {{ xmlTree.error }}，以下为原文
          </p>
          <pre class="m-0 p-4 text-[12px] leading-relaxed text-slate-700 whitespace-pre-wrap break-words">{{ text }}</pre>
        </div>
        <div v-else-if="!text" class="grid place-items-center py-16 text-[12px] text-slate-400">
          文件为空
        </div>
        <div v-else class="grid place-items-center py-16 text-[12px] text-slate-400">解析中…</div>
      </div>

      <!-- JSON Lines：逐条记录折叠展示 -->
      <div
        v-else-if="kind === 'jsonl'"
        class="w-full bg-white"
        :class="isBlock ? '' : 'h-full overflow-auto'"
      >
        <template v-if="jsonlView && jsonlView.records.length">
          <p class="m-0 border-b border-slate-100 bg-slate-50/70 px-4 py-1.5 text-[10.5px] text-slate-500">
            共 {{ jsonlView.total }} 条记录
            <template v-if="jsonlView.total > jsonlView.shown">
              ，仅展示前 {{ jsonlView.shown }} 条
            </template>
          </p>
          <div class="divide-y divide-slate-100">
            <details
              v-for="record in jsonlView.records"
              :key="record.line"
              class="group"
            >
              <summary
                class="flex cursor-pointer list-none items-center gap-2 px-4 py-2 text-[12px] text-slate-600 hover:bg-slate-50"
              >
                <span class="w-8 shrink-0 text-right font-mono text-[10.5px] text-slate-400">
                  {{ record.line }}
                </span>
                <span class="truncate font-mono">
                  {{ record.error ? record.raw : jsonlPreview(record.value) }}
                </span>
                <span
                  v-if="record.error"
                  class="ml-auto shrink-0 rounded bg-rose-50 px-1.5 py-0.5 text-[10px] text-rose-600"
                >
                  JSON 解析失败
                </span>
              </summary>
              <div class="px-4 pb-3 pl-14">
                <JsonTree v-if="!record.error" :value="record.value" />
                <pre
                  v-else
                  class="m-0 text-[11.5px] leading-relaxed text-rose-700 whitespace-pre-wrap break-words"
                >{{ record.raw }}</pre>
              </div>
            </details>
          </div>
        </template>
        <p v-else class="m-auto text-[12px] text-slate-400">没有可显示的记录</p>
      </div>

      <!-- Jupyter Notebook：Markdown / 代码 / 输出 -->
      <NotebookFilePreview
        v-else-if="kind === 'ipynb'"
        :source="text"
        :fit="isBlock ? 'block' : 'fill'"
      />

      <!-- 差异文件：按新增 / 删除着色 -->
      <div
        v-else-if="kind === 'diff'"
        class="w-full bg-white"
        :class="isBlock ? '' : 'h-full overflow-auto'"
      >
        <div v-if="diffLines" class="min-w-max py-1 font-mono text-[11.5px] leading-[1.7]">
          <div
            v-for="row in diffLines"
            :key="row.line"
            class="diff-row"
            :class="`is-${row.type}`"
          >
            <span class="diff-lineno">{{ row.line }}</span>
            <span class="diff-text">{{ row.text || ' ' }}</span>
          </div>
        </div>
        <div v-else class="grid place-items-center py-16 text-[12px] text-slate-400">文件为空</div>
      </div>

      <!-- INI / ENV / properties：键值表 -->
      <div
        v-else-if="kind === 'config'"
        class="w-full bg-white"
        :class="isBlock ? '' : 'h-full overflow-auto'"
      >
        <table v-if="configView" class="kiwi-file-table">
          <thead>
            <tr>
              <th>分组</th>
              <th>键</th>
              <th>值</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(entry, index) in configView" :key="index">
              <td class="text-slate-400">{{ entry.section || '默认' }}</td>
              <td class="font-medium">{{ entry.key }}</td>
              <td class="font-mono">{{ entry.value }}</td>
            </tr>
          </tbody>
        </table>
        <pre
          v-else
          class="m-0 p-4 text-[12px] leading-relaxed text-slate-700 whitespace-pre-wrap break-words"
        >{{ text }}</pre>
      </div>

      <!-- 压缩包：文件目录清单 -->
      <div
        v-else-if="kind === 'archive'"
        class="w-full bg-white"
        :class="isBlock ? '' : 'h-full overflow-auto'"
      >
        <div v-if="archiveLoading" class="grid place-items-center py-16 text-[12px] text-slate-400">
          正在读取压缩包…
        </div>
        <div v-else-if="archiveError" class="w-full">
          <p class="m-0 border-b border-amber-100 bg-amber-50/60 px-4 py-1.5 text-[10.5px] text-amber-700">
            {{ archiveError }}
          </p>
          <div class="grid place-items-center py-12">
            <a :href="url" :download="filename" class="kiwi-btn-primary !py-1.5 !text-xs">
              <KiwiIcon name="download" :size="13" />
              下载压缩包
            </a>
          </div>
        </div>
        <template v-else>
          <p class="m-0 border-b border-slate-100 bg-slate-50/70 px-4 py-1.5 text-[10.5px] text-slate-500">
            共 {{ archiveEntries.length }} 项
            <template v-if="archiveTruncated">，仅展示前 {{ MAX_ARCHIVE_ENTRIES }} 项</template>
          </p>
          <ul v-if="archiveEntries.length" class="m-0 list-none p-0 py-1">
            <li
              v-for="entry in archiveEntries"
              :key="entry.path"
              class="flex items-center gap-2 pr-4 py-1 text-[12px] text-slate-600 hover:bg-slate-50"
              :style="{ paddingLeft: `${14 + entry.depth * 16}px` }"
            >
              <KiwiIcon
                :name="entry.dir ? 'folder' : 'file'"
                :size="13"
                :class="entry.dir ? 'text-amber-500' : 'text-slate-400'"
              />
              <span class="truncate" :class="entry.dir ? 'font-medium text-slate-700' : ''">
                {{ entry.name }}
              </span>
              <span v-if="!entry.dir && entry.size" class="ml-auto shrink-0 text-[10.5px] text-slate-400">
                {{ formatBytes(entry.size) }}
              </span>
            </li>
          </ul>
          <p v-else class="m-auto py-12 text-center text-[12px] text-slate-400">压缩包为空</p>
        </template>
      </div>

      <div
        v-else-if="kind === 'text'"
        class="w-full flex flex-col bg-white"
        :class="isBlock ? '' : 'h-full'"
      >
        <div :class="isBlock ? '' : 'flex-1 min-h-0 overflow-auto'">
          <pre class="m-0 p-5 text-[12px] leading-relaxed text-slate-700 whitespace-pre-wrap break-words">{{ text }}</pre>
        </div>
        <p
          v-if="textTruncated"
          class="shrink-0 border-t border-slate-200 bg-amber-50/60 px-5 py-1.5 text-[10.5px] text-amber-700"
        >
          文件较大，仅显示前 512 KB，可下载后查看完整内容。
        </p>
      </div>

      <div v-else class="w-full h-full grid place-items-center bg-slate-50">
        <div class="text-center px-6">
          <KiwiIcon name="file" :size="40" class="mx-auto text-slate-300" />
          <p class="mt-3 text-[13px] font-medium text-slate-600">{{ filename }}</p>
          <p class="mt-1 text-[11.5px] text-slate-400">
            {{
              ['doc', 'ppt'].includes(ext)
                ? '旧版 Office 格式（.doc / .ppt）暂不支持在线预览，请下载后使用本地应用打开。'
                : '该文件类型暂不支持在线预览，可下载后使用本地应用打开。'
            }}
          </p>
          <a
            :href="url"
            :download="filename"
            class="kiwi-btn-primary mt-4 !py-1.5 !text-xs"
          >
            <KiwiIcon name="download" :size="13" />
            下载文件
          </a>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.md-file-preview {
  max-width: 100%;
  font-size: 14px;
  line-height: 1.8;
  color: #334155;
}
.md-file-preview :deep(pre) {
  white-space: pre-wrap;
  word-break: break-word;
}
.md-file-preview :deep(img) {
  max-width: 100%;
  height: auto;
}
.md-file-preview :deep(table) {
  display: table;
  width: 100%;
}

.kiwi-file-table {
  border-collapse: collapse;
  width: max-content;
  min-width: 100%;
  font-size: 12px;
  color: #334155;
}
.kiwi-file-table th,
.kiwi-file-table td {
  border-right: 1px solid #eef2f6;
  border-bottom: 1px solid #eef2f6;
  padding: 6px 10px;
  text-align: left;
  vertical-align: top;
  white-space: pre-wrap;
  max-width: 420px;
  word-break: break-word;
}
.kiwi-file-table thead th {
  position: sticky;
  top: 0;
  z-index: 1;
  background: #f8fafc;
  color: #475569;
  font-weight: 600;
  white-space: nowrap;
}
.kiwi-file-table tbody tr:nth-child(even) {
  background: #fbfcfd;
}
.kiwi-file-table tbody tr:hover {
  background: rgb(var(--kiwi-50) / 0.6);
}
.kiwi-file-table .kiwi-file-rownum {
  position: sticky;
  left: 0;
  z-index: 1;
  width: 44px;
  min-width: 44px;
  background: #f8fafc;
  color: #94a3b8;
  text-align: right;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}
.kiwi-file-table thead .kiwi-file-rownum {
  z-index: 2;
}

/* 差异文件：新增 / 删除 / hunk 着色 */
.diff-row {
  display: flex;
  min-width: max-content;
}
.diff-lineno {
  flex: 0 0 auto;
  width: 46px;
  padding-right: 10px;
  text-align: right;
  color: #94a3b8;
  background: #f8fafc;
  border-right: 1px solid #eef2f6;
  font-variant-numeric: tabular-nums;
  user-select: none;
}
.diff-text {
  flex: 1 1 auto;
  padding: 0 12px;
  color: #334155;
  white-space: pre;
}
.diff-row.is-add {
  background: #ecfdf5;
}
.diff-row.is-add .diff-text {
  color: #166534;
}
.diff-row.is-add .diff-lineno {
  background: #d1fae5;
  color: #047857;
}
.diff-row.is-del {
  background: #fef2f2;
}
.diff-row.is-del .diff-text {
  color: #b91c1c;
}
.diff-row.is-del .diff-lineno {
  background: #fee2e2;
  color: #b91c1c;
}
.diff-row.is-hunk {
  background: #eff6ff;
}
.diff-row.is-hunk .diff-text {
  color: #1d4ed8;
}
.diff-row.is-meta .diff-text {
  color: #94a3b8;
}
</style>

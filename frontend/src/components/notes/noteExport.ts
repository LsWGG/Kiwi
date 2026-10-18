/**
 * 笔记导出：按笔记类型提供不同的导出格式，统一从目录树右键菜单触发。
 * 文档类走 Markdown / Word，Notebook 走 .ipynb / .py / .md，
 * 数据表导出 CSV / JSON，画布导出 SVG / 源文件。
 */
import { request } from '@/api/client'
import { downloadNoteDocx } from '@/components/editor/docx'
import type { DbField, DbRow } from '@/stores/noteDatabase'
import type { NoteOut, NoteSummary } from '@/stores/notes'
import { canvasDocToSvg } from './canvas/canvasSvgExport'
import { normalizeDoc } from './canvas/types'
import type { NotebookDoc } from './notebook/types'

export type ExportKey =
  | 'markdown'
  | 'docx'
  | 'ipynb'
  | 'python'
  | 'notebook-markdown'
  | 'csv'
  | 'xlsx'
  | 'database-json'
  | 'canvas-svg'
  | 'canvas-json'

export interface ExportAction {
  key: ExportKey
  label: string
  icon: string
  /** 显示在菜单右侧的扩展名 */
  ext: string
}

const DOC_ACTIONS: ExportAction[] = [
  { key: 'markdown', label: 'Markdown 文档', icon: 'fileText', ext: 'MD' },
  { key: 'docx', label: 'Word 文档', icon: 'file', ext: 'DOCX' },
]

const ACTIONS: Record<string, ExportAction[]> = {
  doc: DOC_ACTIONS,
  import: DOC_ACTIONS,
  link: DOC_ACTIONS,
  notebook: [
    { key: 'ipynb', label: 'Jupyter Notebook', icon: 'notebook', ext: 'IPYNB' },
    { key: 'python', label: 'Python 脚本', icon: 'code', ext: 'PY' },
    { key: 'notebook-markdown', label: 'Markdown 笔记', icon: 'fileText', ext: 'MD' },
  ],
  database: [
    { key: 'xlsx', label: 'Excel 表格', icon: 'table', ext: 'XLSX' },
    { key: 'csv', label: 'CSV 表格', icon: 'table', ext: 'CSV' },
    { key: 'database-json', label: 'JSON 数据', icon: 'code', ext: 'JSON' },
  ],
  canvas: [
    { key: 'canvas-svg', label: 'SVG 矢量图', icon: 'image', ext: 'SVG' },
    { key: 'canvas-json', label: '画布源文件', icon: 'code', ext: 'JSON' },
  ],
}

export function exportActionsFor(kind: string | null | undefined): ExportAction[] {
  return ACTIONS[kind ?? 'doc'] ?? DOC_ACTIONS
}

/** 去掉文件名中的非法字符，避免浏览器改写下载名。 */
export function safeFileName(title: string): string {
  const cleaned = (title || '无标题')
    .replace(/[\\/:*?"<>|\u0000-\u001f]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
  return cleaned || '无标题'
}

function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

function downloadText(text: string, filename: string, mime: string) {
  downloadBlob(new Blob([text], { type: `${mime};charset=utf-8` }), filename)
}

async function fetchNote(note: Pick<NoteSummary, 'id' | 'kb_id'>): Promise<NoteOut> {
  return request<NoteOut>(`/notes/${note.id}`, { kbId: note.kb_id })
}

function markdownDocument(note: NoteOut): string {
  const body = note.body_md || ''
  const title = note.title || '无标题'
  // 正文通常已由编辑器保存为完整 Markdown；仅在缺少同名标题时补一级标题。
  if (body.trimStart().startsWith(`# ${title}`)) return body
  return `# ${title}\n\n${body}`.trimEnd() + '\n'
}

function linkMarkdown(note: NoteOut): string {
  const base = markdownDocument(note)
  const url = String(note.props_json?.url ?? '')
  if (!url) return base
  return `${base.trimEnd()}\n\n---\n\n来源：[${url}](${url})\n`
}

interface NotebookCellLike {
  type?: string
  source?: string
  execution_count?: number | null
  outputs?: Array<{
    type?: string
    text?: string
    html?: string
    image?: { mime?: string; data?: string }
  }>
}

function notebookPython(note: NoteOut): string {
  const doc = (note.props_json?.notebook_doc ?? {}) as NotebookDoc
  const cells = Array.isArray(doc.cells) ? (doc.cells as NotebookCellLike[]) : []
  const parts: string[] = [
    '#!/usr/bin/env python3',
    '# -*- coding: utf-8 -*-',
    `"""${note.title || 'Notebook'} — 由 Kiwi Notebook 导出。"""`,
    '',
  ]
  for (const cell of cells) {
    const source = String(cell.source ?? '')
    if (cell.type === 'markdown') {
      parts.push('# %% [markdown]')
      for (const line of source.split('\n')) parts.push(line ? `# ${line}` : '#')
      parts.push('')
      continue
    }
    parts.push('# %%')
    parts.push(source.trimEnd(), '')
  }
  return parts.join('\n').trimEnd() + '\n'
}

function notebookMarkdown(note: NoteOut): string {
  const doc = (note.props_json?.notebook_doc ?? {}) as NotebookDoc
  const cells = Array.isArray(doc.cells) ? (doc.cells as NotebookCellLike[]) : []
  const parts: string[] = [`# ${note.title || 'Notebook'}`, '']
  for (const cell of cells) {
    const source = String(cell.source ?? '').trim()
    if (!source) continue
    if (cell.type === 'markdown') {
      parts.push(source, '')
      continue
    }
    parts.push('```python', source, '```', '')
    const outputs = Array.isArray(cell.outputs) ? cell.outputs : []
    for (const output of outputs) {
      if (output.type === 'error') {
        parts.push('```text', String(output.text ?? ''), '```', '')
      } else if (output.text) {
        parts.push('```text', String(output.text).trimEnd(), '```', '')
      } else if (output.image?.data) {
        parts.push('> 图片输出：请在 Kiwi 中查看或导出为 .ipynb。', '')
      }
    }
  }
  return parts.join('\n').trimEnd() + '\n'
}

interface DatabaseOut {
  fields: DbField[]
  views: unknown[]
}

function optionName(field: DbField, value: unknown): string {
  const options = Array.isArray(field.options) ? field.options : []
  if (field.type === 'multi_select') {
    const ids = Array.isArray(value) ? value : []
    return ids
      .map((id) => options.find((option) => option.id === id)?.name ?? String(id))
      .join(' / ')
  }
  return options.find((option) => option.id === value)?.name ?? String(value ?? '')
}

function cellText(field: DbField, value: unknown): string {
  if (value === null || value === undefined) return ''
  if (field.type === 'select') return optionName(field, value)
  if (field.type === 'multi_select') return optionName(field, value)
  if (field.type === 'checkbox') return value ? '是' : '否'
  if (field.type === 'attachment') {
    if (Array.isArray(value)) {
      return value
        .map((item: any) => item?.filename ?? item?.url ?? '')
        .filter(Boolean)
        .join(' / ')
    }
    return ''
  }
  return typeof value === 'object' ? JSON.stringify(value) : String(value)
}

function csvCell(value: string): string {
  if (!/[",\n\r]/.test(value)) return value
  return `"${value.replace(/"/g, '""')}"`
}

/** Excel 单元格：数字保持数值类型，其余转成可读文本。 */
function excelCell(field: DbField, value: unknown): string | number {
  if (value === null || value === undefined) return ''
  if (field.type === 'number' || field.type === 'rating') {
    const n = Number(value)
    return Number.isFinite(n) ? n : ''
  }
  return cellText(field, value)
}

/** Excel 工作表名：去掉非法字符并限制 31 字符。 */
function sheetName(title: string): string {
  const cleaned = (title || '数据表').replace(/[\\/:*?[\]"]/g, ' ').trim()
  return (cleaned || '数据表').slice(0, 31)
}

function displayWidth(text: string): number {
  return Array.from(text).reduce((sum, ch) => sum + (ch.charCodeAt(0) > 255 ? 2 : 1), 0)
}

async function exportDatabase(note: NoteOut, kind: 'xlsx' | 'csv' | 'json') {
  const [db, rows] = await Promise.all([
    request<DatabaseOut>(`/notes/${note.id}/database`, { kbId: note.kb_id }),
    request<DbRow[]>(`/notes/${note.id}/rows`, { kbId: note.kb_id }),
  ])
  const fields = Array.isArray(db.fields) ? db.fields : []
  const base = safeFileName(note.title)
  if (kind === 'xlsx') {
    const XLSX = await import('xlsx')
    const header = fields.map((field) => field.name)
    const body = rows.map((row) =>
      fields.map((field) => excelCell(field, row.data?.[field.id])),
    )
    const sheet = XLSX.utils.aoa_to_sheet([header, ...body])
    sheet['!cols'] = fields.map((field, index) => {
      const samples = [
        field.name,
        ...rows
          .slice(0, 200)
          .map((row) => cellText(field, row.data?.[field.id])),
      ]
      const width = Math.min(
        42,
        Math.max(9, ...samples.map((text) => displayWidth(String(text)) + 2)),
      )
      return { wch: width }
    })
    if (fields.length && rows.length) {
      sheet['!autofilter'] = {
        ref: XLSX.utils.encode_range({
          s: { r: 0, c: 0 },
          e: { r: rows.length, c: fields.length - 1 },
        }),
      }
    }
    const book = XLSX.utils.book_new()
    XLSX.utils.book_append_sheet(book, sheet, sheetName(note.title))
    const blob = new Blob([XLSX.write(book, { bookType: 'xlsx', type: 'array' })], {
      type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    })
    downloadBlob(blob, `${base}.xlsx`)
    return
  }
  if (kind === 'csv') {
    const header = fields.map((field) => csvCell(field.name)).join(',')
    const lines = rows.map((row) =>
      fields.map((field) => csvCell(cellText(field, row.data?.[field.id]))).join(','),
    )
    // BOM：保证 Excel 打开中文不乱码。
    downloadText(`﻿${[header, ...lines].join('\r\n')}\r\n`, `${base}.csv`, 'text/csv')
    return
  }
  const payload = {
    name: note.title,
    exported_at: new Date().toISOString(),
    fields: db.fields,
    views: db.views,
    rows: rows.map((row) => ({
      id: row.id,
      data: row.data,
      sort_order: row.sort_order,
      created_at: row.created_at,
      updated_at: row.updated_at,
    })),
  }
  downloadText(JSON.stringify(payload, null, 2), `${base}.json`, 'application/json')
}

async function exportNotebookFile(note: Pick<NoteSummary, 'id' | 'kb_id' | 'title'>) {
  const res = await fetch(
    `/api/notebooks/${note.id}/export?kb_id=${encodeURIComponent(note.kb_id)}`,
  )
  if (!res.ok) {
    const detail = await res.json().catch(() => null)
    throw new Error((detail as any)?.detail || res.statusText || '导出失败')
  }
  downloadBlob(await res.blob(), `${safeFileName(note.title)}.ipynb`)
}

/** 执行一次导出；调用方负责 toast 成功 / 失败提示。 */
export async function runNoteExport(
  note: Pick<NoteSummary, 'id' | 'kb_id' | 'title' | 'kind'>,
  key: ExportKey,
): Promise<void> {
  const base = safeFileName(note.title)
  if (key === 'docx') {
    await downloadNoteDocx(note.id, note.kb_id, note.title)
    return
  }
  if (key === 'ipynb') {
    await exportNotebookFile(note)
    return
  }
  const full = await fetchNote(note)
  switch (key) {
    case 'markdown':
      downloadText(
        note.kind === 'link' ? linkMarkdown(full) : markdownDocument(full),
        `${base}.md`,
        'text/markdown',
      )
      return
    case 'python':
      downloadText(notebookPython(full), `${base}.py`, 'text/x-python')
      return
    case 'notebook-markdown':
      downloadText(notebookMarkdown(full), `${base}.md`, 'text/markdown')
      return
    case 'csv':
    case 'xlsx':
    case 'database-json':
      await exportDatabase(
        full,
        key === 'csv' ? 'csv' : key === 'xlsx' ? 'xlsx' : 'json',
      )
      return
    case 'canvas-json':
      downloadText(
        JSON.stringify(full.props_json?.canvas_doc ?? normalizeDoc(null), null, 2),
        `${base}.canvas.json`,
        'application/json',
      )
      return
    case 'canvas-svg': {
      const doc = normalizeDoc(full.props_json?.canvas_doc)
      downloadText(canvasDocToSvg(doc), `${base}.svg`, 'image/svg+xml')
      return
    }
    default:
      throw new Error('不支持的导出格式')
  }
}

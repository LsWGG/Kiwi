/**
 * @ 提及 / 笔记预览共用的数据类型与加载、单元格格式化工具。
 *
 * 预览窗口需要按笔记类型读取不同字段：文档读正文，数据表额外拉取字段与记录，
 * Notebook / 表格读取 props_json 内的结构。这里集中一次，避免提及卡片与
 * 大屏预览各写一套。
 */
import { request } from '@/api/client'

export type NotePreviewKind =
  | 'doc'
  | 'database'
  | 'link'
  | 'import'
  | 'canvas'
  | 'notebook'
  | 'sheet'
  | 'wiki'

export interface NotePreviewLink {
  url?: string
  final_url?: string
  site?: string
  excerpt?: string
  fetch_status?: string
}

export interface NotePreviewOption {
  id: string
  name?: string
  label?: string
}

export interface NotePreviewField {
  id: string
  name: string
  type: string
  options?: NotePreviewOption[]
}

export interface NotePreviewRow {
  id: string
  data: Record<string, any>
}

export interface NotePreviewCell {
  type?: string
  source?: string
}

export interface NotePreviewSheetCell {
  v?: string | number | boolean | null
  f?: string
  cached?: string | number | boolean | null
  s?: { fmt?: string }
}

export interface NotePreviewSheet {
  id?: string
  name?: string
  rows?: number
  cols?: number
  active?: string
  cells?: Record<string, NotePreviewSheetCell>
}

export interface NotePreviewData {
  title: string
  body_md: string
  kind: NotePreviewKind
  link?: NotePreviewLink
  fields?: NotePreviewField[]
  rows?: NotePreviewRow[]
  notebook?: { cells?: NotePreviewCell[] }
  sheet?: { active?: string; sheets?: NotePreviewSheet[] }
}

interface NoteApiResponse extends Partial<NotePreviewData> {
  props_json?: Record<string, any> | null
}

/** 统一读取一篇笔记 / Wiki 页面的预览数据；数据表会并行拉取字段与记录。 */
export async function fetchNotePreview(
  kbId: string,
  id: string,
  target: 'note' | 'wiki' = 'note',
): Promise<NotePreviewData> {
  if (target === 'wiki') {
    const page = await request<{ title: string; body_md: string }>(`/wiki/${id}`, { kbId })
    return {
      title: page.title || '无标题',
      body_md: page.body_md || '',
      kind: 'wiki',
    }
  }

  const note = await request<NoteApiResponse>(`/notes/${id}`, { kbId })
  const data: NotePreviewData = {
    title: note.title || '无标题',
    body_md: note.body_md || '',
    kind: (note.kind as NotePreviewKind) || 'doc',
    link: note.props_json?.link as NotePreviewLink | undefined,
    notebook: note.props_json?.notebook_doc as NotePreviewData['notebook'],
    sheet: note.props_json?.sheet as NotePreviewData['sheet'],
  }
  if (data.kind === 'database') {
    const [database, rows] = await Promise.all([
      request<{ fields: NotePreviewField[] }>(`/notes/${id}/database`, { kbId }),
      request<NotePreviewRow[]>(`/notes/${id}/rows`, { kbId }),
    ])
    data.fields = Array.isArray(database?.fields) ? database.fields : []
    data.rows = Array.isArray(rows) ? rows : []
  }
  return data
}

export function optionLabel(field: NotePreviewField, raw: unknown): string {
  if (raw && typeof raw === 'object') {
    const option = raw as NotePreviewOption & Record<string, any>
    return String(
      option.name ?? option.label ?? option.filename ?? option.title ?? option.id ?? '',
    )
  }
  const id = String(raw ?? '')
  if (!id) return ''
  const option = field.options?.find((item) => item.id === id)
  return String(option?.name ?? option?.label ?? id)
}

export function attachmentsOf(
  row: NotePreviewRow,
  field: NotePreviewField,
): Record<string, any>[] {
  const value = row.data?.[field.id]
  if (!Array.isArray(value)) return []
  return value.filter((item) => item && typeof item === 'object')
}

export function databaseCellText(row: NotePreviewRow, field: NotePreviewField): string {
  const value = row.data?.[field.id]
  if (value === null || value === undefined || value === '') return '—'
  if (Array.isArray(value)) {
    const labels = value.map((item) => optionLabel(field, item)).filter(Boolean)
    return labels.length ? labels.join('、') : '—'
  }
  if (typeof value === 'boolean') return value ? '✓' : '—'
  if (field.type === 'progress') {
    const number = Number(value)
    return Number.isFinite(number)
      ? `${Math.max(0, Math.min(100, Math.round(number)))}%`
      : '—'
  }
  if (field.type === 'select' || field.type === 'multi_select') {
    return optionLabel(field, value) || '—'
  }
  if (typeof value === 'object') {
    return optionLabel(field, value) || JSON.stringify(value)
  }
  return String(value)
}

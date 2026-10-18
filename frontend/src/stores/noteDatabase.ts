import { defineStore } from 'pinia'
import { ref } from 'vue'
import { request } from '@/api/client'
import { useKbsStore } from './kbs'

export type FieldType =
  | 'text'
  | 'long_text'
  | 'number'
  | 'rating'
  | 'select'
  | 'multi_select'
  | 'date'
  | 'checkbox'
  | 'url'
  | 'attachment'

/** 数据表附件字段保存的文件元数据快照。 */
export interface DbAttachment {
  id?: string
  filename: string
  url: string
  content_type: string
  size: number
}

export interface SelectOption {
  id: string
  name: string
  color?: string
}

/** 表格筛选条件（同一视图内多个条件为 AND 关系）。 */
export interface DbFilter {
  id: string
  field: string
  op:
    | 'contains'
    | 'not_contains'
    | 'is'
    | 'is_not'
    | 'is_empty'
    | 'is_not_empty'
    | 'gt'
    | 'gte'
    | 'lt'
    | 'lte'
  value?: string | number | boolean | null
}

export interface DbSort {
  field: string
  direction: 'asc' | 'desc'
}

export interface DbField {
  id: string
  name: string
  type: FieldType
  options?: SelectOption[]
}

export type ViewType = 'table' | 'kanban' | 'gallery' | 'calendar'

export interface DbView {
  id: string
  name: string
  type: ViewType
  hidden_fields?: string[]
  group_field?: string | null
  /** 看板卡片展示字段；null 表示自动展示前两个 */
  display_fields?: string[] | null
  /** 表格列宽（字段 id → px） */
  column_widths?: Record<string, number>
  /** 表格行高（行 id → px） */
  row_heights?: Record<string, number>
  /** 表格筛选（AND） */
  filters?: DbFilter[]
  /** 表格排序（按数组顺序） */
  sorts?: DbSort[]
  date_field?: string | null
  /** 日历结束日期字段（可选），用于跨天横条 */
  end_field?: string | null
  title_field?: string | null
  cover_field?: string | null
  /** 日历横条颜色；null 表示按记录的单选字段自动配色 */
  bar_color?: string | null
}

export interface DbRow {
  id: string
  collection_id: string
  /** 每行对应的完整笔记 */
  note_id?: string | null
  data: Record<string, any>
  sort_order: number
  created_at: string
  updated_at: string
}

interface DatabaseOut {
  note_id: string
  name: string
  fields: DbField[]
  views: DbView[]
}

let seq = 0
export function newFieldId() {
  seq += 1
  return `f_${Date.now().toString(36)}_${seq}`
}

export function newViewId() {
  seq += 1
  return `v_${Date.now().toString(36)}_${seq}`
}

export const useNoteDatabaseStore = defineStore('noteDatabase', () => {
  const kbs = useKbsStore()
  const noteId = ref<string | null>(null)
  const name = ref('')
  const fields = ref<DbField[]>([])
  const views = ref<DbView[]>([])
  const rows = ref<DbRow[]>([])
  const loading = ref(false)
  const saving = ref(false)
  const error = ref<string | null>(null)

  async function load(id: string) {
    const kbId = kbs.currentKbId
    noteId.value = id
    loading.value = true
    error.value = null
    try {
      const [db, rowList] = await Promise.all([
        request<DatabaseOut>(`/notes/${id}/database`, { kbId }),
        request<DbRow[]>(`/notes/${id}/rows`, { kbId }),
      ])
      fields.value = db.fields
      views.value = db.views
      name.value = db.name
      rows.value = rowList
    } catch (e: any) {
      error.value = e.message
      throw e
    } finally {
      loading.value = false
    }
  }

  async function saveSchema(patch: { name?: string; fields?: DbField[]; views?: DbView[] }) {
    if (!noteId.value) return
    saving.value = true
    try {
      const db = await request<DatabaseOut>(`/notes/${noteId.value}/database`, {
        method: 'PATCH',
        kbId: kbs.currentKbId,
        body: JSON.stringify({
          name: patch.name,
          fields: patch.fields,
          views: patch.views,
        }),
      })
      fields.value = db.fields
      views.value = db.views
      name.value = db.name
      return db
    } finally {
      saving.value = false
    }
  }

  async function createRow(data: Record<string, any> = {}) {
    if (!noteId.value) throw new Error('数据表未加载')
    const row = await request<DbRow>(`/notes/${noteId.value}/rows`, {
      method: 'POST',
      kbId: kbs.currentKbId,
      body: JSON.stringify({ data }),
    })
    rows.value.push(row)
    return row
  }

  async function updateRow(id: string, data: Record<string, any>) {
    const row = rows.value.find((r) => r.id === id)
    const prev = row ? { ...row.data } : null
    if (row) row.data = { ...row.data, ...data }
    try {
      if (!noteId.value) throw new Error('数据表未加载')
      const fresh = await request<DbRow>(`/notes/${noteId.value}/rows/${id}`, {
        method: 'PATCH',
        kbId: kbs.currentKbId,
        body: JSON.stringify({ data }),
      })
      if (row) {
        row.data = fresh.data
        row.updated_at = fresh.updated_at
      }
      return fresh
    } catch (e) {
      if (row && prev) row.data = prev
      throw e
    }
  }

  /** 为选中的记录按需生成可编辑笔记；已生成过的行复用原笔记。 */
  async function generateRowNotes(ids: string[]) {
    if (!noteId.value || !ids.length) return []
    const result = await request<
      { row_id: string; note_id: string; title: string; created: boolean }[]
    >(`/notes/${noteId.value}/rows/notes`, {
      method: 'POST',
      kbId: kbs.currentKbId,
      body: JSON.stringify({ row_ids: ids }),
    })
    for (const item of result) {
      const row = rows.value.find((r) => r.id === item.row_id)
      if (row) row.note_id = item.note_id
    }
    return result
  }

  async function deleteRow(id: string) {
    if (!noteId.value) return
    const idx = rows.value.findIndex((r) => r.id === id)
    const removed = idx >= 0 ? rows.value[idx] : null
    if (idx >= 0) rows.value.splice(idx, 1)
    try {
      await request(`/notes/${noteId.value}/rows/${id}`, {
        method: 'DELETE',
        kbId: kbs.currentKbId,
      })
    } catch (e) {
      if (removed) rows.value.splice(idx, 0, removed)
      throw e
    }
  }

  async function deleteRows(ids: string[]) {
    if (!noteId.value || !ids.length) return
    const wanted = new Set(ids)
    const removed = rows.value.filter((r) => wanted.has(r.id))
    rows.value = rows.value.filter((r) => !wanted.has(r.id))
    try {
      await request<{ deleted: number }>(`/notes/${noteId.value}/rows/batch-delete`, {
        method: 'POST',
        kbId: kbs.currentKbId,
        body: JSON.stringify({ row_ids: ids }),
      })
    } catch (e) {
      // 失败回滚：按原顺序插回
      const current = rows.value
      const merged = [...current, ...removed].sort((a, b) => {
        if (a.sort_order !== b.sort_order) return a.sort_order - b.sort_order
        return a.created_at.localeCompare(b.created_at)
      })
      rows.value = merged
      throw e
    }
  }

  return {
    noteId,
    name,
    fields,
    views,
    rows,
    loading,
    saving,
    error,
    load,
    saveSchema,
    createRow,
    updateRow,
    generateRowNotes,
    deleteRow,
    deleteRows,
  }
})

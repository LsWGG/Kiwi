/**
 * 笔记编译资格：与后端 `services/compile_eligibility.py` 保持一致。
 *
 * - 数据表行笔记随所属数据表编译；
 * - 待办汇总由系统自动维护，不属于知识正文；
 * - 只读导入材料只是素材快照，需转为可编辑笔记后再编译；
 * - 其余文档 / 数据表 / 链接 / 导入 / 画布 / Notebook / 表格均可编译。
 */
import type { NoteSummary } from '@/stores/notes'

export type NoteCompileSkipReason = 'collection_row' | 'todo_hub' | 'readonly_import'

export const NOTE_COMPILE_SKIP_LABELS: Record<NoteCompileSkipReason, string> = {
  collection_row: '数据表行笔记随数据表一起编译',
  todo_hub: '待办汇总由系统自动维护，无需编译',
  readonly_import: '只读导入材料无需编译，可转为可编辑笔记后再编译',
}

function truthy(value: unknown): boolean {
  if (typeof value === 'boolean') return value
  if (typeof value === 'string') return ['true', '1', 'yes'].includes(value.trim().toLowerCase())
  return Boolean(value)
}

export function noteCompileSkipReason(
  note: Pick<NoteSummary, 'props_json'>,
): NoteCompileSkipReason | null {
  const props = note.props_json || {}
  if (props.collection_row_id) return 'collection_row'
  if (truthy(props.todo_hub)) return 'todo_hub'
  if (truthy(props.readonly)) return 'readonly_import'
  const meta = props.import
  if (meta && typeof meta === 'object' && truthy(meta.readonly)) return 'readonly_import'
  return null
}

export function noteCompileEligible(note: Pick<NoteSummary, 'props_json'>): boolean {
  return noteCompileSkipReason(note) === null
}

export function noteCompileSkipLabel(
  note: Pick<NoteSummary, 'props_json'>,
): string | null {
  const reason = noteCompileSkipReason(note)
  return reason ? NOTE_COMPILE_SKIP_LABELS[reason] : null
}

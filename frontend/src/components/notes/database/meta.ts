/** 字段类型元信息。 */
import type { FieldType } from '@/stores/noteDatabase'

export interface FieldTypeMeta {
  type: FieldType
  label: string
  icon: string
}

export const FIELD_TYPES: FieldTypeMeta[] = [
  { type: 'text', label: '文本', icon: 'file' },
  { type: 'long_text', label: '多行文本', icon: 'alignLeft' },
  { type: 'number', label: '数字', icon: 'hash' },
  { type: 'rating', label: '评分', icon: 'star' },
  { type: 'select', label: '单选', icon: 'chevron' },
  { type: 'multi_select', label: '多选', icon: 'list' },
  { type: 'date', label: '日期', icon: 'calendar' },
  { type: 'checkbox', label: '复选框', icon: 'checkSquare' },
  { type: 'url', label: '链接', icon: 'link2' },
  { type: 'attachment', label: '附件', icon: 'paperclip' },
]

export function fieldTypeMeta(type: FieldType): FieldTypeMeta {
  return FIELD_TYPES.find((f) => f.type === type) ?? FIELD_TYPES[0]
}

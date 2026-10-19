/**
 * 多级有序列表编号预设（参考 WPS「多级编号」）。
 * 样式通过 CSS 计数器在渲染层生效，笔记只持久化预设 key，
 * 这样 Markdown 往返不会丢失编号格式，也不污染正文源码。
 */
export type OrderedListStyleKey =
  | 'decimal'
  | 'cn'
  | 'cn-circled'
  | 'decimal-cn'
  | 'paren'
  | 'roman'

export interface OrderedListStylePreset {
  key: OrderedListStyleKey
  label: string
  /** 第 1~4 级示例，用于菜单内直观对比 */
  sample: [string, string, string, string]
}

export const DEFAULT_ORDERED_LIST_STYLE: OrderedListStyleKey = 'decimal'

export const ORDERED_LIST_STYLE_PRESETS: OrderedListStylePreset[] = [
  {
    key: 'decimal',
    label: '数字层级',
    sample: ['1.', '1.1', '1.1.1', '1.1.1.1'],
  },
  {
    key: 'cn',
    label: '中文层级',
    sample: ['一、', '（一）', '1.', '（1）'],
  },
  {
    key: 'cn-circled',
    label: '中文带圈',
    sample: ['一、', '（一）', '①', '（1）'],
  },
  {
    key: 'decimal-cn',
    label: '数字带圈',
    sample: ['1、', '（1）', '①', 'a.'],
  },
  {
    key: 'paren',
    label: '括号层级',
    sample: ['（1）', '1）', 'a）', 'i）'],
  },
  {
    key: 'roman',
    label: '罗马层级',
    sample: ['I.', 'A.', '1.', 'a)'],
  },
]

const KEYS = new Set<string>(ORDERED_LIST_STYLE_PRESETS.map((item) => item.key))

export function resolveOrderedListStyle(value: unknown): OrderedListStyleKey {
  return typeof value === 'string' && KEYS.has(value)
    ? (value as OrderedListStyleKey)
    : DEFAULT_ORDERED_LIST_STYLE
}

/** 默认数字层级沿用原有计数器样式，无需额外 class。 */
export function orderedListStyleClass(value: unknown): string {
  const key = resolveOrderedListStyle(value)
  return key === DEFAULT_ORDERED_LIST_STYLE ? '' : `kiwi-ol-${key}`
}

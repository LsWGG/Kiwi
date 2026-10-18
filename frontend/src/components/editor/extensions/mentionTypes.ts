/** @ 提及的展示方式：行内提及 / 独占一行的大卡片 / 嵌入笔记正文。 */
export type MentionDisplay = 'mention' | 'card' | 'embed'

export function normalizeMentionDisplay(value: unknown): MentionDisplay {
  if (value === 'card' || value === 'embed') return value
  // 旧版本的「标题链接」已并入 @ 提及
  return 'mention'
}

export function mentionText(display: MentionDisplay, label: string): string {
  return display === 'mention' ? `@${label}` : label
}

export const MENTION_DISPLAY_OPTIONS: {
  id: MentionDisplay
  label: string
  hint: string
}[] = [
  { id: 'mention', label: '@ 提及', hint: '@标题' },
  { id: 'card', label: '内容卡片', hint: '标题 + 摘要' },
  { id: 'embed', label: '嵌入', hint: '正文预览' },
]

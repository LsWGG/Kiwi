/** @ 提及的展示方式：行内提及 / 标题超链接 / 独占一行的内容卡片 / 嵌入笔记正文。 */
export type MentionDisplay = 'mention' | 'title' | 'card' | 'embed'

export function normalizeMentionDisplay(value: unknown): MentionDisplay {
  if (value === 'title' || value === 'card' || value === 'embed') return value
  // 旧版本的「标题链接」曾并入 @ 提及；新数据用 display=title 还原为超链接。
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
  { id: 'title', label: '标题超链接', hint: '只显示标题' },
  { id: 'card', label: '内容卡片', hint: '标题 + 摘要' },
  { id: 'embed', label: '嵌入正文', hint: '完整内容' },
]

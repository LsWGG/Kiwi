/**
 * 标签配色：同一笔记内按顺序取色，保证相邻标签颜色不同。
 *
 * 这里是**内容色**（用户标签），不随主题强调色变化；色调由 main.css 的
 * `.content-tone` / `.tone-*` 定义，亮暗主题各自取可读的明度。
 */
export const TAG_PALETTE = [
  'content-tone tone-blue',
  'content-tone tone-green',
  'content-tone tone-amber',
  'content-tone tone-violet',
  'content-tone tone-rose',
  'content-tone tone-cyan',
  'content-tone tone-indigo',
  'content-tone tone-teal',
]

export const TAG_CHIP_BASE =
  'inline-flex items-center rounded-full border px-1.5 font-medium leading-none'

export function tagChipClass(index: number) {
  return `${TAG_CHIP_BASE} ${TAG_PALETTE[index % TAG_PALETTE.length]}`
}

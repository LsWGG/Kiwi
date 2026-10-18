/** 标签配色：同一笔记内按顺序取色，保证相邻标签颜色不同。 */
export const TAG_PALETTE = [
  'border-sky-200/70 bg-sky-50 text-sky-700',
  'border-emerald-200/70 bg-emerald-50 text-emerald-700',
  'border-amber-200/70 bg-amber-50 text-amber-700',
  'border-violet-200/70 bg-violet-50 text-violet-700',
  'border-rose-200/70 bg-rose-50 text-rose-700',
  'border-cyan-200/70 bg-cyan-50 text-cyan-700',
  'border-indigo-200/70 bg-indigo-50 text-indigo-700',
  'border-teal-200/70 bg-teal-50 text-teal-700',
]

export const TAG_CHIP_BASE =
  'inline-flex items-center rounded-full border px-1.5 font-medium leading-none'

export function tagChipClass(index: number) {
  return `${TAG_CHIP_BASE} ${TAG_PALETTE[index % TAG_PALETTE.length]}`
}

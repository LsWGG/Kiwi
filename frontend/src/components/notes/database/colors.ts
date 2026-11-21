/**
 * 选项配色（与后端存储的 color 字符串对应）。
 *
 * 选项颜色是**内容色**：用户给字段选项挑的颜色，跨主题保持同一色相，
 * 由 main.css 的 `.content-tone` / `.tone-*` 在亮暗主题下取可读明度。
 * 灰色选项使用中性的主题表面色，跟随主题中性色板。
 */
const TONE: Record<string, string> = {
  blue: 'tone-blue',
  green: 'tone-green',
  amber: 'tone-amber',
  rose: 'tone-rose',
  violet: 'tone-violet',
  cyan: 'tone-cyan',
  orange: 'tone-orange',
}

const CHIP: Record<string, string> = {
  slate: 'bg-slate-100 text-slate-600 border-slate-200/70',
}

for (const color of Object.keys(TONE)) {
  CHIP[color] = `content-tone ${TONE[color]}`
}

const DOT: Record<string, string> = {
  slate: 'bg-slate-400',
}

for (const color of Object.keys(TONE)) {
  DOT[color] = `content-tone--dot ${TONE[color]}`
}

const RING: Record<string, string> = {
  slate: 'border-slate-300',
}

for (const color of Object.keys(TONE)) {
  RING[color] = `content-tone--ring ${TONE[color]}`
}

export const OPTION_COLORS = [
  'slate',
  'blue',
  'green',
  'amber',
  'rose',
  'violet',
  'cyan',
  'orange',
] as const

export function chipClass(color?: string): string {
  return CHIP[color ?? ''] ?? 'bg-kiwi-50 text-kiwi-600 border-kiwi-200/70'
}
export function dotClass(color?: string): string {
  return DOT[color ?? ''] ?? 'bg-kiwi-400'
}
export function ringClass(color?: string): string {
  return RING[color ?? ''] ?? 'border-kiwi-300'
}

/** 选项配色（与后端存储的 color 字符串对应）。 */
const CHIP: Record<string, string> = {
  slate: 'bg-slate-100 text-slate-600 border-slate-200/70',
  blue: 'bg-sky-50 text-sky-600 border-sky-200/70',
  green: 'bg-emerald-50 text-emerald-600 border-emerald-200/70',
  amber: 'bg-amber-50 text-amber-600 border-amber-200/70',
  rose: 'bg-rose-50 text-rose-600 border-rose-200/70',
  violet: 'bg-violet-50 text-violet-600 border-violet-200/70',
  cyan: 'bg-cyan-50 text-cyan-600 border-cyan-200/70',
  orange: 'bg-orange-50 text-orange-600 border-orange-200/70',
}

const DOT: Record<string, string> = {
  slate: 'bg-slate-400',
  blue: 'bg-sky-400',
  green: 'bg-emerald-400',
  amber: 'bg-amber-400',
  rose: 'bg-rose-400',
  violet: 'bg-violet-400',
  cyan: 'bg-cyan-400',
  orange: 'bg-orange-400',
}

const RING: Record<string, string> = {
  slate: 'border-slate-300',
  blue: 'border-sky-300',
  green: 'border-emerald-300',
  amber: 'border-amber-300',
  rose: 'border-rose-300',
  violet: 'border-violet-300',
  cyan: 'border-cyan-300',
  orange: 'border-orange-300',
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

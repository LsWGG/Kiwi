/**
 * 生成 src/lib/emojiShortcodeMap.ts。
 *
 * `@tiptap/extension-emoji` 的 emojis 数据集约 500KB（含标签、关键词），
 * 而阅读视图只需要「短代码 → 表情字符」这一张表。生成紧凑映射可以避免
 * 每个打开阅读模式 / Wiki 页面的用户都下载完整表情库。
 *
 * 用法：npm run gen:emoji-shortcodes
 */
import { writeFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { emojis } from '@tiptap/extension-emoji'

const map = {}
for (const item of emojis) {
  if (!item.emoji) continue
  const names = item.shortcodes?.length ? item.shortcodes : [item.name]
  for (const name of names) map[name.toLowerCase()] = item.emoji
}

const sorted = Object.fromEntries(Object.entries(map).sort(([a], [b]) => a.localeCompare(b)))
const target = resolve(dirname(fileURLToPath(import.meta.url)), '../src/lib/emojiShortcodeMap.ts')
writeFileSync(
  target,
  '// 由 scripts/generate-emoji-shortcodes.mjs 生成，请勿手动编辑。\n' +
    '// 来源：@tiptap/extension-emoji → emojibase 短代码表。\n' +
    `export const EMOJI_SHORTCODES: Record<string, string> = ${JSON.stringify(sorted)}\n`,
)
console.log(`已生成 ${Object.keys(sorted).length} 条短代码 → ${target}`)

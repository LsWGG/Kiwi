/**
 * Emoji 短代码（`:frame_with_picture:`、`:smile:` 等）→ 原生 emoji 字符。
 *
 * Notion / 语雀 / GitHub 导出的 Markdown 常带短代码；编辑器和阅读视图
 * 都按文本渲染，不转换就会直接显示成冒号包裹的英文名。这里只处理普通
 * 文本 token，代码块与行内代码保持原样。
 */
import { EMOJI_SHORTCODES } from './emojiShortcodeMap'

const SHORTCODE_PATTERN = /:([a-z0-9_+-]+):/gi

export function replaceEmojiShortcodes(text: string): string {
  if (!text.includes(':')) return text
  return text.replace(
    SHORTCODE_PATTERN,
    (match, name: string) => EMOJI_SHORTCODES[name.toLowerCase()] ?? match,
  )
}

/** 在 markdown-it 的 inline 解析之后替换文本 token 里的短代码。 */
export function installEmojiShortcodeRule(markdownit: any) {
  if (markdownit.__kiwiEmojiShortcodes) return
  markdownit.__kiwiEmojiShortcodes = true
  markdownit.core.ruler.after('inline', 'kiwi_emoji_shortcodes', (state: any) => {
    for (const block of state.tokens) {
      if (block.type !== 'inline' || !Array.isArray(block.children)) continue
      for (const child of block.children) {
        if (child.type !== 'text' || typeof child.content !== 'string') continue
        child.content = replaceEmojiShortcodes(child.content)
      }
    }
  })
}

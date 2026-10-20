/**
 * 图片注解归一化。
 *
 * 历史文档里存在两种图注写法：
 * 1. `![alt](src "图 1：说明")` —— 图注写在 Markdown title 中；
 * 2. 图片后单独一段 `图 1：说明。` —— 图注被当成正文段落。
 *
 * 第二种写法在编辑态、阅读态与分屏预览里的字号 / 间距都不一致。这里在
 * markdown-it 解析阶段把「图片段落 + 紧随其后的图注段落」折叠成图片 title，
 * 让所有渲染入口共用同一种图注结构；文档在下次保存时也会自然变成规范写法。
 */

/** 图注段落：`图 1：…`、`图 2.1：…`、`Figure 3: …`。 */
export const IMAGE_CAPTION_RE =
  /^(?:图|Figure|Fig\.?)\s*\d+(?:\s*[.．\-–—]\s*\d+)*\s*[：:]\s*\S/i

function normalizeCaption(text: string): string {
  return text.trim().replace(/[。.．]\s*$/, '')
}

function isImageOnlyParagraph(token: any): any | null {
  if (token?.type !== 'inline' || !Array.isArray(token.children)) return null
  if (token.children.length !== 1) return null
  const only = token.children[0]
  if (only?.type !== 'image' || !only.attrGet('src')) return null
  return only
}

function isCaptionParagraph(token: any): string | null {
  if (token?.type !== 'inline') return null
  const text = String(token.content || '').trim()
  return IMAGE_CAPTION_RE.test(text) ? normalizeCaption(text) : null
}

/**
 * markdown-it core rule：把图片后的独立图注段落并入前一张图片的 title。
 *
 * 只处理「独占一段的图片」，且图注必须紧跟在图片段落之后，避免误吞正文。
 * 原图已有 title 时保留 title，但移除重复的图注段落。
 */
export function foldImageCaptionTokens(state: any): void {
  const tokens: any[] = Array.isArray(state?.tokens) ? state.tokens : []
  for (let index = 0; index < tokens.length - 5; index += 1) {
    const image = isImageOnlyParagraph(tokens[index])
    if (!image) continue
    if (tokens[index + 1]?.type !== 'paragraph_close') continue
    if (tokens[index + 2]?.type !== 'paragraph_open') continue
    const caption = isCaptionParagraph(tokens[index + 3])
    if (!caption) continue
    if (tokens[index + 4]?.type !== 'paragraph_close') continue

    if (!image.attrGet('title')) image.attrSet('title', caption)
    tokens.splice(index + 2, 3)
  }
}

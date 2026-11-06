/**
 * 识别剪贴板中的 Markdown 源码。
 *
 * tiptap-markdown 自带的粘贴转换使用 inline 解析，整段 Markdown 源码里的
 * 标题、列表、代码围栏会被当成普通文字。这里只负责判断「像不像一份
 * Markdown 文档」，命中后由编辑器改用块级解析。
 */

const BLOCK_HINTS: RegExp[] = [
  // ATX 标题
  /^ {0,3}#{1,6}[ \t]+\S/m,
  // 代码围栏
  /^ {0,3}(?:```|~~~)[^\n]*$/m,
  // 引用块
  /^ {0,3}>\s+\S/m,
  // 任务列表
  /^ {0,3}(?:[-*+]|\d+[.)])\s+\[[ xX]\]\s+\S/m,
  // 表格分隔行（|---|:---:|）
  /^[ \t]*\|?[ \t:|-]*-[ \t:|-]*\|[ \t:|-]*$/m,
  // 分隔线
  /^ {0,3}([-*_])(?:[ \t]*\1){2,}[ \t]*$/m,
]

const LIST_LINE = /^ {0,3}(?:[-*+]|\d+[.)])\s+\S/

/** 纯文本剪贴板内容是否值得按块级 Markdown 解析。 */
export function looksLikeMarkdownSource(text: string): boolean {
  const source = text.replace(/\r\n?/g, '\n').trim()
  if (!source) return false
  if (BLOCK_HINTS.some((pattern) => pattern.test(source))) return true
  // 至少两项连续列表才当作 Markdown，避免把普通的一句「- 说明」误判。
  const listLines = source.split('\n').filter((line) => LIST_LINE.test(line)).length
  if (listLines >= 2) return true
  // 独立成段的图片语法通常来自 Markdown 源码。
  return /!\[[^\]]*\]\([^)\s]+(?:\s+"[^"]*")?\)/.test(source)
}

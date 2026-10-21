/**
 * 空待办（`- [ ]`，复选框后没有正文）在 markdown-it 里的兼容处理。
 *
 * `markdown-it-task-lists` 只识别 `[ ] `（带尾随空格）形式的标记，
 * 裸 `- [ ]` 会被当成普通列表项，正文变成字面量 `[ ]`。编辑器保存后
 * 再打开，空待办就消失了。解析前给这类标记补一个空格，让它走正常
 * 的任务列表分支；写入 Markdown 时序列化器仍会输出 `- [ ]`。
 */
export function enableEmptyTaskItems(markdownit: {
  core: { ruler: { before: (name: string, rule: string, fn: (state: any) => void) => void } }
}) {
  markdownit.core.ruler.before('github-task-lists', 'kiwi_empty_task_items', (state: any) => {
    const tokens = state.tokens
    for (let i = 2; i < tokens.length; i += 1) {
      const token = tokens[i]
      if (token.type !== 'inline' || !/^\[[ xX]\]$/.test(token.content)) continue
      if (tokens[i - 1]?.type !== 'paragraph_open') continue
      if (tokens[i - 2]?.type !== 'list_item_open') continue
      token.content += ' '
      const children = token.children
      const last = children?.[children.length - 1]
      if (last?.type === 'text') last.content += ' '
    }
  })
}

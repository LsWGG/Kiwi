/**
 * 任务列表：在默认 TaskList 基础上修复「空待办」的 Markdown 往返。
 *
 * tiptap-markdown 自带的 TaskList 解析只调用 markdown-it-task-lists，
 * 而该插件不认没有正文的 `- [ ]`。这里补上解析前的兼容规则，并保留
 * 默认的 `contains-task-list` → `data-type="taskList"` 标记。
 */
import TaskList from '@tiptap/extension-task-list'
import taskListPlugin from 'markdown-it-task-lists'
import { enableEmptyTaskItems } from '@/lib/markdownTaskItems'

export const KiwiTaskList = TaskList.extend({
  addStorage() {
    return {
      markdown: {
        parse: {
          setup(markdownit: any) {
            markdownit.use(taskListPlugin)
            enableEmptyTaskItems(markdownit)
          },
          updateDOM(element: HTMLElement) {
            element.querySelectorAll('.contains-task-list').forEach((list) => {
              list.setAttribute('data-type', 'taskList')
            })
          },
        },
      },
    }
  },
})

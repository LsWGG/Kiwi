<script setup lang="ts">
/**
 * 插件宿主的轻量富文本编辑器。
 *
 * 组件插件（时间轴等）需要「和文本笔记一样」的内容编辑能力：标题、加粗、
 * 列表、引用、代码与待办勾选框。内容统一以 Markdown 保存（`v-model`），
 * 与笔记正文、只读渲染保持一致；阅读态复用同一套 ProseMirror schema，
 * 只把编辑能力关掉。
 */
import { onBeforeUnmount, ref, watch } from 'vue'
import type { Editor } from '@tiptap/core'
import { EditorContent, useEditor } from '@tiptap/vue-3'
import StarterKit from '@tiptap/starter-kit'
import TaskList from '@tiptap/extension-task-list'
import TaskItem from '@tiptap/extension-task-item'
import Placeholder from '@tiptap/extension-placeholder'
import Underline from '@tiptap/extension-underline'
import { Markdown } from 'tiptap-markdown'

interface ToolbarAction {
  key: string
  label: string
  glyph: string
  command: (editor: Editor) => void
  active?: (editor: Editor) => boolean
}

const props = withDefaults(
  defineProps<{
    modelValue?: string
    readonly?: boolean
    placeholder?: string
    minHeight?: string
  }>(),
  {
    modelValue: '',
    readonly: false,
    placeholder: '开始记录…',
    minHeight: '72px',
  },
)

const emit = defineEmits<{ 'update:modelValue': [value: string] }>()

const TOOLBAR: ToolbarAction[] = [
  {
    key: 'bold',
    label: '加粗',
    glyph: 'B',
    command: (editor) => editor.chain().focus().toggleBold().run(),
    active: (editor) => editor.isActive('bold'),
  },
  {
    key: 'italic',
    label: '斜体',
    glyph: 'I',
    command: (editor) => editor.chain().focus().toggleItalic().run(),
    active: (editor) => editor.isActive('italic'),
  },
  {
    key: 'underline',
    label: '下划线',
    glyph: 'U',
    command: (editor) => editor.chain().focus().toggleUnderline().run(),
    active: (editor) => editor.isActive('underline'),
  },
  {
    key: 'strike',
    label: '删除线',
    glyph: 'S',
    command: (editor) => editor.chain().focus().toggleStrike().run(),
    active: (editor) => editor.isActive('strike'),
  },
  {
    key: 'heading',
    label: '标题',
    glyph: 'H2',
    command: (editor) => editor.chain().focus().toggleHeading({ level: 2 }).run(),
    active: (editor) => editor.isActive('heading', { level: 2 }),
  },
  {
    key: 'blockquote',
    label: '引用',
    glyph: '❝',
    command: (editor) => editor.chain().focus().toggleBlockquote().run(),
    active: (editor) => editor.isActive('blockquote'),
  },
  {
    key: 'code',
    label: '行内代码',
    glyph: '</>',
    command: (editor) => editor.chain().focus().toggleCode().run(),
    active: (editor) => editor.isActive('code'),
  },
  {
    key: 'bulletList',
    label: '无序列表',
    glyph: '•',
    command: (editor) => editor.chain().focus().toggleBulletList().run(),
    active: (editor) => editor.isActive('bulletList'),
  },
  {
    key: 'orderedList',
    label: '有序列表',
    glyph: '1.',
    command: (editor) => editor.chain().focus().toggleOrderedList().run(),
    active: (editor) => editor.isActive('orderedList'),
  },
  {
    key: 'taskList',
    label: '勾选框',
    glyph: '☑',
    command: (editor) => editor.chain().focus().toggleTaskList().run(),
    active: (editor) => editor.isActive('taskList'),
  },
  {
    key: 'undo',
    label: '撤销',
    glyph: '↶',
    command: (editor) => editor.chain().focus().undo().run(),
  },
  {
    key: 'redo',
    label: '重做',
    glyph: '↷',
    command: (editor) => editor.chain().focus().redo().run(),
  },
]

const stateTick = ref(0)
let emitTimer: number | undefined
let lastEmitted = props.modelValue ?? ''

function getMarkdown(editor: Editor): string {
  return String((editor.storage as any).markdown?.getMarkdown?.() ?? '')
}

function flushEmit(editor?: Editor) {
  if (emitTimer !== undefined) {
    window.clearTimeout(emitTimer)
    emitTimer = undefined
  }
  if (!editor) return
  const value = getMarkdown(editor)
  if (value === lastEmitted) return
  lastEmitted = value
  emit('update:modelValue', value)
}

function scheduleEmit() {
  if (emitTimer !== undefined) window.clearTimeout(emitTimer)
  // 输入时先让本地编辑器保持完整状态，停手后再写回区块 props，
  // 避免每次按键都触发外层笔记事务与自动保存。
  emitTimer = window.setTimeout(() => {
    emitTimer = undefined
    flushEmit(editorRef.value)
  }, 300)
}

function runAction(action: ToolbarAction) {
  const editor = editorRef.value
  if (!editor || props.readonly) return
  action.command(editor)
}

function actionActive(action: ToolbarAction): boolean {
  // 读取 tick，让工具栏在选区 / 格式变化后重新求值。
  void stateTick.value
  const editor = editorRef.value
  return !!editor && !!action.active?.(editor)
}

function actionDisabled(action: ToolbarAction): boolean {
  void stateTick.value
  const editor = editorRef.value
  if (!editor || props.readonly) return true
  if (action.key === 'undo') return !editor.can().undo()
  if (action.key === 'redo') return !editor.can().redo()
  return false
}

const editorRef = useEditor({
  content: props.modelValue,
  editable: !props.readonly,
  extensions: [
    StarterKit,
    Underline,
    TaskList,
    TaskItem.configure({ nested: true }),
    Placeholder.configure({ placeholder: props.placeholder }),
    Markdown.configure({
      // 粘贴 / 导入的 Markdown 按结构解析成富文本；未知 HTML 仍会被
      // ProseMirror schema 丢弃，不会把脚本带进笔记。
      html: true,
      tightLists: true,
      linkify: false,
      breaks: false,
      transformPastedText: true,
      transformCopiedText: true,
    }),
  ],
  editorProps: {
    attributes: {
      class: 'kiwi-plugin-note-editor__prosemirror',
      spellcheck: 'false',
    },
  },
  onUpdate: scheduleEmit,
  onTransaction: () => {
    stateTick.value += 1
  },
  onBlur: ({ editor }) => flushEmit(editor),
})

watch(
  () => props.modelValue,
  (value) => {
    const editor = editorRef.value
    if (!editor) return
    const next = String(value ?? '')
    if (next === getMarkdown(editor)) {
      lastEmitted = next
      return
    }
    lastEmitted = next
    editor.commands.setContent(next, false)
  },
)

watch(
  () => props.readonly,
  (value) => {
    editorRef.value?.setEditable(!value)
  },
)

onBeforeUnmount(() => {
  if (emitTimer !== undefined) window.clearTimeout(emitTimer)
})
</script>

<template>
  <div
    class="kiwi-plugin-note-editor"
    :class="{ 'is-readonly': readonly }"
    :aria-readonly="readonly"
  >
    <div
      v-if="editorRef && !readonly"
      class="kiwi-plugin-note-editor__toolbar"
      role="toolbar"
      aria-label="笔记格式"
    >
      <button
        v-for="action in TOOLBAR"
        :key="action.key"
        type="button"
        class="kiwi-plugin-note-editor__tool"
        :class="[
          `is-${action.key}`,
          { 'is-active': actionActive(action) },
        ]"
        :title="action.label"
        :aria-label="action.label"
        :aria-pressed="action.active ? actionActive(action) : undefined"
        :disabled="actionDisabled(action)"
        @mousedown.prevent
        @click.stop="runAction(action)"
      >
        {{ action.glyph }}
      </button>
    </div>
    <div
      class="kiwi-plugin-note-editor__body"
      :style="readonly ? undefined : { '--kiwi-plugin-note-min-height': minHeight }"
      @mousedown.stop
      @click.stop
      @keydown.stop
      @keyup.stop
      @beforeinput.stop
      @input.stop
      @paste.stop
      @cut.stop
      @copy.stop
      @drop.stop
    >
      <EditorContent v-if="editorRef" :editor="editorRef" />
    </div>
  </div>
</template>

<style scoped>
.kiwi-plugin-note-editor {
  border: 1px solid rgb(226 232 240);
  border-radius: 9px;
  background: #fff;
  overflow: hidden;
}

.kiwi-plugin-note-editor__toolbar {
  display: flex;
  flex-wrap: wrap;
  gap: 1px;
  padding: 3px 5px;
  border-bottom: 1px solid rgb(241 245 249);
  background: rgb(248 250 252 / 0.85);
}

.kiwi-plugin-note-editor__tool {
  display: grid;
  place-items: center;
  min-width: 24px;
  height: 23px;
  padding: 0 4px;
  border-radius: 5px;
  color: rgb(100 116 139);
  font-size: 11px;
  font-weight: 600;
  line-height: 1;
  transition: background 0.15s ease, color 0.15s ease;
}

.kiwi-plugin-note-editor__tool.is-italic {
  font-style: italic;
}

.kiwi-plugin-note-editor__tool.is-strike {
  text-decoration: line-through;
}

.kiwi-plugin-note-editor__tool.is-underline {
  text-decoration: underline;
}

.kiwi-plugin-note-editor__tool.is-code {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 10px;
}

.kiwi-plugin-note-editor__tool:hover:not(:disabled) {
  background: rgb(241 245 249);
  color: rgb(51 65 85);
}

.kiwi-plugin-note-editor__tool.is-active {
  background: rgb(var(--kiwi-50, 236 253 245));
  color: rgb(var(--kiwi-700, 4 120 87));
}

.kiwi-plugin-note-editor__tool:disabled {
  opacity: 0.42;
  cursor: default;
}

.kiwi-plugin-note-editor__body {
  padding: 7px 9px;
  min-height: var(--kiwi-plugin-note-min-height, 72px);
  /* 插件区块本身是 `contenteditable=false` 的可拖拽节点，Chromium 会把
     `user-select` 算成 none 并让整个区块一起拖走。嵌套编辑器必须显式恢复
     文本选择，否则鼠标拖选失效、指针也不会显示为文本光标。 */
  cursor: text;
  user-select: text;
  -webkit-user-select: text;
}

.kiwi-plugin-note-editor :deep(.ProseMirror) {
  min-height: inherit;
  outline: none;
  user-select: text;
  -webkit-user-select: text;
  color: rgb(51 65 85);
  font-size: 13px;
  line-height: 1.7;
  overflow-wrap: anywhere;
}

.kiwi-plugin-note-editor :deep(.ProseMirror > :first-child) {
  margin-top: 0;
}

.kiwi-plugin-note-editor :deep(.ProseMirror > :last-child) {
  margin-bottom: 0;
}

.kiwi-plugin-note-editor :deep(.ProseMirror p) {
  margin: 0.25rem 0;
}

.kiwi-plugin-note-editor :deep(.ProseMirror h1),
.kiwi-plugin-note-editor :deep(.ProseMirror h2),
.kiwi-plugin-note-editor :deep(.ProseMirror h3) {
  margin: 0.45rem 0 0.25rem;
  color: rgb(30 41 59);
  font-weight: 650;
  line-height: 1.4;
}

.kiwi-plugin-note-editor :deep(.ProseMirror h1) {
  font-size: 16px;
}

.kiwi-plugin-note-editor :deep(.ProseMirror h2) {
  font-size: 14px;
}

.kiwi-plugin-note-editor :deep(.ProseMirror h3) {
  font-size: 13px;
}

.kiwi-plugin-note-editor :deep(.ProseMirror ul),
.kiwi-plugin-note-editor :deep(.ProseMirror ol) {
  margin: 0.3rem 0;
  padding-left: 1.35rem;
}

.kiwi-plugin-note-editor :deep(.ProseMirror ul) {
  list-style: disc;
}

.kiwi-plugin-note-editor :deep(.ProseMirror ol) {
  list-style: decimal;
}

.kiwi-plugin-note-editor :deep(.ProseMirror li) {
  margin: 0.1rem 0;
}

.kiwi-plugin-note-editor :deep(.ProseMirror blockquote) {
  margin: 0.4rem 0;
  padding-left: 0.75rem;
  border-left: 3px solid rgb(var(--kiwi-300, 167 243 208));
  color: rgb(100 116 139);
}

.kiwi-plugin-note-editor :deep(.ProseMirror code) {
  padding: 1px 4px;
  border-radius: 4px;
  background: rgb(241 245 249);
  color: rgb(79 70 229);
  font-size: 0.88em;
}

.kiwi-plugin-note-editor :deep(.ProseMirror pre) {
  margin: 0.4rem 0;
  padding: 8px 10px;
  border-radius: 7px;
  background: rgb(15 23 42);
  color: rgb(226 232 240);
  font-size: 11.5px;
  overflow-x: auto;
}

.kiwi-plugin-note-editor :deep(.ProseMirror pre code) {
  padding: 0;
  background: transparent;
  color: inherit;
}

.kiwi-plugin-note-editor :deep(.ProseMirror a) {
  color: rgb(var(--kiwi-600, 5 150 105));
  text-decoration: underline;
}

.kiwi-plugin-note-editor :deep(.ProseMirror hr) {
  margin: 0.65rem 0;
  border: 0;
  border-top: 1px solid rgb(226 232 240);
}

.kiwi-plugin-note-editor :deep(.ProseMirror p.is-editor-empty:first-child::before) {
  float: left;
  height: 0;
  color: rgb(148 163 184);
  content: attr(data-placeholder);
  pointer-events: none;
}

/* 待办清单：与笔记编辑器一致，勾选后弱化并划线。 */
.kiwi-plugin-note-editor :deep(.ProseMirror ul[data-type='taskList']) {
  list-style: none;
  padding-left: 0;
}

.kiwi-plugin-note-editor :deep(.ProseMirror ul[data-type='taskList'] li) {
  display: flex;
  align-items: flex-start;
  gap: 6px;
}

.kiwi-plugin-note-editor :deep(.ProseMirror ul[data-type='taskList'] li > label) {
  display: flex;
  flex: 0 0 auto;
  align-items: center;
  height: 1.7em;
  margin: 0;
  user-select: none;
}

.kiwi-plugin-note-editor :deep(.ProseMirror ul[data-type='taskList'] li > label input[type='checkbox']) {
  width: 14px;
  height: 14px;
  margin: 0;
  accent-color: rgb(var(--kiwi-500, 16 185 129));
  cursor: pointer;
}

.kiwi-plugin-note-editor :deep(.ProseMirror ul[data-type='taskList'] li > div) {
  flex: 1;
  min-width: 0;
}

.kiwi-plugin-note-editor :deep(.ProseMirror ul[data-type='taskList'] li > div > p) {
  margin: 0;
}

.kiwi-plugin-note-editor :deep(.ProseMirror ul[data-type='taskList'] li[data-checked='true'] > div > p) {
  color: rgb(148 163 184);
  text-decoration: line-through;
  text-decoration-color: rgb(148 163 184 / 0.55);
}

.kiwi-plugin-note-editor.is-readonly {
  border: 0;
  border-radius: 0;
  background: transparent;
  overflow: visible;
}

.kiwi-plugin-note-editor.is-readonly .kiwi-plugin-note-editor__body {
  min-height: 0;
  padding: 0;
}

.kiwi-plugin-note-editor.is-readonly :deep(.ProseMirror) {
  /* 阅读态正文容器可能给外层编辑器设了 min-height（如 240px），
     这里必须覆盖，否则嵌套编辑器会把时间点卡片撑出大片空白。 */
  min-height: 0 !important;
}

.kiwi-plugin-note-editor.is-readonly :deep(.ProseMirror ul[data-type='taskList'] li > label) {
  pointer-events: none;
}

.kiwi-plugin-note-editor.is-readonly :deep(.ProseMirror ul[data-type='taskList'] li > label input[type='checkbox']) {
  cursor: default;
}
</style>

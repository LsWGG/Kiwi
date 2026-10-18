<script setup lang="ts">
/**
 * Notebook 单元格编辑器：CodeMirror 6，Python / Markdown 语法高亮、行号、
 * 自动缩进与括号匹配，并接管 Jupyter 常用快捷键（Shift+Enter 等）。
 */
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { Compartment, EditorState } from '@codemirror/state'
import {
  EditorView,
  drawSelection,
  dropCursor,
  highlightActiveLine,
  highlightActiveLineGutter,
  highlightSpecialChars,
  keymap,
  lineNumbers,
  placeholder as cmPlaceholder,
} from '@codemirror/view'
import {
  defaultKeymap,
  history,
  historyKeymap,
  indentWithTab,
  toggleComment,
} from '@codemirror/commands'
import {
  HighlightStyle,
  bracketMatching,
  defaultHighlightStyle,
  indentOnInput,
  syntaxHighlighting,
} from '@codemirror/language'
import {
  autocompletion,
  closeBrackets,
  closeBracketsKeymap,
  completionKeymap,
} from '@codemirror/autocomplete'
import { tags } from '@lezer/highlight'
import { python } from '@codemirror/lang-python'
import { markdown } from '@codemirror/lang-markdown'

const props = withDefaults(
  defineProps<{
    modelValue: string
    language?: 'python' | 'markdown'
    readonly?: boolean
    placeholder?: string
    minHeight?: number
    maxHeight?: number
    autofocus?: boolean
  }>(),
  {
    language: 'python',
    readonly: false,
    placeholder: '',
    minHeight: 68,
    maxHeight: 460,
    autofocus: false,
  },
)

const emit = defineEmits<{
  (e: 'update:modelValue', value: string): void
  (e: 'focus'): void
  (e: 'blur'): void
  (e: 'escape'): void
  /** Ctrl / Cmd + Enter：运行并保持焦点 */
  (e: 'run'): void
  /** Shift + Enter：运行并跳到下一格 */
  (e: 'run-next'): void
  /** Alt + Enter：运行并在下方插入 */
  (e: 'run-insert'): void
}>()

const host = ref<HTMLElement | null>(null)
const languageCompartment = new Compartment()
const editableCompartment = new Compartment()
let view: EditorView | null = null
let lastValue = props.modelValue
let applyingExternal = false

const kiwiTheme = EditorView.theme({
  '&': {
    fontSize: '12.5px',
    backgroundColor: 'transparent',
    color: '#1e293b',
  },
  '&.cm-focused': { outline: 'none' },
  '.cm-scroller': {
    fontFamily:
      'ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, "Liberation Mono", monospace',
    lineHeight: '1.65',
    overflow: 'auto',
  },
  '.cm-content': {
    padding: '8px 0',
    caretColor: '#0284c7',
  },
  '.cm-line': { padding: '0 10px' },
  '.cm-gutters': {
    backgroundColor: 'transparent',
    color: '#cbd5e1',
    border: 'none',
    paddingLeft: '4px',
  },
  '.cm-activeLineGutter': {
    backgroundColor: 'transparent',
    color: '#94a3b8',
  },
  '.cm-activeLine': { backgroundColor: 'rgba(14, 165, 233, 0.045)' },
  '.cm-selectionBackground, ::selection': {
    backgroundColor: 'rgba(14, 165, 233, 0.18) !important',
  },
  '.cm-cursor': { borderLeftColor: '#0284c7', borderLeftWidth: '1.5px' },
  '.cm-placeholder': { color: '#cbd5e1' },
  '.cm-tooltip': {
    border: '1px solid #e2e8f0',
    backgroundColor: '#ffffff',
    borderRadius: '8px',
    boxShadow: '0 8px 24px rgba(15, 23, 42, 0.12)',
  },
  '.cm-tooltip-autocomplete > ul > li[aria-selected]': {
    backgroundColor: '#e0f2fe',
    color: '#0c4a6e',
  },
})

const kiwiHighlight = HighlightStyle.define([
  { tag: tags.keyword, color: '#7c3aed' },
  { tag: [tags.function(tags.variableName), tags.labelName], color: '#0369a1' },
  { tag: [tags.typeName, tags.className, tags.number, tags.self, tags.namespace], color: '#c026d3' },
  { tag: [tags.operator, tags.operatorKeyword, tags.escape, tags.regexp], color: '#0e7490' },
  { tag: [tags.constant(tags.name), tags.standard(tags.name), tags.atom, tags.bool], color: '#b45309' },
  { tag: [tags.meta, tags.comment], color: '#94a3b8', fontStyle: 'italic' },
  { tag: tags.string, color: '#15803d' },
  { tag: [tags.heading, tags.strong], fontWeight: 'bold', color: '#0f172a' },
  { tag: tags.emphasis, fontStyle: 'italic' },
  { tag: tags.strikethrough, textDecoration: 'line-through' },
  { tag: tags.link, color: '#0284c7', textDecoration: 'underline' },
  { tag: tags.invalid, color: '#e11d48' },
])

function languageSupport(language: 'python' | 'markdown') {
  return language === 'markdown' ? markdown() : python()
}

function runKey(key: string, handler: () => void) {
  return {
    key,
    preventDefault: true,
    run: () => {
      handler()
      return true
    },
  }
}

function focusEditor(end = false) {
  if (!view) return
  view.focus()
  if (end) {
    const length = view.state.doc.length
    view.dispatch({ selection: { anchor: length } })
  }
}

defineExpose({ focusEditor })

onMounted(() => {
  if (!host.value) return
  view = new EditorView({
    parent: host.value,
    state: EditorState.create({
      doc: props.modelValue,
      extensions: [
        lineNumbers(),
        highlightActiveLineGutter(),
        highlightSpecialChars(),
        history(),
        drawSelection(),
        dropCursor(),
        EditorState.allowMultipleSelections.of(true),
        indentOnInput(),
        syntaxHighlighting(defaultHighlightStyle, { fallback: true }),
        syntaxHighlighting(kiwiHighlight),
        bracketMatching(),
        closeBrackets(),
        autocompletion({ activateOnTyping: true }),
        highlightActiveLine(),
        EditorView.lineWrapping,
        keymap.of([
          runKey('Shift-Enter', () => emit('run-next')),
          runKey('Mod-Enter', () => emit('run')),
          runKey('Alt-Enter', () => emit('run-insert')),
          {
            key: 'Escape',
            preventDefault: true,
            run: () => {
              emit('escape')
              view?.contentDOM.blur()
              return true
            },
          },
          { key: 'Mod-/', run: toggleComment, preventDefault: true },
          indentWithTab,
          ...closeBracketsKeymap,
          ...defaultKeymap,
          ...historyKeymap,
          ...completionKeymap,
        ]),
        cmPlaceholder(props.placeholder),
        kiwiTheme,
        languageCompartment.of(languageSupport(props.language)),
        editableCompartment.of(
          props.readonly ? [EditorState.readOnly.of(true), EditorView.editable.of(false)] : [],
        ),
        EditorView.updateListener.of((update) => {
          if (update.docChanged && !applyingExternal) {
            lastValue = update.state.doc.toString()
            emit('update:modelValue', lastValue)
          }
        }),
        EditorView.theme({
          '&': {
            minHeight: `${props.minHeight}px`,
            maxHeight: `${props.maxHeight}px`,
          },
        }),
      ],
    }),
  })
  view.dom.addEventListener('focusin', () => emit('focus'))
  view.dom.addEventListener('focusout', () => emit('blur'))
  if (props.autofocus) focusEditor(true)
})

watch(
  () => props.modelValue,
  (value) => {
    if (!view || value === lastValue) return
    applyingExternal = true
    view.dispatch({
      changes: { from: 0, to: view.state.doc.length, insert: value },
    })
    lastValue = value
    applyingExternal = false
  },
)

watch(
  () => props.language,
  (language) => {
    view?.dispatch({ effects: languageCompartment.reconfigure(languageSupport(language)) })
  },
)

watch(
  () => props.readonly,
  (readonly) => {
    view?.dispatch({
      effects: editableCompartment.reconfigure(
        readonly ? [EditorState.readOnly.of(true), EditorView.editable.of(false)] : [],
      ),
    })
  },
)

onBeforeUnmount(() => {
  view?.destroy()
  view = null
})
</script>

<template>
  <div ref="host" class="nb-cm-host min-w-0" />
</template>

<style scoped>
.nb-cm-host :deep(.cm-editor) {
  @apply rounded-lg border border-slate-200/70 bg-slate-50/60 transition-colors;
}
.nb-cm-host :deep(.cm-editor.cm-focused) {
  @apply border-kiwi-300 bg-white;
}
.nb-cm-host :deep(.cm-editor .cm-scroller) {
  border-radius: 0.5rem;
}
</style>

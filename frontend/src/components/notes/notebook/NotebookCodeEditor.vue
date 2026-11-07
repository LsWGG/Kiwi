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

/**
 * 主题在应用启动后才写入 <html>，因此配色要在挂载时读取，
 * 不能在模块顶层缓存。内置 classic 保持原有蓝色编辑态；
 * 安装主题后代码区跟随主题令牌与明暗模式。
 */
function themeContext() {
  const root = document.documentElement
  const custom = root.dataset.kiwiThemeCustom === 'true'
  const dark = custom && root.dataset.kiwiThemeMode === 'dark'
  return { custom, dark }
}

function buildEditorTheme() {
  const { custom, dark } = themeContext()
  const colors = custom
    ? {
        text: 'rgb(var(--theme-text-primary))',
        caret: 'rgb(var(--theme-accent))',
        gutter: 'rgb(var(--theme-text-faint))',
        gutterActive: 'rgb(var(--theme-text-subtle))',
        activeLine: 'rgb(var(--theme-accent) / 0.08)',
        selection: 'rgb(var(--theme-accent) / 0.22)',
        placeholder: 'rgb(var(--theme-text-faint))',
        tooltipBg: 'rgb(var(--theme-surface))',
        tooltipBorder: 'rgb(var(--theme-border))',
        tooltipShadow: '0 8px 24px rgba(0, 0, 0, 0.35)',
        selectedBg: 'rgb(var(--theme-accent) / 0.18)',
        selectedText: 'rgb(var(--theme-text-primary))',
      }
    : {
        text: '#1e293b',
        caret: '#0284c7',
        gutter: '#cbd5e1',
        gutterActive: '#94a3b8',
        activeLine: 'rgba(14, 165, 233, 0.045)',
        selection: 'rgba(14, 165, 233, 0.18)',
        placeholder: '#cbd5e1',
        tooltipBg: '#ffffff',
        tooltipBorder: '#e2e8f0',
        tooltipShadow: '0 8px 24px rgba(15, 23, 42, 0.12)',
        selectedBg: '#e0f2fe',
        selectedText: '#0c4a6e',
      }
  return EditorView.theme(
    {
      '&': {
        fontSize: '12.5px',
        backgroundColor: 'transparent',
        color: colors.text,
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
        caretColor: colors.caret,
      },
      '.cm-line': { padding: '0 10px' },
      '.cm-gutters': {
        backgroundColor: 'transparent',
        color: colors.gutter,
        border: 'none',
        paddingLeft: '4px',
      },
      '.cm-activeLineGutter': {
        backgroundColor: 'transparent',
        color: colors.gutterActive,
      },
      '.cm-activeLine': { backgroundColor: colors.activeLine },
      '.cm-selectionBackground, ::selection': {
        backgroundColor: `${colors.selection} !important`,
      },
      '.cm-cursor': { borderLeftColor: colors.caret, borderLeftWidth: '1.5px' },
      '.cm-placeholder': { color: colors.placeholder },
      '.cm-tooltip': {
        border: `1px solid ${colors.tooltipBorder}`,
        backgroundColor: colors.tooltipBg,
        color: colors.text,
        borderRadius: '8px',
        boxShadow: colors.tooltipShadow,
      },
      '.cm-tooltip-autocomplete > ul > li[aria-selected]': {
        backgroundColor: colors.selectedBg,
        color: colors.selectedText,
      },
    },
    { dark },
  )
}

function buildHighlightStyle() {
  const { custom, dark } = themeContext()
  const syntax = dark
    ? {
        keyword: '#c4b5fd',
        fn: '#7dd3fc',
        type: '#f0abfc',
        operator: '#67e8f9',
        constant: '#fcd34d',
        comment: '#94a3b8',
        string: '#86efac',
        heading: '#f1f5f9',
        link: '#5eead4',
        invalid: '#fb7185',
      }
    : custom
      ? {
          keyword: '#7c3aed',
          fn: '#0369a1',
          type: '#c026d3',
          operator: '#0e7490',
          constant: '#b45309',
          comment: 'rgb(var(--theme-text-subtle))',
          string: '#15803d',
          heading: 'rgb(var(--theme-text-primary))',
          link: 'rgb(var(--theme-accent))',
          invalid: '#e11d48',
        }
      : {
          keyword: '#7c3aed',
          fn: '#0369a1',
          type: '#c026d3',
          operator: '#0e7490',
          constant: '#b45309',
          comment: '#94a3b8',
          string: '#15803d',
          heading: '#0f172a',
          link: '#0284c7',
          invalid: '#e11d48',
        }
  return HighlightStyle.define([
    { tag: tags.keyword, color: syntax.keyword },
    { tag: [tags.function(tags.variableName), tags.labelName], color: syntax.fn },
    { tag: [tags.typeName, tags.className, tags.number, tags.self, tags.namespace], color: syntax.type },
    { tag: [tags.operator, tags.operatorKeyword, tags.escape, tags.regexp], color: syntax.operator },
    { tag: [tags.constant(tags.name), tags.standard(tags.name), tags.atom, tags.bool], color: syntax.constant },
    { tag: [tags.meta, tags.comment], color: syntax.comment, fontStyle: 'italic' },
    { tag: tags.string, color: syntax.string },
    { tag: [tags.heading, tags.strong], fontWeight: 'bold', color: syntax.heading },
    { tag: tags.emphasis, fontStyle: 'italic' },
    { tag: tags.strikethrough, textDecoration: 'line-through' },
    { tag: tags.link, color: syntax.link, textDecoration: 'underline' },
    { tag: tags.invalid, color: syntax.invalid },
  ])
}

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
        syntaxHighlighting(buildHighlightStyle()),
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
        buildEditorTheme(),
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
  border: 1px solid rgb(var(--theme-border) / 0.7);
  border-radius: 0.5rem;
  background: rgb(var(--theme-app) / 0.6);
  transition: background-color 0.15s ease, border-color 0.15s ease;
}
.nb-cm-host :deep(.cm-editor.cm-focused) {
  border-color: rgb(var(--kiwi-300));
  background: rgb(var(--theme-surface) / var(--theme-surface-opacity));
}
.nb-cm-host :deep(.cm-editor .cm-scroller) {
  border-radius: 0.5rem;
}
</style>

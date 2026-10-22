<script setup lang="ts">
/** 公式块：KaTeX 预览 + 就地编辑 LaTeX 源码。 */
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { NodeViewWrapper, nodeViewProps } from '@tiptap/vue-3'
import katex from 'katex'
import 'katex/dist/katex.min.css'
import KiwiIcon from '@/components/ui/KiwiIcon.vue'
import { useEditorEditable } from './useEditorEditable'

const props = defineProps(nodeViewProps)

const editable = useEditorEditable(props.editor)
// 阅读模式不进入编辑态，避免只读页面里出现输入框和外框
const editing = ref(editable.value && !String(props.node.attrs.latex || '').trim())
const draft = ref(String(props.node.attrs.latex || ''))
const textarea = ref<HTMLTextAreaElement | null>(null)
const root = ref<HTMLElement | null>(null)

watch(
  () => props.node.attrs.latex,
  (value) => {
    if (!editing.value) draft.value = String(value || '')
  },
)

const rendered = computed(() => {
  const latex = String(props.node.attrs.latex || '').trim()
  if (!latex) {
    return '<span class="kiwi-formula-empty">点击编辑公式</span>'
  }
  try {
    return katex.renderToString(latex, {
      displayMode: true,
      throwOnError: false,
      strict: false,
      trust: false,
    })
  } catch (e: any) {
    return `<span class="kiwi-formula-error">${String(e?.message || '公式无法渲染')}</span>`
  }
})

const preview = computed(() => {
  const latex = draft.value.trim()
  if (!latex) return '<span class="kiwi-formula-empty">输入 LaTeX，例如 E = mc^2</span>'
  try {
    return katex.renderToString(latex, {
      displayMode: true,
      throwOnError: false,
      strict: false,
      trust: false,
    })
  } catch (e: any) {
    return `<span class="kiwi-formula-error">${String(e?.message || '公式无法渲染')}</span>`
  }
})

function startEdit() {
  if (!editable.value) return
  draft.value = String(props.node.attrs.latex || '')
  editing.value = true
  void nextTick(() => textarea.value?.focus())
}

function save() {
  const latex = draft.value.trim()
  if (!latex) {
    props.deleteNode()
    return
  }
  editing.value = false
  if (latex !== props.node.attrs.latex) props.updateAttributes({ latex })
}

function cancel() {
  if (!String(props.node.attrs.latex || '').trim()) {
    props.deleteNode()
    return
  }
  editing.value = false
}

function onDocPointer(event: MouseEvent) {
  if (!editing.value) return
  // NodeViewWrapper 的模板 ref 是组件实例而非 DOM，容器要通过编辑器查。
  const dom = (() => {
    try {
      const pos = props.getPos()
      return typeof pos === 'number' ? props.editor.view.nodeDOM(pos) : null
    } catch {
      return null
    }
  })()
  const target = event.target as Node | null
  if (!dom || !target || !(dom as HTMLElement).contains(target)) save()
}

onMounted(() => document.addEventListener('mousedown', onDocPointer))
onBeforeUnmount(() => document.removeEventListener('mousedown', onDocPointer))
</script>

<template>
  <NodeViewWrapper
    ref="root"
    class="kiwi-formula-block"
    :class="{ 'is-selected': selected, 'is-editing': editing, 'is-readonly': !editable }"
    data-type="kiwi-formula"
    contenteditable="false"
  >
    <template v-if="!editing || !editable">
      <div v-if="editable" class="kiwi-formula-toolbar">
        <span class="kiwi-formula-tag"><KiwiIcon name="code" :size="11" />公式</span>
        <button type="button" class="kiwi-formula-action" title="编辑公式" @mousedown.prevent @click="startEdit">
          <KiwiIcon name="edit" :size="12" />
        </button>
      </div>
      <div
        v-if="editable || String(node.attrs.latex || '').trim()"
        class="kiwi-formula-render"
        @click="startEdit"
        v-html="rendered"
      />
    </template>
    <template v-else>
      <div class="kiwi-formula-toolbar">
        <span class="kiwi-formula-tag"><KiwiIcon name="code" :size="11" />编辑 LaTeX</span>
        <span class="kiwi-formula-hint">支持 \frac、\sum、矩阵等</span>
        <div class="ml-auto flex items-center gap-1">
          <button type="button" class="kiwi-formula-btn" @mousedown.prevent @click="cancel">取消</button>
          <button type="button" class="kiwi-formula-btn is-primary" @mousedown.prevent @click="save">完成</button>
        </div>
      </div>
      <textarea
        ref="textarea"
        v-model="draft"
        rows="3"
        class="kiwi-formula-input"
        spellcheck="false"
        placeholder="E = mc^2"
        @keydown.meta.enter.prevent="save"
        @keydown.ctrl.enter.prevent="save"
        @keydown.esc.prevent="cancel"
      />
      <div class="kiwi-formula-preview" v-html="preview" />
    </template>
  </NodeViewWrapper>
</template>

<style scoped>
.kiwi-formula-block {
  margin: 0.75rem 0;
  border-radius: 12px;
  border: 1px solid rgb(226 232 240);
  background: rgb(248 250 252 / 0.75);
  transition: border-color 0.15s ease, box-shadow 0.15s ease;
}
/* 阅读模式：去掉组件外框，只展示公式本身 */
.kiwi-formula-block.is-readonly {
  margin: 0.9rem 0;
  border: 0;
  background: transparent;
  border-radius: 0;
}
.kiwi-formula-block.is-readonly .kiwi-formula-render {
  padding: 0;
  cursor: default;
}
.kiwi-formula-block.is-selected,
.kiwi-formula-block.is-editing {
  border-color: rgb(var(--kiwi-300));
  box-shadow: 0 0 0 3px rgb(var(--kiwi-100) / 0.55);
}
.kiwi-formula-toolbar {
  display: flex;
  align-items: center;
  gap: 8px;
  min-height: 30px;
  padding: 4px 10px;
  border-bottom: 1px solid rgb(226 232 240 / 0.8);
  color: rgb(100 116 139);
  font-size: 11px;
}
.kiwi-formula-tag {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-weight: 500;
  color: rgb(71 85 105);
}
.kiwi-formula-hint {
  color: rgb(148 163 184);
}
.kiwi-formula-action {
  margin-left: auto;
  padding: 3px;
  border-radius: 6px;
  color: rgb(148 163 184);
}
.kiwi-formula-action:hover {
  color: rgb(var(--kiwi-600));
  background: rgb(var(--kiwi-50));
}
.kiwi-formula-render {
  padding: 14px 16px;
  overflow-x: auto;
  cursor: text;
  color: rgb(30 41 59);
}
.kiwi-formula-render :deep(.katex-display) {
  margin: 0.25em 0;
}
.kiwi-formula-empty {
  color: rgb(148 163 184);
  font-size: 13px;
}
.kiwi-formula-error {
  color: rgb(220 38 38);
  font-size: 12px;
  white-space: pre-wrap;
}
.kiwi-formula-btn {
  border-radius: 6px;
  padding: 2px 9px;
  color: rgb(71 85 105);
  border: 1px solid rgb(226 232 240);
  background: #fff;
}
.kiwi-formula-btn.is-primary {
  color: #fff;
  border-color: rgb(var(--kiwi-600));
  background: rgb(var(--kiwi-600));
}
.kiwi-formula-btn:hover {
  opacity: 0.86;
}
.kiwi-formula-input {
  display: block;
  width: 100%;
  resize: vertical;
  padding: 10px 12px;
  border: 0;
  border-bottom: 1px dashed rgb(203 213 225);
  background: rgb(255 255 255 / 0.7);
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 12.5px;
  line-height: 1.6;
  color: rgb(51 65 85);
  outline: none;
}
.kiwi-formula-preview {
  padding: 12px 16px;
  overflow-x: auto;
  color: rgb(30 41 59);
}
.kiwi-formula-preview :deep(.katex-display) {
  margin: 0.2em 0;
}
</style>

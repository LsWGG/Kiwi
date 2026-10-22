<script setup lang="ts">
/** Mermaid 绘图块：左侧源码、右侧实时预览；非编辑态展示渲染图。 */
import { nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { NodeViewWrapper, nodeViewProps } from '@tiptap/vue-3'
import mermaid from 'mermaid'
import KiwiIcon from '@/components/ui/KiwiIcon.vue'
import { useEditorEditable } from './useEditorEditable'

const props = defineProps(nodeViewProps)

let initializedTheme = ''
function ensureInit() {
  const dark =
    document.documentElement.classList.contains('dark') ||
    document.body.classList.contains('dark')
  const theme = dark ? 'dark' : 'default'
  if (initializedTheme === theme) return
  initializedTheme = theme
  mermaid.initialize({
    startOnLoad: false,
    securityLevel: 'strict',
    theme,
    fontFamily:
      '-apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif',
    flowchart: { htmlLabels: false, curve: 'basis' },
    sequence: { useMaxWidth: true },
  })
}

const editable = useEditorEditable(props.editor)
// 阅读模式不进入编辑态，仅呈现渲染结果
const editing = ref(editable.value && !String(props.node.attrs.code || '').trim())
const draft = ref(String(props.node.attrs.code || ''))
const svg = ref('')
const error = ref('')
const loading = ref(false)
const root = ref<HTMLElement | null>(null)
const textarea = ref<HTMLTextAreaElement | null>(null)
let seq = 0

async function render(code: string) {
  const source = code.trim()
  seq += 1
  const current = seq
  if (!source) {
    svg.value = ''
    error.value = ''
    return
  }
  loading.value = true
  try {
    ensureInit()
    const id = `kiwi-mermaid-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
    const result = await mermaid.render(id, source)
    if (current !== seq) return
    svg.value = result.svg
    error.value = ''
  } catch (e: any) {
    if (current !== seq) return
    svg.value = ''
    error.value = String(e?.message || '图表语法有误')
  } finally {
    if (current === seq) loading.value = false
  }
}

let timer: number | undefined
watch(
  () => [props.node.attrs.code, editing.value] as const,
  ([code, isEditing]) => {
    window.clearTimeout(timer)
    timer = window.setTimeout(() => {
      void render(isEditing ? draft.value : String(code || ''))
    }, isEditing ? 260 : 0)
  },
  { immediate: true },
)

function startEdit() {
  if (!editable.value) return
  draft.value = String(props.node.attrs.code || '')
  editing.value = true
  void nextTick(() => {
    textarea.value?.focus()
    void render(draft.value)
  })
}

function save() {
  const code = draft.value.trim()
  if (!code) {
    props.deleteNode()
    return
  }
  editing.value = false
  if (code !== props.node.attrs.code) props.updateAttributes({ code })
  void nextTick(() => void render(code))
}

function cancel() {
  if (!String(props.node.attrs.code || '').trim()) {
    props.deleteNode()
    return
  }
  editing.value = false
  draft.value = String(props.node.attrs.code || '')
  void nextTick(() => void render(draft.value))
}

function downloadSvg() {
  if (!svg.value) return
  const blob = new Blob([svg.value], { type: 'image/svg+xml;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = 'kiwi-mermaid.svg'
  a.click()
  URL.revokeObjectURL(url)
}

onBeforeUnmount(() => window.clearTimeout(timer))
</script>

<template>
  <NodeViewWrapper
    ref="root"
    class="kiwi-mermaid-block"
    :class="{ 'is-selected': selected, 'is-editing': editing, 'is-readonly': !editable }"
    data-type="kiwi-mermaid"
    contenteditable="false"
  >
    <div v-if="editable" class="kiwi-mermaid-toolbar">
      <span class="kiwi-mermaid-tag"><KiwiIcon name="graph" :size="11" />文本绘图 · Mermaid</span>
      <span v-if="loading" class="kiwi-mermaid-status">渲染中…</span>
      <span v-else-if="error" class="kiwi-mermaid-status is-error">语法有误</span>
      <div class="ml-auto flex items-center gap-1">
        <template v-if="editing">
          <button type="button" class="kiwi-mermaid-btn" @mousedown.prevent @click="cancel">取消</button>
          <button type="button" class="kiwi-mermaid-btn is-primary" @mousedown.prevent @click="save">
            完成
          </button>
        </template>
        <template v-else>
          <button type="button" class="kiwi-mermaid-action" title="下载 SVG" @mousedown.prevent @click="downloadSvg">
            <KiwiIcon name="download" :size="12" />
          </button>
          <button type="button" class="kiwi-mermaid-action" title="编辑源码" @mousedown.prevent @click="startEdit">
            <KiwiIcon name="edit" :size="12" />
          </button>
        </template>
      </div>
    </div>

    <div v-if="editing" class="kiwi-mermaid-edit">
      <textarea
        ref="textarea"
        v-model="draft"
        class="kiwi-mermaid-input"
        spellcheck="false"
        rows="10"
        placeholder="flowchart LR&#10;  A[开始] --> B[结束]"
        @keydown.meta.enter.prevent="save"
        @keydown.ctrl.enter.prevent="save"
        @keydown.esc.prevent="cancel"
      />
      <div class="kiwi-mermaid-preview">
        <div v-if="svg" class="kiwi-mermaid-svg" v-html="svg" />
        <pre v-else-if="error" class="kiwi-mermaid-error">{{ error }}</pre>
        <span v-else class="kiwi-mermaid-empty">在左侧输入 Mermaid 语法，右侧实时预览</span>
      </div>
    </div>

    <div v-else class="kiwi-mermaid-view" @click="startEdit">
      <div v-if="svg" class="kiwi-mermaid-svg" v-html="svg" />
      <pre v-else-if="error" class="kiwi-mermaid-error">{{ error }}</pre>
      <span v-else class="kiwi-mermaid-empty">点击编辑 Mermaid 源码</span>
    </div>
  </NodeViewWrapper>
</template>

<style scoped>
.kiwi-mermaid-block {
  margin: 0.75rem 0;
  border-radius: 12px;
  border: 1px solid rgb(226 232 240);
  background: rgb(248 250 252 / 0.75);
  transition: border-color 0.15s ease, box-shadow 0.15s ease;
}
/* 阅读模式：去掉组件外框，只展示图形 */
.kiwi-mermaid-block.is-readonly {
  margin: 0.9rem 0;
  border: 0;
  background: transparent;
  border-radius: 0;
}
.kiwi-mermaid-block.is-readonly .kiwi-mermaid-view {
  min-height: 0;
  padding: 4px 0;
  cursor: default;
}
.kiwi-mermaid-block.is-selected,
.kiwi-mermaid-block.is-editing {
  border-color: rgb(var(--kiwi-300));
  box-shadow: 0 0 0 3px rgb(var(--kiwi-100) / 0.55);
}
.kiwi-mermaid-toolbar {
  display: flex;
  align-items: center;
  gap: 8px;
  min-height: 30px;
  padding: 4px 10px;
  border-bottom: 1px solid rgb(226 232 240 / 0.8);
  color: rgb(100 116 139);
  font-size: 11px;
}
.kiwi-mermaid-tag {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-weight: 500;
  color: rgb(71 85 105);
}
.kiwi-mermaid-status {
  color: rgb(148 163 184);
}
.kiwi-mermaid-status.is-error {
  color: rgb(220 38 38);
}
.kiwi-mermaid-action {
  padding: 3px;
  border-radius: 6px;
  color: rgb(148 163 184);
}
.kiwi-mermaid-action:hover {
  color: rgb(var(--kiwi-600));
  background: rgb(var(--kiwi-50));
}
.kiwi-mermaid-btn {
  border-radius: 6px;
  padding: 2px 9px;
  color: rgb(71 85 105);
  border: 1px solid rgb(226 232 240);
  background: #fff;
}
.kiwi-mermaid-btn.is-primary {
  color: #fff;
  border-color: rgb(var(--kiwi-600));
  background: rgb(var(--kiwi-600));
}
.kiwi-mermaid-btn:hover {
  opacity: 0.86;
}
.kiwi-mermaid-edit {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
}
.kiwi-mermaid-input {
  resize: none;
  min-height: 230px;
  padding: 12px;
  border: 0;
  border-right: 1px dashed rgb(203 213 225);
  background: rgb(255 255 255 / 0.7);
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 12.5px;
  line-height: 1.65;
  color: rgb(51 65 85);
  outline: none;
}
.kiwi-mermaid-preview,
.kiwi-mermaid-view {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 180px;
  padding: 14px;
  overflow: auto;
}
.kiwi-mermaid-view {
  cursor: text;
}
.kiwi-mermaid-svg {
  max-width: 100%;
  overflow: auto;
}
.kiwi-mermaid-svg :deep(svg) {
  max-width: 100%;
  height: auto;
  margin: 0 auto;
}
.kiwi-mermaid-empty {
  color: rgb(148 163 184);
  font-size: 12px;
}
.kiwi-mermaid-error {
  margin: 0;
  max-width: 100%;
  overflow: auto;
  color: rgb(220 38 38);
  font-size: 11.5px;
  white-space: pre-wrap;
}
@media (max-width: 900px) {
  .kiwi-mermaid-edit {
    grid-template-columns: minmax(0, 1fr);
  }
  .kiwi-mermaid-input {
    border-right: 0;
    border-bottom: 1px dashed rgb(203 213 225);
    min-height: 160px;
  }
}
</style>

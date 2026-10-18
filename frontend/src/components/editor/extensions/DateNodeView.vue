<script setup lang="ts">
/** 日期胶囊：点击弹出原生日期选择器，就地修改。 */
import { nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { NodeViewWrapper, nodeViewProps } from '@tiptap/vue-3'
import { useEditorEditable } from './useEditorEditable'

const props = defineProps(nodeViewProps)

const root = ref<HTMLElement | null>(null)
const input = ref<HTMLInputElement | null>(null)
const editable = useEditorEditable(props.editor)
const editing = ref(false)
const draft = ref(String(props.node.attrs.date || ''))

function open() {
  if (!editable.value) return
  draft.value = String(props.node.attrs.date || '')
  editing.value = true
  void nextTick(() => input.value?.showPicker?.())
}

function save() {
  if (draft.value) props.updateAttributes({ date: draft.value })
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
  if (!dom || !target || !(dom as HTMLElement).contains(target)) {
    save()
  }
}

onMounted(() => document.addEventListener('mousedown', onDocPointer))
onBeforeUnmount(() => document.removeEventListener('mousedown', onDocPointer))
</script>

<template>
  <NodeViewWrapper
    ref="root"
    as="span"
    class="kiwi-date-wrap"
    :class="{ 'is-selected': selected, 'is-readonly': !editable }"
    data-kiwi-date-node
    contenteditable="false"
  >
    <button
      type="button"
      class="kiwi-date-chip"
      :title="editable ? '点击修改日期' : String(node.attrs.date || '')"
      @mousedown.prevent
      @click.stop="open"
    >
      <span aria-hidden="true">📅</span>
      <span>{{ node.attrs.date || '选择日期' }}</span>
    </button>
    <span v-if="editing" class="kiwi-date-pop" @mousedown.stop>
      <input
        ref="input"
        v-model="draft"
        type="date"
        class="kiwi-date-input"
        @keydown.enter.prevent="save"
        @keydown.esc.prevent="editing = false"
      />
      <button type="button" class="kiwi-date-ok" @mousedown.prevent @click="save">确定</button>
    </span>
  </NodeViewWrapper>
</template>

<style scoped>
.kiwi-date-wrap {
  position: relative;
  display: inline-flex;
  vertical-align: baseline;
}
.kiwi-date-chip {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  margin: 0 2px;
  padding: 1px 7px;
  border-radius: 999px;
  border: 1px solid rgb(190 242 100 / 0.65);
  background: rgb(247 254 231);
  color: rgb(63 98 18);
  font-size: 0.86em;
  line-height: 1.5;
  font-variant-numeric: tabular-nums;
  cursor: pointer;
  transition: background 0.15s ease, border-color 0.15s ease;
}
.kiwi-date-chip:hover {
  background: rgb(236 252 203);
  border-color: rgb(163 230 53 / 0.8);
}
.is-readonly .kiwi-date-chip {
  cursor: default;
}
.is-readonly .kiwi-date-chip:hover {
  background: rgb(247 254 231);
  border-color: rgb(190 242 100 / 0.65);
}
.is-selected .kiwi-date-chip {
  outline: 2px solid rgb(132 204 22 / 0.55);
  outline-offset: 1px;
}
.kiwi-date-pop {
  position: absolute;
  left: 0;
  top: calc(100% + 6px);
  z-index: 40;
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 7px;
  border-radius: 12px;
  border: 1px solid rgb(226 232 240);
  background: #fff;
  box-shadow: 0 12px 32px rgb(15 23 42 / 0.14);
}
.kiwi-date-input {
  border: 1px solid rgb(203 213 225);
  border-radius: 8px;
  padding: 4px 6px;
  font-size: 12px;
  color: rgb(51 65 85);
  outline: none;
}
.kiwi-date-input:focus {
  border-color: rgb(132 204 22);
  box-shadow: 0 0 0 2px rgb(217 249 157 / 0.6);
}
.kiwi-date-ok {
  border-radius: 8px;
  padding: 4px 10px;
  font-size: 12px;
  color: #fff;
  background: rgb(101 163 13);
}
.kiwi-date-ok:hover {
  background: rgb(77 124 15);
}
</style>

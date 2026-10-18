<script setup lang="ts">
/**
 * 数据表块：与数据表笔记同等的数据模型（字段 / 四视图 / 记录）。
 * 通过 EmbeddedDatabase 复用笔记数据表的视图组件。
 */
import { computed } from 'vue'
import { NodeViewWrapper, nodeViewProps } from '@tiptap/vue-3'
import KiwiIcon from '@/components/ui/KiwiIcon.vue'
import EmbeddedDatabase from './EmbeddedDatabase.vue'
import { normalizeDataTable } from './dataTableModel'
import { useEditorEditable } from './useEditorEditable'

const props = defineProps(nodeViewProps)

const editable = useEditorEditable(props.editor)

const model = computed(() =>
  normalizeDataTable({
    title: props.node.attrs.title,
    fields: props.node.attrs.fields,
    views: props.node.attrs.views,
    rows: props.node.attrs.rows,
    view: props.node.attrs.view,
  }),
)

function update(attrs: Record<string, unknown>) {
  props.updateAttributes(attrs)
}

function setTitle(event: Event) {
  update({ title: (event.target as HTMLInputElement).value })
}
</script>

<template>
  <NodeViewWrapper
    class="kiwi-datatable-block"
    :class="{ 'is-selected': selected, 'is-readonly': !editable }"
    data-type="kiwi-datatable"
    contenteditable="false"
  >
    <div v-if="editable" class="kiwi-datatable-toolbar">
      <span class="kiwi-datatable-tag">
        <KiwiIcon name="table" :size="11" />
        数据表
      </span>
      <input
        class="kiwi-datatable-title"
        :value="model.title"
        placeholder="添加数据表标题"
        @input="setTitle"
        @keydown.stop
        @mousedown.stop
      />
      <span class="kiwi-datatable-size">
        {{ model.fields.length }} 个字段 · {{ model.views.length }} 个视图
      </span>
    </div>

    <h4 v-if="!editable && model.title" class="kiwi-datatable-readonly-title">
      {{ model.title }}
    </h4>

    <EmbeddedDatabase
      :fields="model.fields"
      :views="model.views"
      :rows="model.rows"
      :active-view="model.view"
      :editable="editable"
      @fields="update({ fields: $event })"
      @views="update({ views: $event })"
      @rows="update({ rows: $event })"
      @view="update({ view: $event })"
    />
  </NodeViewWrapper>
</template>

<style scoped>
.kiwi-datatable-block {
  margin: 0.75rem 0;
  border-radius: 12px;
  border: 1px solid rgb(226 232 240);
  background: rgb(255 255 255 / 0.86);
  transition: border-color 0.15s ease, box-shadow 0.15s ease;
}
.kiwi-datatable-block.is-selected {
  border-color: rgb(190 242 100);
  box-shadow: 0 0 0 3px rgb(236 252 203 / 0.55);
}
/* 阅读模式：去掉组件外框，直接聚焦数据内容 */
.kiwi-datatable-block.is-readonly {
  margin: 0.9rem 0;
  border: 0;
  background: transparent;
  border-radius: 0;
}
.kiwi-datatable-readonly-title {
  margin: 0 0 6px;
  font-size: 12.5px;
  font-weight: 600;
  color: rgb(51 65 85);
}
.kiwi-datatable-toolbar {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 7px 10px 5px;
}
.kiwi-datatable-tag {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  flex-shrink: 0;
  font-size: 11px;
  font-weight: 500;
  color: rgb(71 85 105);
}
.kiwi-datatable-title {
  min-width: 0;
  flex: 1;
  border: 0;
  background: transparent;
  font-size: 12px;
  color: rgb(51 65 85);
  outline: none;
}
.kiwi-datatable-title::placeholder {
  color: rgb(148 163 184);
}
.kiwi-datatable-size {
  flex-shrink: 0;
  font-size: 9.5px;
  color: rgb(148 163 184);
  font-variant-numeric: tabular-nums;
}
</style>

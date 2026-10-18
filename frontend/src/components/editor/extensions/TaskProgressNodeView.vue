<script setup lang="ts">
/**
 * 待办进度块：显示绑定清单的完成度，并提供标题 / 计数 / 配色 / 绑定方向配置。
 * 所有配置写入节点属性，随 Markdown 围栏一起保存。
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { NodeViewWrapper, nodeViewProps } from '@tiptap/vue-3'
import KiwiIcon from '@/components/ui/KiwiIcon.vue'
import { useEditorEditable } from './useEditorEditable'
import {
  TASK_PROGRESS_COLORS,
  TASK_PROGRESS_COLOR_LABELS,
  findBoundTaskList,
  normalizeTaskProgressBind,
  normalizeTaskProgressColor,
  starterTaskListContent,
  taskListStats,
  type TaskProgressBind,
  type TaskProgressColor,
} from './taskProgress'

const props = defineProps(nodeViewProps)
const editable = useEditorEditable(props.editor)

/** NodeView 不会自动在每次勾选后重算，用文档事务版本触发 computed。 */
const docVersion = ref(0)
const bump = () => {
  docVersion.value += 1
}
onMounted(() => props.editor.on('transaction', bump))
onBeforeUnmount(() => props.editor.off('transaction', bump))

const label = computed(() => String(props.node.attrs.label || '待办进度'))
const showCount = computed(() => props.node.attrs.showCount !== false)
const showPercent = computed(() => props.node.attrs.showPercent !== false)
const color = computed<TaskProgressColor>(() =>
  normalizeTaskProgressColor(props.node.attrs.color),
)
const bind = computed<TaskProgressBind>(() =>
  normalizeTaskProgressBind(props.node.attrs.bind),
)

const stats = computed(() => {
  docVersion.value
  const pos = props.getPos()
  if (typeof pos !== 'number') return null
  const list = findBoundTaskList(props.editor.state.doc, pos, bind.value)
  return list ? taskListStats(list.node) : null
})

const percent = computed(() => stats.value?.percent ?? 0)
const hasBothMeta = computed(() => showCount.value && showPercent.value)

const settingsOpen = ref(false)
const titleDraft = ref(label.value)
watch(label, (value) => {
  if (!settingsOpen.value) titleDraft.value = value
})

function update(attrs: Record<string, unknown>) {
  props.updateAttributes(attrs)
}

function commitTitle() {
  const next = titleDraft.value.trim().slice(0, 80) || '待办进度'
  titleDraft.value = next
  if (next !== label.value) update({ label: next })
}

function toggle(key: 'showCount' | 'showPercent', event: Event) {
  update({ [key]: (event.target as HTMLInputElement).checked })
}

function setBind(event: Event) {
  update({ bind: normalizeTaskProgressBind((event.target as HTMLSelectElement).value) })
}

function setColor(next: TaskProgressColor) {
  update({ color: next })
}

function insertStarterList() {
  const pos = props.getPos()
  if (typeof pos !== 'number') return
  props.editor
    .chain()
    .focus()
    .insertContentAt(pos + props.node.nodeSize, starterTaskListContent())
    .run()
}

function remove() {
  props.deleteNode()
}
</script>

<template>
  <NodeViewWrapper
    as="div"
    class="kiwi-task-progress-card"
    :class="[`tone-${color}`, { 'is-selected': selected, 'is-empty': !stats }]"
    contenteditable="false"
    data-kiwi-task-progress-card="true"
    :data-task-done="stats?.done ?? 0"
    :data-task-total="stats?.total ?? 0"
    :data-task-percent="percent"
  >
    <div class="kiwi-task-progress-head">
      <span class="kiwi-task-progress-badge">
        <KiwiIcon name="checkSquare" :size="13" />
      </span>
      <span class="kiwi-task-progress-label" :title="label">{{ label }}</span>
      <span v-if="stats" class="kiwi-task-progress-meta">
        <template v-if="showCount">{{ stats.done }} / {{ stats.total }}</template>
        <span v-if="hasBothMeta" class="kiwi-task-progress-dot">·</span>
        <template v-if="showPercent">{{ percent }}%</template>
      </span>
      <span v-else class="kiwi-task-progress-meta is-muted">未找到任务清单</span>
      <span class="kiwi-task-progress-spacer" />
      <button
        v-if="editable"
        type="button"
        class="kiwi-task-progress-icon"
        :class="{ 'is-active': settingsOpen }"
        title="配置进度条"
        @mousedown.prevent
        @click.stop="settingsOpen = !settingsOpen"
      >
        <KiwiIcon name="settings" :size="13" />
      </button>
      <button
        v-if="editable"
        type="button"
        class="kiwi-task-progress-icon is-danger"
        title="删除进度条"
        @mousedown.prevent
        @click.stop="remove"
      >
        <KiwiIcon name="trash" :size="13" />
      </button>
    </div>

    <div
      class="kiwi-task-progress-track"
      role="progressbar"
      :aria-valuenow="percent"
      aria-valuemin="0"
      aria-valuemax="100"
      :aria-label="label"
    >
      <i class="kiwi-task-progress-fill" :style="{ width: `${percent}%` }" />
    </div>

    <p v-if="!stats" class="kiwi-task-progress-empty">
      在上方或下方插入任务清单后，这里会自动统计完成度。
      <button
        v-if="editable"
        type="button"
        class="kiwi-task-progress-inline-action"
        @mousedown.prevent
        @click.stop="insertStarterList"
      >
        插入示例清单
      </button>
    </p>

    <div v-if="editable && settingsOpen" class="kiwi-task-progress-settings">
      <div class="kiwi-task-progress-field">
        <span class="kiwi-task-progress-field-label">标题</span>
        <input
          v-model="titleDraft"
          class="kiwi-task-progress-input"
          maxlength="80"
          placeholder="待办进度"
          @mousedown.stop
          @keydown.stop
          @keydown.enter.prevent="commitTitle"
          @blur="commitTitle"
        />
      </div>

      <div class="kiwi-task-progress-options">
        <label class="kiwi-task-progress-check">
          <input
            type="checkbox"
            :checked="showCount"
            @mousedown.stop
            @change="toggle('showCount', $event)"
          />
          显示完成数
        </label>
        <label class="kiwi-task-progress-check">
          <input
            type="checkbox"
            :checked="showPercent"
            @mousedown.stop
            @change="toggle('showPercent', $event)"
          />
          显示百分比
        </label>
      </div>

      <div class="kiwi-task-progress-field">
        <span class="kiwi-task-progress-field-label">绑定清单</span>
        <select
          class="kiwi-task-progress-select"
          :value="bind"
          @mousedown.stop
          @change="setBind"
        >
          <option value="auto">最近的清单</option>
          <option value="next">下方清单</option>
          <option value="prev">上方清单</option>
        </select>
      </div>

      <div class="kiwi-task-progress-field">
        <span class="kiwi-task-progress-field-label">配色</span>
        <div class="kiwi-task-progress-colors">
          <button
            v-for="tone in TASK_PROGRESS_COLORS"
            :key="tone"
            type="button"
            class="kiwi-task-progress-swatch"
            :class="[`tone-${tone}`, { 'is-active': tone === color }]"
            :title="TASK_PROGRESS_COLOR_LABELS[tone]"
            :aria-label="TASK_PROGRESS_COLOR_LABELS[tone]"
            @mousedown.prevent
            @click.stop="setColor(tone)"
          >
            <span />
          </button>
        </div>
      </div>
    </div>
  </NodeViewWrapper>
</template>

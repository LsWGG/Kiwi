<script setup lang="ts">
/** JSON 预览：轻量可折叠树，默认展开前两层，超大数组只渲染前 200 项。 */
import { computed, ref } from 'vue'

const props = withDefaults(
  defineProps<{
    value: unknown
    label?: string
    depth?: number
  }>(),
  { label: '', depth: 0 },
)

const MAX_ITEMS = 200

const isArray = computed(() => Array.isArray(props.value))
const isObject = computed(
  () => !!props.value && typeof props.value === 'object' && !isArray.value,
)
const isBranch = computed(() => isArray.value || isObject.value)

const entries = computed<[string, unknown][]>(() => {
  if (isArray.value) {
    return (props.value as unknown[]).map((item, index) => [String(index), item])
  }
  if (isObject.value) return Object.entries(props.value as Record<string, unknown>)
  return []
})

const shown = computed(() => entries.value.slice(0, MAX_ITEMS))
const hiddenCount = computed(() => Math.max(0, entries.value.length - MAX_ITEMS))

// 根节点与前两层默认展开，深层结构折叠，避免大文件一次渲染过多节点。
const expanded = ref(props.depth < 2)

function toggle() {
  expanded.value = !expanded.value
}

function valueClass(value: unknown) {
  if (value === null) return 'is-null'
  if (typeof value === 'string') return 'is-string'
  if (typeof value === 'number') return 'is-number'
  if (typeof value === 'boolean') return 'is-boolean'
  return ''
}

function valueText(value: unknown) {
  if (typeof value === 'string') return `"${value}"`
  return String(value)
}
</script>

<template>
  <div class="json-node">
    <div v-if="isBranch" class="json-line">
      <button
        type="button"
        class="json-caret"
        :class="{ 'is-open': expanded }"
        :aria-label="expanded ? '收起' : '展开'"
        @click="toggle"
      >
        <span class="json-caret-glyph">▸</span>
      </button>
      <button type="button" class="json-branch" @click="toggle">
        <span v-if="label" class="json-key">{{ label }}<span class="json-punct">:</span></span>
        <span class="json-brace">{{ isArray ? '[' : '{' }}</span>
        <span class="json-count">{{ entries.length }} 项</span>
        <span class="json-brace">{{ isArray ? ']' : '}' }}</span>
      </button>
    </div>

    <div v-else class="json-line">
      <span class="json-caret-spacer" />
      <span v-if="label" class="json-key">{{ label }}<span class="json-punct">:</span></span>
      <span class="json-value" :class="valueClass(value)">{{ valueText(value) }}</span>
    </div>

    <div v-if="isBranch && expanded" class="json-children">
      <JsonTree
        v-for="[key, child] in shown"
        :key="key"
        :label="key"
        :value="child"
        :depth="depth + 1"
      />
      <p v-if="hiddenCount" class="json-more">… 仅展开前 {{ MAX_ITEMS }} 项，共 {{ entries.length }} 项</p>
    </div>
  </div>
</template>

<style scoped>
.json-node {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 12px;
  line-height: 1.7;
  color: #334155;
}
.json-line {
  display: flex;
  align-items: flex-start;
  gap: 2px;
  min-height: 20px;
}
.json-caret,
.json-caret-spacer {
  flex: 0 0 16px;
  width: 16px;
  height: 20px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}
.json-caret {
  color: #94a3b8;
  border-radius: 4px;
}
.json-caret:hover {
  color: rgb(var(--kiwi-600));
  background: rgb(var(--kiwi-50));
}
.json-caret-glyph {
  display: inline-block;
  font-size: 9px;
  transition: transform 0.12s ease;
}
.json-caret.is-open .json-caret-glyph {
  transform: rotate(90deg);
}
.json-branch {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  border-radius: 4px;
  padding: 0 3px;
  text-align: left;
}
.json-branch:hover {
  background: rgb(248 250 252);
}
.json-key {
  color: #0f172a;
  font-weight: 500;
}
.json-punct {
  color: #94a3b8;
  margin-left: 1px;
}
.json-brace {
  color: #64748b;
}
.json-count {
  color: #94a3b8;
  font-size: 11px;
}
.json-value.is-string {
  color: #047857;
  white-space: pre-wrap;
  word-break: break-word;
}
.json-value.is-number {
  color: #b45309;
}
.json-value.is-boolean {
  color: #7c3aed;
}
.json-value.is-null {
  color: #94a3b8;
  font-style: italic;
}
.json-children {
  margin-left: 7px;
  padding-left: 10px;
  border-left: 1px dashed #e2e8f0;
}
.json-more {
  margin: 2px 0 2px 18px;
  color: #94a3b8;
  font-size: 11px;
}
</style>

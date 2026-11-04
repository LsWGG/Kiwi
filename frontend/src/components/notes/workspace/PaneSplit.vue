<script setup lang="ts">
/**
 * 分栏布局节点：叶子渲染单栏，split 按 row/column 递归渲染子栏与拖动分隔条。
 * 根节点也可能是单栏（只有一篇笔记时无需 split）。
 */
import type { PaneNode } from './paneLayout'
import WorkspacePane from './WorkspacePane.vue'
import PaneDivider from './PaneDivider.vue'

defineProps<{
  node: PaneNode
  activePaneId: string | null
}>()

const emit = defineEmits<{
  (e: 'close-pane', paneId: string): void
  (e: 'open-info'): void
  (e: 'open-backlink', noteId: string, mentionId?: string): void
  (e: 'open-note', noteId: string): void
}>()
</script>

<template>
  <WorkspacePane
    v-if="node.type === 'pane'"
    :pane="node"
    :active="node.id === activePaneId"
    @close="(id: string) => emit('close-pane', id)"
    @open-info="emit('open-info')"
    @open-backlink="(id: string, mentionId?: string) => emit('open-backlink', id, mentionId)"
    @open-note="(id: string) => emit('open-note', id)"
  />
  <div
    v-else
    class="flex h-full w-full min-h-0 min-w-0"
    :class="node.direction === 'row' ? 'flex-row' : 'flex-col'"
  >
    <template v-for="(child, index) in node.children" :key="child.id">
      <PaneDivider
        v-if="index > 0"
        :split-id="node.id"
        :index="index - 1"
        :direction="node.direction"
      />
      <div
        class="relative min-h-0 min-w-0 overflow-hidden"
        :style="{ flexGrow: node.sizes[index] ?? 1, flexBasis: 0 }"
      >
        <PaneSplit
          v-if="child.type === 'split'"
          :node="child"
          :active-pane-id="activePaneId"
          @close-pane="(id: string) => emit('close-pane', id)"
          @open-info="emit('open-info')"
          @open-backlink="(id: string, mentionId?: string) => emit('open-backlink', id, mentionId)"
          @open-note="(id: string) => emit('open-note', id)"
        />
        <WorkspacePane
          v-else
          :pane="child"
          :active="child.id === activePaneId"
          @close="(id: string) => emit('close-pane', id)"
          @open-info="emit('open-info')"
          @open-backlink="(id: string, mentionId?: string) => emit('open-backlink', id, mentionId)"
          @open-note="(id: string) => emit('open-note', id)"
        />
      </div>
    </template>
  </div>
</template>

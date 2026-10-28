<script setup lang="ts">
/** 桌面版的 YouTube 占位块：保留节点与 Markdown 数据，不创建远程 iframe。 */
import { computed } from 'vue'
import { NodeViewWrapper, nodeViewProps } from '@tiptap/vue-3'
import KiwiIcon from '@/components/ui/KiwiIcon.vue'

const props = defineProps(nodeViewProps)
const src = computed(() => String(props.node.attrs.src || ''))
</script>

<template>
  <NodeViewWrapper class="my-3" contenteditable="false">
    <div
      class="flex items-center gap-3 rounded-xl border border-dashed border-slate-300 bg-slate-50/70 px-4 py-3"
    >
      <span class="grid h-10 w-10 shrink-0 place-items-center rounded-lg bg-slate-200/70 text-slate-400">
        <KiwiIcon name="video" :size="18" />
      </span>
      <div class="min-w-0">
        <p class="text-[12.5px] font-medium text-slate-600">YouTube 视频</p>
        <p v-if="src" class="truncate font-mono text-[10.5px] text-slate-400">{{ src }}</p>
        <p class="mt-0.5 text-[10.5px] text-slate-400">桌面版已禁用外部视频嵌入</p>
      </div>
    </div>
  </NodeViewWrapper>
</template>

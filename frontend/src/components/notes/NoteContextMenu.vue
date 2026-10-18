<script setup lang="ts">
/** 目录树右键菜单。 */
import { computed, nextTick, ref, watch } from 'vue'
import KiwiIcon from '@/components/ui/KiwiIcon.vue'
import type { ExportAction } from './noteExport'
import type { TreeRow } from './types'

const props = withDefaults(
  defineProps<{
    open: boolean
    x: number
    y: number
    row: TreeRow | null
    selectionCount?: number
    exportActions?: ExportAction[]
  }>(),
  { selectionCount: 1, exportActions: () => [] },
)

const emit = defineEmits<{
  (e: 'rename'): void
  (e: 'pin'): void
  (e: 'new-folder'): void
  (e: 'copy'): void
  (e: 'move-kb'): void
  (e: 'emoji'): void
  (e: 'tags'): void
  (e: 'archive'): void
  (e: 'export', key: string): void
  (e: 'delete'): void
  (e: 'close'): void
}>()

const panelEl = ref<HTMLElement | null>(null)
const pos = ref({ left: '0px', top: '0px' })

/**
 * 菜单挂到 <html> 下，外层用视口坐标定位、内层应用 --ui-scale。
 * 若把 zoom 加在定位元素本身，left/top 也会被缩放，在 4K 下会飘到右下方。
 */
function place() {
  if (!props.open) return
  void nextTick(() => {
    const rect = panelEl.value?.getBoundingClientRect()
    const width = rect?.width ?? 176
    const height = rect?.height ?? 160
    pos.value = {
      left: `${Math.max(8, Math.min(props.x, window.innerWidth - width - 8))}px`,
      top: `${Math.max(8, Math.min(props.y, window.innerHeight - height - 8))}px`,
    }
  })
}

watch(() => [props.open, props.x, props.y], place, { immediate: true })

const isFolder = computed(() => props.row?.type === 'folder')
/** 「收件箱」始终置顶，无需再切换。 */
const isInbox = computed(() => isFolder.value && !!props.row?.inbox)
const pinned = computed(() =>
  isFolder.value
    ? !!props.row?.folder?.pinned
    : !!props.row?.note?.props_json?.pinned,
)
/** 多选时只保留批量删除，避免对整组选择展示单项操作。 */
const batch = computed(() => !isFolder.value && props.selectionCount > 1)
</script>

<template>
  <Teleport to="html">
    <div
      v-if="open"
      class="fixed inset-0 z-[80]"
      @mousedown="emit('close')"
      @contextmenu.prevent="emit('close')"
    >
      <div class="absolute" :style="pos">
        <div
          ref="panelEl"
          class="w-52 rounded-xl border border-slate-200/70 bg-white/95 backdrop-blur-xl shadow-lifted p-1 animate-scale-in"
          :style="{ zoom: 'var(--ui-scale)' }"
          @mousedown.stop
        >
          <template v-if="batch">
            <div class="px-2.5 py-1.5 text-[10.5px] text-slate-400">
              已选 {{ selectionCount }} 项
            </div>
            <button
              type="button"
              class="menu-row !text-rose-500 hover:!bg-rose-50"
              @click="emit('delete'); emit('close')"
            >
              <KiwiIcon name="trash" :size="14" />
              删除选中的 {{ selectionCount }} 项
            </button>
          </template>
          <template v-else>
          <button
            type="button"
            class="menu-row"
            @click="emit('rename'); emit('close')"
          >
            <KiwiIcon name="edit" :size="14" />
            重命名
          </button>
          <button
            v-if="!isInbox"
            type="button"
            class="menu-row"
            @click="emit('pin'); emit('close')"
          >
            <KiwiIcon name="pin" :size="14" :class="pinned ? 'text-kiwi-500' : ''" />
            {{ pinned ? '取消置顶' : '置顶' }}
          </button>
          <button
            v-if="isFolder"
            type="button"
            class="menu-row"
            @click="emit('new-folder'); emit('close')"
          >
            <KiwiIcon name="folder" :size="14" />
            新建子分组
          </button>
          <template v-if="!isFolder">
            <button
              type="button"
              class="menu-row"
              @click="emit('emoji'); emit('close')"
            >
              <KiwiIcon name="smile" :size="14" />
              设置表情
            </button>
            <button
              type="button"
              class="menu-row"
              @click="emit('tags'); emit('close')"
            >
              <KiwiIcon name="hash" :size="14" />
              设置标签
            </button>
            <button
              type="button"
              class="menu-row"
              @click="emit('copy'); emit('close')"
            >
              <KiwiIcon name="copy" :size="14" />
              复制
            </button>
            <button
              type="button"
              class="menu-row"
              @click="emit('move-kb'); emit('close')"
            >
              <KiwiIcon name="arrowRight" :size="14" />
              移动到其他知识库
            </button>
            <button
              type="button"
              class="menu-row"
              @click="emit('archive'); emit('close')"
            >
              <KiwiIcon name="folderOpen" :size="14" />
              归档
            </button>
            <template v-if="exportActions.length">
              <div class="my-1 h-px bg-slate-200/70" />
              <div class="px-2.5 pb-0.5 pt-1 text-[10px] font-medium tracking-wide text-slate-400">
                导出
              </div>
              <button
                v-for="action in exportActions"
                :key="action.key"
                type="button"
                class="menu-row"
                @click="emit('export', action.key); emit('close')"
              >
                <KiwiIcon :name="action.icon" :size="14" />
                <span class="flex-1 truncate text-left">{{ action.label }}</span>
                <span
                  class="shrink-0 rounded border border-slate-200 bg-slate-50 px-1 py-px text-[9px] font-semibold tracking-wide text-slate-400"
                >{{ action.ext }}</span>
              </button>
            </template>
          </template>
          <div class="my-1 h-px bg-slate-200/70" />
          <button
            type="button"
            class="menu-row !text-rose-500 hover:!bg-rose-50"
            @click="emit('delete'); emit('close')"
          >
            <KiwiIcon name="trash" :size="14" />
            移入回收站
          </button>
          </template>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.menu-row {
  @apply w-full flex items-center gap-2 rounded-lg px-2.5 py-1.5 text-[12.5px] text-slate-600 transition-colors hover:bg-kiwi-50;
}
</style>

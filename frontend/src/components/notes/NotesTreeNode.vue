<script setup lang="ts">
/** 目录树单行：文件夹 / 文档 / 数据表 / 链接 / 导入。 */
import { computed, nextTick, ref, watch } from 'vue'
import KiwiIcon from '@/components/ui/KiwiIcon.vue'
import type { DropPos, TreeRow } from './types'

const props = withDefaults(
  defineProps<{
    row: TreeRow
    activeId?: string | null
    open?: boolean
    renaming?: boolean
    dragging?: boolean
    selected?: boolean
    dropTarget?: DropPos | null
  }>(),
  { activeId: null, open: false, renaming: false, dragging: false, selected: false, dropTarget: null },
)

const emit = defineEmits<{
  (e: 'select', row: TreeRow, event: MouseEvent): void
  (e: 'toggle', row: TreeRow): void
  (e: 'menu', event: MouseEvent, row: TreeRow): void
  (e: 'dragstart', event: DragEvent, row: TreeRow): void
  (e: 'dragover', event: DragEvent, row: TreeRow): void
  (e: 'dragleave', event: DragEvent, row: TreeRow): void
  (e: 'drop', event: DragEvent, row: TreeRow): void
  (e: 'rename', row: TreeRow, name: string): void
  (e: 'rename-cancel'): void
  (e: 'unpin'): void
}>()

const input = ref<HTMLInputElement | null>(null)
const draft = ref('')

const isFolder = computed(() => props.row.type === 'folder')
const isInbox = computed(() => isFolder.value && !!props.row.inbox)
const pinned = computed(() =>
  isFolder.value ? !!props.row.folder?.pinned : !!props.row.note?.props_json?.pinned,
)
const kind = computed(() => props.row.note?.kind ?? 'doc')
const label = computed(() =>
  isFolder.value ? (props.row.folder?.name ?? '') : (props.row.note?.title || '无标题'),
)
/** 置顶区是快捷副本；打开笔记时高亮并追踪原目录中的那一行。 */
const active = computed(
  () => !isFolder.value && !props.row.hoisted && props.row.id === props.activeId,
)
/** 自定义表情优先于类型图标 */
const emoji = computed(() => {
  if (isFolder.value) return ''
  return String(props.row.note?.props_json?.emoji ?? '').trim()
})

const icon = computed(() => {
  if (isFolder.value) return props.open ? 'folderOpen' : 'folder'
  switch (kind.value) {
    case 'database':
      return 'database'
    case 'canvas':
      return 'pen'
    case 'link':
      return 'link2'
    case 'import':
      // 导入文档：带下载箭头的文件图标，与普通文档区分
      return 'fileImport'
    case 'notebook':
      return 'notebook'
    default:
      return 'fileText'
  }
})
const iconClass = computed(() => {
  if (isInbox.value) return 'text-orange-500'
  if (isFolder.value) return 'text-amber-400/90'
  switch (kind.value) {
    case 'database':
      return 'text-kiwi-500'
    case 'canvas':
      return 'text-violet-500'
    case 'link':
      return 'text-sky-500'
    case 'import':
      return 'text-emerald-500/90'
    case 'notebook':
      return 'text-indigo-500'
    default:
      return 'text-blue-500'
  }
})

watch(
  () => props.renaming,
  async (on) => {
    if (!on) return
    draft.value = label.value
    await nextTick()
    input.value?.focus()
    input.value?.select()
  },
  { immediate: true },
)

function commit() {
  const name = draft.value.trim()
  if (!name) {
    emit('rename-cancel')
    return
  }
  if (name === label.value) {
    emit('rename-cancel')
    return
  }
  emit('rename', props.row, name)
}

function onInputKey(e: KeyboardEvent) {
  if (e.key === 'Enter') {
    e.preventDefault()
    commit()
  } else if (e.key === 'Escape') {
    e.preventDefault()
    emit('rename-cancel')
  }
}

function onClick(event: MouseEvent) {
  if (props.renaming) return
  if (isFolder.value) emit('toggle', props.row)
  else emit('select', props.row, event)
}
</script>

<template>
  <div
    class="group relative flex items-center gap-1.5 h-8 pr-1.5 rounded-lg cursor-pointer select-none transition-colors"
    :class="[
      isInbox
        ? 'bg-orange-50/80 text-orange-800 hover:bg-orange-100/70'
        : active
          ? 'bg-kiwi-100/80 text-kiwi-800'
          : selected
            ? 'bg-kiwi-50/90 text-kiwi-800 ring-1 ring-inset ring-kiwi-200/70'
            : 'text-slate-600 hover:bg-white/80',
      dragging ? 'opacity-40' : '',
      dropTarget === 'into' ? 'ring-2 ring-kiwi-300 ring-inset bg-kiwi-50/80' : '',
    ]"
    :style="{ paddingLeft: `${6 + row.depth * 14}px` }"
    :data-origin-note="!row.hoisted && !isFolder ? row.id : undefined"
    :title="isInbox ? '收件箱 · 始终置顶' : undefined"
    :draggable="!renaming"
    @click="onClick"
    @contextmenu.prevent.stop="emit('menu', $event, row)"
    @dragstart="emit('dragstart', $event, row)"
    @dragover="emit('dragover', $event, row)"
    @dragleave="emit('dragleave', $event, row)"
    @drop.stop="emit('drop', $event, row)"
  >
    <span
      v-if="dropTarget === 'before'"
      class="absolute left-2 right-2 -top-[1px] h-0.5 rounded-full bg-kiwi-500"
    />
    <span
      v-if="dropTarget === 'after'"
      class="absolute left-2 right-2 -bottom-[1px] h-0.5 rounded-full bg-kiwi-500"
    />

    <button
      v-if="isFolder"
      type="button"
      class="w-4 h-4 grid place-items-center rounded text-slate-400 hover:text-kiwi-600 shrink-0"
      :class="isInbox ? '!text-orange-400 hover:!text-orange-600' : ''"
      :aria-label="open ? '折叠' : '展开'"
      @click.stop="emit('toggle', row)"
    >
      <KiwiIcon
        name="chevronRight"
        :size="12"
        class="transition-transform duration-150"
        :class="open ? 'rotate-90' : ''"
      />
    </button>
    <span v-else class="w-4 shrink-0" />

    <span
      v-if="emoji"
      class="w-4 shrink-0 text-center text-[13px] leading-none"
      aria-hidden="true"
    >{{ emoji }}</span>
    <KiwiIcon v-else :name="icon" :size="14" class="shrink-0" :class="iconClass" />

    <input
      v-if="renaming"
      ref="input"
      v-model="draft"
      class="min-w-0 flex-1 h-6 rounded-md border border-kiwi-300 bg-white px-1.5 text-[12.5px] text-slate-700 outline-none focus:ring-2 focus:ring-kiwi-200"
      @keydown="onInputKey"
      @blur="commit"
      @click.stop
      @dblclick.stop
    />
    <span v-else class="min-w-0 flex-1 truncate text-[12.5px]" :class="active ? 'font-medium' : ''">
      {{ label }}
    </span>
    <button
      v-if="pinned && !isInbox"
      type="button"
      class="shrink-0 grid place-items-center rounded p-0.5 text-kiwi-400 transition-colors hover:bg-kiwi-50 hover:text-kiwi-600"
      title="取消置顶"
      aria-label="取消置顶"
      @click.stop="emit('unpin')"
      @mousedown.stop
      @dblclick.stop
    >
      <KiwiIcon name="pin" :size="10" />
    </button>
    <span
      v-if="!isFolder && row.note?.props_json?.collection_row_id"
      class="shrink-0 rounded border border-slate-200/80 bg-white/80 px-1 text-[9px] leading-4 text-slate-400"
      title="该笔记是数据表（笔记集合）中的一条记录，同时也能作为独立笔记打开、链接和打标签"
    >集合记录</span>
  </div>
</template>

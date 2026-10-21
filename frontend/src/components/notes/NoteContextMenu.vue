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
  (e: 'lock'): void
  (e: 'archive'): void
  (e: 'export', key: string): void
  (e: 'delete'): void
  (e: 'create', kind: string): void
  (e: 'close'): void
}>()

const panelEl = ref<HTMLElement | null>(null)
const pos = ref({ left: '0px', top: '0px' })

/** 右键条目所在层级的新建入口（分组 = 分组内部，笔记 = 笔记所属层级）。 */
const showCreate = ref(false)
const createTriggerEl = ref<HTMLElement | null>(null)
const createPanelEl = ref<HTMLElement | null>(null)
const createPos = ref({ left: '0px', top: '0px' })
let hideCreateTimer: number | null = null
const CREATE_ITEMS = [
  { key: 'doc', label: '文档', icon: 'fileText', tone: 'text-blue-500' },
  { key: 'canvas', label: '画布', icon: 'pen', tone: 'text-violet-500' },
  { key: 'database', label: '数据表', icon: 'database', tone: 'text-kiwi-500' },
  { key: 'sheet', label: '表格', icon: 'table', tone: 'text-emerald-600' },
  { key: 'notebook', label: 'Notebook', icon: 'notebook', tone: 'text-indigo-500' },
  { key: 'import', label: '导入', icon: 'fileImport', tone: 'text-emerald-500' },
  { key: 'link', label: '链接', icon: 'link2', tone: 'text-sky-500' },
  { key: 'template', label: '模板', icon: 'layoutTemplate', tone: 'text-kiwi-500' },
  { key: 'folder', label: '子分组', icon: 'folder', tone: 'text-amber-400' },
] as const

watch(
  () => props.open,
  (open) => {
    if (!open) {
      showCreate.value = false
      cancelHideCreate()
    }
  },
)
watch(showCreate, (visible) => {
  if (visible) placeCreate()
})

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

/**
 * 「在此层级新建」使用二级飞出列表，而不是在主菜单里内嵌展开。
 * 优先贴右侧；右侧空间不足时翻到左侧，避免飞出屏幕。
 */
function placeCreate() {
  if (!props.open || !showCreate.value) return
  void nextTick(() => {
    const trigger = createTriggerEl.value?.getBoundingClientRect()
    const panel = createPanelEl.value?.getBoundingClientRect()
    if (!trigger) return
    const width = panel?.width ?? 160
    const height = panel?.height ?? 260
    const gap = 4
    let left = trigger.right + gap
    if (left + width > window.innerWidth - 8) {
      left = Math.max(8, trigger.left - width - gap)
    }
    const top = Math.max(8, Math.min(trigger.top - 4, window.innerHeight - height - 8))
    createPos.value = { left: `${left}px`, top: `${top}px` }
  })
}

function cancelHideCreate() {
  if (hideCreateTimer !== null) {
    window.clearTimeout(hideCreateTimer)
    hideCreateTimer = null
  }
}
function openCreate() {
  cancelHideCreate()
  showCreate.value = true
}
function scheduleHideCreate() {
  cancelHideCreate()
  hideCreateTimer = window.setTimeout(() => {
    hideCreateTimer = null
    showCreate.value = false
  }, 160)
}

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
/** 笔记下的新建目标是「子笔记」，分组层级才允许继续建子分组。 */
const createItems = computed(() =>
  isFolder.value ? CREATE_ITEMS : CREATE_ITEMS.filter((item) => item.key !== 'folder'),
)
const createTitle = computed(() =>
  isFolder.value
    ? '新建到当前分组'
    : `新建到「${props.row?.note?.title || '无标题'}」下级`,
)
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
            ref="createTriggerEl"
            type="button"
            class="menu-row"
            :class="showCreate ? 'bg-kiwi-50 text-kiwi-700' : ''"
            @mouseenter="openCreate"
            @mouseleave="scheduleHideCreate"
            @click.stop="openCreate"
          >
            <KiwiIcon name="plus" :size="14" />
            {{ isFolder ? '在此层级新建' : '新建子笔记' }}
            <KiwiIcon
              name="chevronRight"
              :size="11"
              class="ml-auto text-slate-300"
            />
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
              @click="emit('lock'); emit('close')"
            >
              <KiwiIcon :name="row?.note?.is_locked ? 'unlock' : 'lock'" :size="14" />
              {{ row?.note?.is_locked ? '密码锁（已上锁）' : '设置密码锁' }}
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

      <!-- 二级飞出列表：与主菜单分离定位，避免把主菜单撑高/撑宽 -->
      <div
        v-if="showCreate"
        class="absolute z-[81]"
        :style="createPos"
        @mousedown.stop
        @mouseenter="cancelHideCreate"
        @mouseleave="scheduleHideCreate"
        @contextmenu.prevent
      >
        <div
          ref="createPanelEl"
          class="w-44 rounded-xl border border-slate-200/70 bg-white/95 p-1 shadow-lifted backdrop-blur-xl animate-scale-in"
          :style="{ zoom: 'var(--ui-scale)' }"
        >
          <div class="truncate px-2.5 pb-1 pt-1.5 text-[10px] font-medium tracking-wide text-slate-400">
            {{ createTitle }}
          </div>
          <button
            v-for="item in createItems"
            :key="item.key"
            type="button"
            class="menu-row"
            @click="emit('create', item.key); emit('close')"
          >
            <KiwiIcon :name="item.icon" :size="14" :class="item.tone + ' shrink-0'" />
            <span class="truncate">{{ item.label }}</span>
          </button>
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

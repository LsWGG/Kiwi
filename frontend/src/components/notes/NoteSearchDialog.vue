<script setup lang="ts">
/** 全局笔记检索：全文关键词 + 状态 / 类型 / 分组 / 标签 / 更新时间组合筛选。 */
import { computed, nextTick, ref, watch } from 'vue'
import { useKbsStore } from '@/stores/kbs'
import {
  useNotesStore,
  type NoteSearchItem,
  type NoteSearchResult,
} from '@/stores/notes'
import KiwiIcon from '@/components/ui/KiwiIcon.vue'
import { toast } from '@/components/ui/toast'

const props = defineProps<{ open: boolean }>()
const emit = defineEmits<{
  (e: 'close'): void
  (e: 'open-note', id: string, kbId?: string): void
}>()

const kbs = useKbsStore()
const notes = useNotesStore()

const query = ref('')
const searchKbId = ref(kbs.currentKbId ?? '')
const status = ref<'all' | 'active' | 'archived' | 'trash'>('all')
const kind = ref('')
const folderId = ref('')
const selectedTags = ref<string[]>([])
const updatedFrom = ref('')
const updatedTo = ref('')
const loading = ref(false)
const result = ref<NoteSearchResult | null>(null)
const inputRef = ref<HTMLInputElement | null>(null)
const listRef = ref<HTMLElement | null>(null)
const activeIndex = ref(0)
const showDate = ref(false)
const elapsed = ref(0)
let timer: number | null = null
let seq = 0

const KIND_OPTIONS = [
  { value: '', label: '全部类型' },
  { value: 'doc', label: '文档' },
  { value: 'database', label: '数据表' },
  { value: 'canvas', label: '画布' },
  { value: 'notebook', label: 'Notebook' },
  { value: 'import', label: '导入' },
  { value: 'link', label: '链接' },
]

const STATUS_OPTIONS = [
  { value: 'all', label: '活跃 + 归档' },
  { value: 'active', label: '仅活跃' },
  { value: 'archived', label: '仅归档' },
  { value: 'trash', label: '回收站' },
]

// 跨库检索时，当前库的分组 / 标签筛选不适用
const sameKb = computed(() => searchKbId.value === kbs.currentKbId)
const kbName = (id: string) => kbs.kbs.find((k) => k.id === id)?.name ?? ''

const folderOptions = computed(() => {
  if (!sameKb.value) return []
  const out: Array<{ id: string; label: string }> = []
  const walk = (parentId: string | null, depth: number) => {
    for (const folder of notes.folders.filter((f) => f.parent_id === parentId)) {
      out.push({ id: folder.id, label: `${'　'.repeat(depth)}${folder.name}` })
      walk(folder.id, depth + 1)
    }
  }
  walk(null, 0)
  return out
})

const subTags = computed(() => {
  const byParent = new Map<string | null, typeof notes.tags>()
  for (const tag of notes.tags) {
    const key = tag.parent_id ?? null
    const list = byParent.get(key) || []
    list.push(tag)
    byParent.set(key, list)
  }
  return byParent
})

const tagTree = computed(() => {
  const out: Array<{ id: string; name: string; usage: number; depth: number }> = []
  const walk = (parentId: string | null, depth: number) => {
    for (const tag of subTags.value.get(parentId) || []) {
      out.push({ id: tag.id, name: tag.name, usage: tag.usage_count, depth })
      walk(tag.id, depth + 1)
    }
  }
  walk(null, 0)
  return out
})

const hasFilter = computed(
  () =>
    !!query.value.trim() ||
    status.value !== 'all' ||
    !!kind.value ||
    !!folderId.value ||
    selectedTags.value.length > 0 ||
    !!updatedFrom.value ||
    !!updatedTo.value,
)

const terms = computed(() =>
  query.value
    .trim()
    .split(/\s+/)
    .filter(Boolean),
)

const items = computed(() => result.value?.items ?? [])
watch(items, () => {
  activeIndex.value = 0
})

const dateActive = computed(() => !!(updatedFrom.value || updatedTo.value))
const dateLabel = computed(() => {
  if (!dateActive.value) return '更新时间'
  return `${updatedFrom.value || '不限'} ~ ${updatedTo.value || '不限'}`
})

const folderMap = computed(() => new Map(notes.folders.map((f) => [f.id, f])))
function folderPath(id: string | null): string {
  if (!id) return ''
  const names: string[] = []
  let current = folderMap.value.get(id)
  let guard = 0
  while (current && guard++ < 20) {
    names.unshift(current.name)
    current = current.parent_id ? folderMap.value.get(current.parent_id) : undefined
  }
  return names.join(' / ')
}

function escapeHtml(value: string): string {
  return value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

function highlight(value: string): string {
  let html = escapeHtml(value || '')
  for (const term of terms.value) {
    html = html.replace(
      new RegExp(`(${escapeRegExp(escapeHtml(term))})`, 'gi'),
      '<mark class="bg-amber-100/90 text-amber-800 rounded px-0.5">$1</mark>',
    )
  }
  return html
}

function toggleTag(id: string) {
  selectedTags.value = selectedTags.value.includes(id)
    ? selectedTags.value.filter((t) => t !== id)
    : [...selectedTags.value, id]
}

function resetFilters() {
  query.value = ''
  status.value = 'all'
  kind.value = ''
  folderId.value = ''
  selectedTags.value = []
  updatedFrom.value = ''
  updatedTo.value = ''
  showDate.value = false
}

async function runSearch() {
  if (!kbs.currentKbId) return
  seq += 1
  const mySeq = seq
  loading.value = true
  const startedAt = performance.now()
  try {
    const res = await notes.searchNotes({
      q: query.value,
      kb_id: searchKbId.value || undefined,
      status: status.value,
      kind: kind.value || undefined,
      folder_id: folderId.value || undefined,
      tag_ids: selectedTags.value,
      updated_from: updatedFrom.value ? `${updatedFrom.value}T00:00:00` : undefined,
      updated_to: updatedTo.value ? `${updatedTo.value}T23:59:59` : undefined,
      limit: 100,
    })
    if (mySeq === seq) {
      result.value = res
      elapsed.value = Math.round(performance.now() - startedAt)
    }
  } catch (e: any) {
    if (mySeq === seq) {
      result.value = { total: 0, items: [] }
      toast.error(e.message || '搜索失败')
    }
  } finally {
    if (mySeq === seq) loading.value = false
  }
}

function scheduleSearch() {
  if (timer !== null) window.clearTimeout(timer)
  timer = window.setTimeout(() => {
    timer = null
    void runSearch()
  }, 260)
}

watch(
  [query, status, kind, folderId, selectedTags, updatedFrom, updatedTo],
  scheduleSearch,
  { deep: true },
)

watch(searchKbId, () => {
  folderId.value = ''
  selectedTags.value = []
  scheduleSearch()
})

watch(
  () => props.open,
  async (open) => {
    if (!open) {
      if (timer !== null) window.clearTimeout(timer)
      return
    }
    if (!notes.tags.length) void notes.fetchTags().catch(() => {})
    if (!notes.folders.length) void notes.fetchTree().catch(() => {})
    searchKbId.value = kbs.currentKbId ?? ''
    await nextTick()
    inputRef.value?.focus()
    await runSearch()
  },
)

function openItem(item: NoteSearchItem) {
  if (item.note.status === 'trash') {
    toast.error('回收站中的笔记需先恢复后才能打开')
    return
  }
  emit('open-note', item.note.id, item.note.kb_id)
  emit('close')
}

/** 结果摘要：画布/链接等结构化条目比正文片段更有信息量。 */
function summaryOf(item: NoteSearchItem): string {
  const note = item.note
  if (note.kind === 'canvas') {
    const doc = note.props_json?.canvas_doc as
      | { nodes?: unknown[]; edges?: unknown[]; theme?: string }
      | undefined
    const nodes = Array.isArray(doc?.nodes) ? doc.nodes.length : 0
    const edges = Array.isArray(doc?.edges) ? doc.edges.length : 0
    return `画布 · ${nodes} 个节点 · ${edges} 条连线`
  }
  if (note.kind === 'notebook') {
    const doc = note.props_json?.notebook_doc as
      | { cells?: Array<{ type?: string }> }
      | undefined
    const cells = Array.isArray(doc?.cells) ? doc.cells.length : 0
    const code = Array.isArray(doc?.cells)
      ? doc.cells.filter((cell) => cell.type === 'code').length
      : 0
    return `Notebook · ${cells} 个单元格 · ${code} 个代码单元格`
  }
  if (note.kind === 'link') {
    const link = note.props_json?.link as
      | { site?: string; url?: string; excerpt?: string }
      | undefined
    return link?.excerpt || link?.site || link?.url || item.snippet
  }
  return item.snippet
}

function hasSummary(item: NoteSearchItem): boolean {
  const text = (summaryOf(item) || '').trim()
  return !!text && text !== (item.note.title || '').trim()
}

/** 只有存在分组 / 标签 / 非标题命中时才占一行元信息，避免列表被撑高。 */
function showMeta(item: NoteSearchItem): boolean {
  return (
    !!folderPath(item.note.folder_id) ||
    item.note.tags.length > 0 ||
    item.matched_fields.some((f) => f !== 'title')
  )
}

function dateLabelOf(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  const now = new Date()
  if (d.toDateString() === now.toDateString()) {
    return d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
  }
  if (d.getFullYear() === now.getFullYear()) {
    return d.toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit' })
  }
  return d.toLocaleDateString('zh-CN')
}

function fullDate(iso: string): string {
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? '' : d.toLocaleString('zh-CN')
}

function scrollActiveIntoView() {
  void nextTick(() => {
    listRef.value
      ?.querySelector<HTMLElement>(`[data-search-index="${activeIndex.value}"]`)
      ?.scrollIntoView({ block: 'nearest' })
  })
}

function onInputKeydown(e: KeyboardEvent) {
  if (e.key === 'ArrowDown') {
    e.preventDefault()
    if (!items.value.length) return
    activeIndex.value = (activeIndex.value + 1) % items.value.length
    scrollActiveIntoView()
  } else if (e.key === 'ArrowUp') {
    e.preventDefault()
    if (!items.value.length) return
    activeIndex.value = (activeIndex.value - 1 + items.value.length) % items.value.length
    scrollActiveIntoView()
  } else if (e.key === 'Enter') {
    const item = items.value[activeIndex.value]
    if (item) {
      e.preventDefault()
      openItem(item)
    }
  } else if (e.key === 'Escape') {
    emit('close')
  }
}

const KIND_LABEL: Record<string, string> = {
  doc: '文档',
  database: '数据表',
  canvas: '画布',
  import: '导入',
  link: '链接',
  notebook: 'Notebook',
}
const KIND_ICON: Record<string, string> = {
  doc: 'fileText',
  database: 'table',
  canvas: 'pen',
  import: 'fileImport',
  link: 'link2',
  notebook: 'notebook',
}
const KIND_TILE: Record<string, string> = {
  doc: 'border-slate-200 bg-slate-50 text-slate-500',
  database: 'border-sky-200 bg-sky-50 text-sky-600',
  canvas: 'border-violet-200 bg-violet-50 text-violet-600',
  import: 'border-emerald-200 bg-emerald-50 text-emerald-600',
  link: 'border-amber-200 bg-amber-50 text-amber-600',
  notebook: 'border-indigo-200 bg-indigo-50 text-indigo-600',
}
const MATCH_LABEL: Record<string, string> = {
  title: '标题',
  body: '正文',
  tags: '标签',
  meta: '元数据',
  wiki: '关联 Wiki',
  source: '关联素材',
}
</script>

<template>
  <Teleport to="html">
    <div
      v-if="open"
      class="fixed inset-0 z-[90] flex items-start justify-center bg-slate-900/30 px-4 pt-[7vh] backdrop-blur-sm"
      @mousedown.self="emit('close')"
    >
      <div
        class="flex max-h-[82vh] w-full max-w-[820px] animate-scale-in flex-col overflow-hidden rounded-2xl border border-slate-200/80 bg-white/95 shadow-2xl"
        :style="{ zoom: 'var(--ui-scale)' }"
      >
        <!-- 搜索框 -->
        <div class="flex h-[52px] shrink-0 items-center gap-2.5 border-b border-slate-200/60 px-4">
          <KiwiIcon
            :name="loading ? 'loader' : 'search'"
            :size="16"
            :spin="loading"
            class="shrink-0 text-kiwi-500"
          />
          <input
            ref="inputRef"
            v-model="query"
            name="note-search"
            autocomplete="off"
            spellcheck="false"
            class="min-w-0 flex-1 bg-transparent text-[14px] text-slate-700 outline-none placeholder:text-slate-300"
            placeholder="搜索标题、正文、标签、链接元数据…"
            @keydown="onInputKeydown"
          />
          <span
            v-if="result && !loading"
            class="shrink-0 rounded-full bg-slate-100 px-2 py-0.5 text-[10px] tabular-nums text-slate-500"
          >
            {{ result.total }} 条
          </span>
          <span v-else-if="loading" class="shrink-0 text-[10px] text-slate-400">搜索中…</span>
          <button
            v-if="hasFilter"
            class="shrink-0 text-[10.5px] text-slate-400 transition-colors hover:text-kiwi-600"
            @click="resetFilters"
          >
            清除筛选
          </button>
          <button class="kiwi-btn-ghost shrink-0 !p-1.5" title="关闭" @click="emit('close')">
            <KiwiIcon name="close" :size="13" />
          </button>
        </div>

        <!-- 筛选条 -->
        <div class="shrink-0 border-b border-slate-100 bg-slate-50/50 px-4 py-2">
          <div class="flex flex-wrap items-center gap-1.5">
            <select v-model="searchKbId" class="search-select max-w-[150px]" title="搜索的知识库">
              <option v-for="kb in kbs.kbs" :key="kb.id" :value="kb.id">{{ kb.name }}</option>
            </select>
            <select v-model="status" class="search-select">
              <option v-for="o in STATUS_OPTIONS" :key="o.value" :value="o.value">{{ o.label }}</option>
            </select>
            <select v-model="kind" class="search-select">
              <option v-for="o in KIND_OPTIONS" :key="o.value" :value="o.value">{{ o.label }}</option>
            </select>
            <select v-model="folderId" class="search-select max-w-[160px]" :disabled="!sameKb">
              <option value="">全部分组</option>
              <option v-for="f in folderOptions" :key="f.id" :value="f.id">{{ f.label }}</option>
            </select>
            <button
              type="button"
              class="search-toggle"
              :class="dateActive && 'search-toggle-active'"
              @click="showDate = !showDate"
            >
              <KiwiIcon name="calendar" :size="11" />
              <span class="max-w-[150px] truncate">{{ dateLabel }}</span>
              <KiwiIcon
                name="chevron"
                :size="10"
                class="transition-transform"
                :class="showDate && 'rotate-180'"
              />
            </button>
            <span class="ml-auto hidden text-[9.5px] text-slate-400 sm:inline">
              标题 / 正文 / 标签 / 元数据
            </span>
          </div>

          <div v-if="showDate" class="mt-2 flex flex-wrap items-center gap-1.5">
            <input v-model="updatedFrom" type="date" class="search-date" />
            <span class="text-[10px] text-slate-400">至</span>
            <input v-model="updatedTo" type="date" class="search-date" />
            <button
              v-if="dateActive"
              type="button"
              class="text-[10px] text-slate-400 hover:text-rose-500"
              @click="updatedFrom = ''; updatedTo = ''"
            >
              清除日期
            </button>
          </div>

          <div
            v-if="tagTree.length && sameKb"
            class="mt-1.5 flex items-center gap-1 overflow-x-auto pb-0.5"
          >
            <span class="shrink-0 pr-0.5 text-[9.5px] text-slate-400">标签</span>
            <button
              v-for="tag in tagTree"
              :key="tag.id"
              class="shrink-0 rounded-full border px-2 py-0.5 text-[10px] transition-colors"
              :class="
                selectedTags.includes(tag.id)
                  ? 'border-kiwi-300 bg-kiwi-50 text-kiwi-700'
                  : 'border-slate-200 bg-white text-slate-500 hover:border-kiwi-200'
              "
              @click="toggleTag(tag.id)"
            >
              {{ tag.name }}
              <span class="text-[9px] text-slate-300">{{ tag.usage }}</span>
            </button>
          </div>
        </div>

        <!-- 结果 -->
        <div ref="listRef" class="min-h-0 flex-1 overflow-y-auto p-1.5">
          <div
            v-if="!result"
            class="grid h-full place-items-center py-16 text-center text-[12px] text-slate-400"
          >
            输入关键词开始检索
          </div>

          <div v-else-if="loading && !items.length" class="space-y-0.5 p-1">
            <div v-for="i in 6" :key="i" class="flex items-start gap-2.5 rounded-xl px-2.5 py-2">
              <div class="mt-0.5 h-7 w-7 shrink-0 animate-pulse rounded-lg bg-slate-100" />
              <div class="min-w-0 flex-1 space-y-1.5 py-0.5">
                <div class="h-2.5 w-2/5 animate-pulse rounded bg-slate-100" />
                <div class="h-2 w-4/5 animate-pulse rounded bg-slate-50" />
              </div>
            </div>
          </div>

          <div v-else-if="!items.length" class="grid h-full place-items-center px-6 py-16 text-center">
            <div>
              <div
                class="mx-auto mb-3 grid h-11 w-11 place-items-center rounded-2xl bg-gradient-to-br from-kiwi-100 to-kiwi-50 text-kiwi-400"
              >
                <KiwiIcon name="search" :size="20" />
              </div>
              <p class="text-[12.5px] font-medium text-slate-500">没有匹配的笔记</p>
              <p class="mt-1 text-[10.5px] text-slate-400">试试缩短关键词，或减少筛选条件</p>
              <button
                v-if="hasFilter"
                type="button"
                class="mt-3 text-[10.5px] text-kiwi-600 hover:underline"
                @click="resetFilters"
              >
                清除全部筛选
              </button>
            </div>
          </div>

          <template v-else>
            <button
              v-for="(item, i) in items"
              :key="item.note.id"
              type="button"
              :data-search-index="i"
              class="group flex w-full items-start gap-2.5 rounded-xl px-2.5 py-2 text-left transition-colors"
              :class="
                i === activeIndex
                  ? 'bg-kiwi-50/80 ring-1 ring-inset ring-kiwi-100'
                  : 'hover:bg-slate-50'
              "
              @click="openItem(item)"
              @mouseenter="activeIndex = i"
            >
              <span
                class="mt-0.5 grid h-7 w-7 shrink-0 place-items-center rounded-lg border"
                :class="KIND_TILE[item.note.kind] || KIND_TILE.doc"
                :title="KIND_LABEL[item.note.kind] || item.note.kind"
              >
                <KiwiIcon :name="KIND_ICON[item.note.kind] || 'fileText'" :size="13" />
              </span>

              <span class="min-w-0 flex-1">
                <span class="flex items-center gap-1.5">
                  <span
                    class="truncate text-[12.5px] font-medium text-slate-700"
                    v-html="highlight(item.note.title || '无标题')"
                  />
                  <span
                    v-if="!sameKb"
                    class="shrink-0 rounded bg-kiwi-50 px-1.5 py-0.5 text-[9px] text-kiwi-600"
                  >
                    {{ kbName(item.note.kb_id) }}
                  </span>
                  <span
                    v-if="item.note.status !== 'active'"
                    class="shrink-0 rounded px-1.5 py-0.5 text-[9px]"
                    :class="
                      item.note.status === 'archived'
                        ? 'bg-amber-50 text-amber-600'
                        : 'bg-rose-50 text-rose-500'
                    "
                  >
                    {{ item.note.status === 'archived' ? '已归档' : '回收站' }}
                  </span>
                  <span
                    class="ml-auto shrink-0 text-[9.5px] tabular-nums text-slate-400"
                    :title="fullDate(item.note.updated_at)"
                  >
                    {{ dateLabelOf(item.note.updated_at) }}
                  </span>
                </span>

                <span
                  v-if="hasSummary(item)"
                  class="mt-0.5 block truncate text-[10.5px] leading-relaxed text-slate-500"
                  v-html="highlight(summaryOf(item))"
                />

                <span
                  v-if="showMeta(item)"
                  class="mt-0.5 flex items-center gap-1.5 overflow-hidden text-[9.5px] text-slate-400"
                >
                  <span
                    v-if="folderPath(item.note.folder_id)"
                    class="inline-flex min-w-0 items-center gap-0.5 text-slate-400"
                  >
                    <KiwiIcon name="folder" :size="10" class="shrink-0" />
                    <span class="truncate">{{ folderPath(item.note.folder_id) }}</span>
                  </span>
                  <span
                    v-for="tag in item.note.tags.slice(0, 4)"
                    :key="tag"
                    class="shrink-0 text-kiwi-500"
                  >
                    {{ tag }}
                  </span>
                  <span class="ml-auto flex shrink-0 items-center gap-1">
                    <span
                      v-for="field in item.matched_fields.filter((f) => f !== 'title')"
                      :key="field"
                      class="rounded bg-slate-50 px-1 py-0.5 text-[9px] text-slate-400"
                    >
                      {{ MATCH_LABEL[field] || field }}
                    </span>
                  </span>
                </span>
              </span>

              <KiwiIcon
                v-if="i === activeIndex"
                name="arrowRight"
                :size="12"
                class="mt-2 shrink-0 text-kiwi-400"
              />
            </button>
          </template>
        </div>

        <!-- 底部提示 -->
        <div
          class="flex shrink-0 items-center gap-3 border-t border-slate-100 px-4 py-1.5 text-[10px] text-slate-400"
        >
          <span class="inline-flex items-center gap-0.5">
            <kbd class="search-kbd">↑</kbd><kbd class="search-kbd">↓</kbd> 选择
          </span>
          <span><kbd class="search-kbd">Enter</kbd> 打开</span>
          <span><kbd class="search-kbd">Esc</kbd> 关闭</span>
          <span v-if="result" class="ml-auto tabular-nums">
            {{ items.length }} / {{ result.total }} 条
            <template v-if="elapsed"> · {{ elapsed }}ms</template>
          </span>
          <span v-else class="ml-auto">搜索范围：标题 / 正文 / 标签 / 链接与导入元数据</span>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.search-select {
  @apply h-7 rounded-lg border border-slate-200 bg-white px-2 text-[10.5px] text-slate-600 outline-none focus:border-kiwi-300;
}
.search-date {
  @apply h-7 rounded-lg border border-slate-200 bg-white px-1.5 text-[10px] text-slate-600 outline-none focus:border-kiwi-300;
}
.search-toggle {
  @apply inline-flex h-7 items-center gap-1 rounded-lg border border-slate-200 bg-white px-2 text-[10.5px] text-slate-600 outline-none transition-colors hover:border-kiwi-200;
}
.search-toggle-active {
  @apply border-kiwi-300 bg-kiwi-50 text-kiwi-700;
}
.search-select:disabled {
  @apply cursor-not-allowed opacity-50;
}
.search-kbd {
  @apply rounded border border-slate-200 bg-slate-50 px-1 py-0.5 text-[9px] text-slate-500;
}
</style>

<script setup lang="ts">
/** 笔记历史版本：时间线列表 + 内容预览 + 还原 / 删除 / 手动检查点。 */
import { computed, ref, watch } from 'vue'
import KiwiModal from '@/components/ui/KiwiModal.vue'
import KiwiIcon from '@/components/ui/KiwiIcon.vue'
import KiwiConfirm from '@/components/ui/KiwiConfirm.vue'
import MarkdownView from '@/components/editor/MarkdownView.vue'
import { useNotesStore, type NoteOut, type NoteRevision, type NoteRevisionSummary } from '@/stores/notes'
import { toast } from '@/components/ui/toast'

const props = withDefaults(
  defineProps<{
    open: boolean
    noteId: string
    /** 编辑器中的当前正文：用于和选中的历史版本做 diff */
    currentBody?: string
    currentTitle?: string
  }>(),
  { currentBody: '', currentTitle: '' },
)
const emit = defineEmits<{
  (e: 'close'): void
  (e: 'restored', note: NoteOut): void
}>()

const notes = useNotesStore()
const loading = ref(false)
const creating = ref(false)
const restoring = ref(false)
const revisions = ref<NoteRevisionSummary[]>([])
const selectedId = ref<string | null>(null)
const detail = ref<NoteRevision | null>(null)
const detailLoading = ref(false)
const deleteTarget = ref<NoteRevisionSummary | null>(null)

const SOURCE_META: Record<string, { label: string; tone: string; dot: string }> = {
  auto: {
    label: '自动保存',
    tone: 'bg-slate-100/80 text-slate-500 ring-slate-200/70',
    dot: 'bg-slate-300',
  },
  manual: {
    label: '手动检查点',
    tone: 'bg-kiwi-50 text-kiwi-600 ring-kiwi-200/70',
    dot: 'bg-kiwi-500',
  },
  restore: {
    label: '还原前',
    tone: 'bg-amber-50 text-amber-600 ring-amber-200/70',
    dot: 'bg-amber-400',
  },
}

function sourceMeta(source: string) {
  return (
    SOURCE_META[source] || {
      label: source || '版本',
      tone: 'bg-slate-100/80 text-slate-500 ring-slate-200/70',
      dot: 'bg-slate-300',
    }
  )
}

function formatClock(value: string) {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  return date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
}

function formatFullTime(value: string) {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
}

function dayLabel(date: Date) {
  const now = new Date()
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime()
  const day = new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime()
  const days = Math.round((today - day) / 86_400_000)
  if (days <= 0) return '今天'
  if (days === 1) return '昨天'
  if (days < 7) return `${days} 天前`
  return date.toLocaleDateString('zh-CN', {
    year: date.getFullYear() === now.getFullYear() ? undefined : 'numeric',
    month: '2-digit',
    day: '2-digit',
  })
}

interface RevisionGroup {
  key: string
  label: string
  items: NoteRevisionSummary[]
}

/** 按自然日分组，时间线读起来比一串时间戳清晰。 */
const revisionGroups = computed<RevisionGroup[]>(() => {
  const groups: RevisionGroup[] = []
  for (const revision of revisions.value) {
    const date = new Date(revision.created_at)
    const valid = !Number.isNaN(date.getTime())
    const key = valid
      ? `${date.getFullYear()}-${date.getMonth()}-${date.getDate()}`
      : 'unknown'
    const last = groups[groups.length - 1]
    if (last?.key === key) {
      last.items.push(revision)
    } else {
      groups.push({ key, label: valid ? dayLabel(date) : '更早', items: [revision] })
    }
  }
  return groups
})

function isLatest(revision: NoteRevisionSummary) {
  return revisions.value[0]?.id === revision.id
}

const selected = computed(
  () => revisions.value.find((revision) => revision.id === selectedId.value) ?? null,
)

const bodyChars = computed(() => (detail.value?.body_md || '').length)

// ---- 历史版本 ↔ 当前版本 diff ----
type DiffKind = 'same' | 'add' | 'del'
interface DiffLine {
  kind: DiffKind
  text: string
  oldNo: number | null
  newNo: number | null
}
type DiffView = 'preview' | 'diff'
const viewMode = ref<DiffView>('diff')

/** 行级 LCS diff；公共前后缀先裁掉，避免大文档做满矩阵。 */
function buildLineDiff(oldText: string, newText: string): DiffLine[] {
  const split = (text: string) => (text || '').replace(/\r\n?/g, '\n').split('\n')
  const a = split(oldText)
  const b = split(newText)
  // 同一篇笔记的空正文与“单个空行”视为相同
  if (a.length === 1 && a[0] === '' && b.length === 1 && b[0] === '') return []

  let prefix = 0
  while (prefix < a.length && prefix < b.length && a[prefix] === b[prefix]) prefix += 1
  let suffix = 0
  while (
    suffix < a.length - prefix &&
    suffix < b.length - prefix &&
    a[a.length - 1 - suffix] === b[b.length - 1 - suffix]
  ) {
    suffix += 1
  }
  const oldMid = a.slice(prefix, a.length - suffix)
  const newMid = b.slice(prefix, b.length - suffix)
  const out: DiffLine[] = []
  for (let i = 0; i < prefix; i += 1) {
    out.push({ kind: 'same', text: a[i], oldNo: i + 1, newNo: i + 1 })
  }

  const n = oldMid.length
  const m = newMid.length
  let added = 0
  let removed = 0
  // 极端大文档（> 400 万单元格）退化展示：中段整体视为删除 + 新增
  if (n * m > 4_000_000) {
    oldMid.forEach((text, i) =>
      out.push({ kind: 'del', text, oldNo: prefix + i + 1, newNo: null }),
    )
    newMid.forEach((text, i) =>
      out.push({ kind: 'add', text, oldNo: null, newNo: prefix + i + 1 }),
    )
    removed += n
    added += m
  } else {
    const dp: Uint32Array[] = Array.from({ length: n + 1 }, () => new Uint32Array(m + 1))
    for (let i = n - 1; i >= 0; i -= 1) {
      for (let j = m - 1; j >= 0; j -= 1) {
        dp[i][j] =
          oldMid[i] === newMid[j]
            ? dp[i + 1][j + 1] + 1
            : Math.max(dp[i + 1][j], dp[i][j + 1])
      }
    }
    let i = 0
    let j = 0
    while (i < n && j < m) {
      if (oldMid[i] === newMid[j]) {
        out.push({ kind: 'same', text: oldMid[i], oldNo: prefix + i + 1, newNo: prefix + j + 1 })
        i += 1
        j += 1
      } else if (dp[i + 1][j] >= dp[i][j + 1]) {
        out.push({ kind: 'del', text: oldMid[i], oldNo: prefix + i + 1, newNo: null })
        removed += 1
        i += 1
      } else {
        out.push({ kind: 'add', text: newMid[j], oldNo: null, newNo: prefix + j + 1 })
        added += 1
        j += 1
      }
    }
    while (i < n) {
      out.push({ kind: 'del', text: oldMid[i], oldNo: prefix + i + 1, newNo: null })
      removed += 1
      i += 1
    }
    while (j < m) {
      out.push({ kind: 'add', text: newMid[j], oldNo: null, newNo: prefix + j + 1 })
      added += 1
      j += 1
    }
  }

  for (let k = suffix; k > 0; k -= 1) {
    const oldIndex = a.length - k
    const newIndex = b.length - k
    out.push({
      kind: 'same',
      text: a[oldIndex],
      oldNo: oldIndex + 1,
      newNo: newIndex + 1,
    })
  }
  return out
}

const diffLines = computed(() =>
  buildLineDiff(detail.value?.body_md || '', props.currentBody || ''),
)
const diffStats = computed(() => {
  let added = 0
  let removed = 0
  for (const line of diffLines.value) {
    if (line.kind === 'add') added += 1
    else if (line.kind === 'del') removed += 1
  }
  return { added, removed, identical: added === 0 && removed === 0 }
})
function diffPrefix(kind: DiffKind): string {
  if (kind === 'add') return '+'
  if (kind === 'del') return '−'
  return ''
}

async function load(selectId?: string | null) {
  loading.value = true
  try {
    revisions.value = await notes.fetchRevisions(props.noteId)
    const next =
      (selectId && revisions.value.some((r) => r.id === selectId) ? selectId : null) ??
      revisions.value[0]?.id ??
      null
    await select(next)
  } catch (e: any) {
    toast.error(e.message || '加载历史版本失败')
  } finally {
    loading.value = false
  }
}

async function select(id: string | null) {
  selectedId.value = id
  detail.value = null
  if (!id) return
  detailLoading.value = true
  try {
    detail.value = await notes.getRevision(props.noteId, id)
  } catch (e: any) {
    toast.error(e.message || '读取版本内容失败')
  } finally {
    detailLoading.value = false
  }
}

watch(
  () => props.open,
  (open) => {
    if (!open) {
      revisions.value = []
      selectedId.value = null
      detail.value = null
      deleteTarget.value = null
      return
    }
    // 默认展示与当前版本的差异；需要看完整旧稿时再切回「版本内容」。
    viewMode.value = 'diff'
    void load()
  },
)

async function createCheckpoint() {
  creating.value = true
  try {
    const revision = await notes.createRevision(props.noteId)
    toast.success('已保存当前版本')
    await load(revision.id)
  } catch (e: any) {
    toast.error(e.message || '保存版本失败')
  } finally {
    creating.value = false
  }
}

async function restore() {
  const revision = selected.value
  if (!revision) return
  restoring.value = true
  try {
    const note = await notes.restoreRevision(props.noteId, revision.id)
    toast.success('已还原到所选版本')
    emit('restored', note)
    await load()
  } catch (e: any) {
    toast.error(e.message || '还原失败')
  } finally {
    restoring.value = false
  }
}

async function confirmDelete() {
  const target = deleteTarget.value
  deleteTarget.value = null
  if (!target) return
  try {
    await notes.deleteRevision(props.noteId, target.id)
    toast.success('已删除该历史版本')
    await load(selectedId.value === target.id ? null : selectedId.value)
  } catch (e: any) {
    toast.error(e.message || '删除失败')
  }
}
</script>

<template>
  <KiwiModal
    :open="open"
    max-w="max-w-5xl"
    @close="emit('close')"
  >
    <div class="flex h-[min(70vh,640px)] min-h-[380px] flex-col">
      <!-- 顶栏：标题 + 全局操作 -->
      <header class="mb-3.5 flex shrink-0 items-center gap-2.5">
        <span
          class="grid h-9 w-9 shrink-0 place-items-center rounded-xl bg-gradient-to-br from-kiwi-500 to-kiwi-700 text-white shadow-[0_10px_24px_-12px_rgba(90,85,199,0.7)]"
        >
          <KiwiIcon name="layers" :size="17" />
        </span>
        <div class="min-w-0">
          <h2 class="text-[15px] leading-tight font-semibold text-slate-800">历史版本</h2>
          <p class="mt-0.5 text-[10px] text-slate-400">
            自动留档 · 共 <span class="tabular-nums">{{ revisions.length }}</span> 个版本
          </p>
        </div>
        <div class="ml-auto flex items-center gap-1">
          <button
            class="kiwi-btn-ghost !p-1.5"
            title="刷新版本列表"
            :disabled="loading"
            @click="load(selectedId)"
          >
            <KiwiIcon name="refresh" :size="14" :spin="loading" />
          </button>
          <button class="kiwi-btn-ghost !p-1.5" aria-label="关闭" @click="emit('close')">
            <KiwiIcon name="close" :size="15" />
          </button>
        </div>
      </header>

      <div class="flex min-h-0 flex-1 flex-col gap-3 sm:flex-row">
        <!-- 左侧：版本时间线 -->
        <aside
          class="flex max-h-[220px] min-h-0 w-full shrink-0 flex-col overflow-hidden rounded-2xl border border-slate-200/70 bg-white/55 backdrop-blur sm:max-h-none sm:w-[264px]"
        >
          <div class="shrink-0 border-b border-slate-200/60 p-2.5">
            <button
              class="kiwi-btn-primary w-full !py-1.5 !text-[11px]"
              :disabled="creating"
              @click="createCheckpoint"
            >
              <KiwiIcon :name="creating ? 'loader' : 'plus'" :size="12" :spin="creating" />
              保存当前版本
            </button>
            <div class="mt-2 flex items-center justify-between px-0.5 text-[9.5px] text-slate-400">
              <span>最多保留最近 60 个</span>
              <span class="tabular-nums">{{ revisions.length }} 个</span>
            </div>
          </div>

          <div class="min-h-0 flex-1 overflow-y-auto px-2 py-2">
            <div
              v-if="loading"
              class="flex h-full flex-col items-center justify-center py-10 text-[10.5px] text-slate-400"
            >
              <KiwiIcon name="loader" :size="16" spin class="mb-2" />
              加载历史版本…
            </div>
            <div v-else-if="!revisions.length" class="px-2 py-10 text-center">
              <span
                class="mx-auto mb-2 grid h-9 w-9 place-items-center rounded-xl bg-slate-100 text-slate-300"
              >
                <KiwiIcon name="layers" :size="15" />
              </span>
              <p class="text-[10.5px] leading-relaxed text-slate-400">
                还没有历史版本<br />
                开始编辑后会自动记录，也可先保存检查点
              </p>
            </div>
            <template v-else>
              <section v-for="group in revisionGroups" :key="group.key" class="mb-1">
                <div
                  class="sticky top-0 z-10 -mx-2 flex items-center gap-1.5 bg-white/90 px-2.5 py-1 text-[9px] font-medium tracking-[0.08em] text-slate-400 backdrop-blur"
                >
                  {{ group.label }}
                  <span class="ml-auto font-normal tracking-normal text-slate-300">
                    {{ group.items.length }}
                  </span>
                </div>
                <div class="relative">
                  <span
                    class="pointer-events-none absolute top-1 bottom-1 left-[7px] w-px bg-slate-200/90"
                    aria-hidden="true"
                  />
                  <button
                    v-for="revision in group.items"
                    :key="revision.id"
                    type="button"
                    class="group relative block w-full rounded-lg py-1.5 pr-2 pl-5 text-left transition-all duration-150"
                    :class="
                      revision.id === selectedId
                        ? 'bg-white ring-1 ring-inset ring-kiwi-200/80 shadow-[0_4px_14px_-12px_rgba(15,23,42,0.5)]'
                        : 'hover:bg-white/70'
                    "
                    @click="select(revision.id)"
                  >
                    <span
                      class="absolute top-[8px] left-[3.5px] h-[7px] w-[7px] rounded-full transition-colors"
                      :class="
                        revision.id === selectedId
                          ? 'bg-kiwi-500 ring-4 ring-kiwi-100'
                          : [sourceMeta(revision.source).dot, 'ring-2 ring-white']
                      "
                    />
                    <span class="flex items-baseline gap-1.5">
                      <span
                        class="truncate text-[11.5px] leading-snug"
                        :class="
                          revision.id === selectedId
                            ? 'font-medium text-slate-800'
                            : 'text-slate-600'
                        "
                      >
                        {{ revision.title || '无标题' }}
                      </span>
                      <span
                        class="ml-auto shrink-0 text-[9px] tabular-nums text-slate-400"
                      >
                        {{ formatClock(revision.created_at) }}
                      </span>
                    </span>
                    <span class="mt-1 flex items-center gap-1">
                      <span
                        class="rounded px-1 py-px text-[8.5px] font-medium ring-1 ring-inset"
                        :class="sourceMeta(revision.source).tone"
                      >
                        {{ sourceMeta(revision.source).label }}
                      </span>
                      <span
                        v-if="isLatest(revision)"
                        class="rounded bg-kiwi-500/10 px-1 py-px text-[8.5px] font-medium text-kiwi-600"
                      >
                        最新
                      </span>
                    </span>
                  </button>
                </div>
              </section>
            </template>
          </div>

          <p
            class="shrink-0 border-t border-slate-200/60 px-3 py-2 text-[9.5px] leading-relaxed text-slate-400"
          >
            2 分钟内的连续编辑会合并为一个检查点
          </p>
        </aside>

        <!-- 右侧：内容预览 / 差异对比 -->
        <section
          class="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden rounded-2xl border border-slate-200/70 bg-white/70 shadow-soft"
        >
          <header class="flex shrink-0 items-center gap-2 border-b border-slate-200/60 px-3.5 py-2.5">
            <span
              class="grid h-6 w-6 shrink-0 place-items-center rounded-lg bg-kiwi-50 text-kiwi-500"
            >
              <KiwiIcon name="layers" :size="12" />
            </span>
            <div class="min-w-0">
              <div class="flex items-center gap-1.5">
                <span class="truncate text-[12px] font-medium text-slate-700">
                  {{ detail?.title || selected?.title || '版本预览' }}
                </span>
                <span
                  v-if="selected"
                  class="shrink-0 rounded px-1 py-px text-[8.5px] font-medium ring-1 ring-inset"
                  :class="sourceMeta(selected.source).tone"
                >
                  {{ sourceMeta(selected.source).label }}
                </span>
              </div>
              <p class="mt-0.5 truncate text-[9.5px] tabular-nums text-slate-400">
                <template v-if="selected">
                  {{ formatFullTime(selected.created_at) }}
                  <template v-if="detail"> · {{ bodyChars.toLocaleString() }} 字符</template>
                </template>
                <template v-else>从左侧选择一个版本</template>
              </p>
            </div>
            <div class="ml-auto flex shrink-0 items-center rounded-lg bg-slate-100/80 p-0.5">
              <button
                type="button"
                class="rounded-md px-2 py-1 text-[10px] font-medium transition-all"
                :class="
                  viewMode === 'preview'
                    ? 'bg-white text-kiwi-700 shadow-sm'
                    : 'text-slate-400 hover:text-slate-600'
                "
                @click="viewMode = 'preview'"
              >
                版本内容
              </button>
              <button
                type="button"
                class="rounded-md px-2 py-1 text-[10px] font-medium transition-all"
                :class="
                  viewMode === 'diff'
                    ? 'bg-white text-kiwi-700 shadow-sm'
                    : 'text-slate-400 hover:text-slate-600'
                "
                @click="viewMode = 'diff'"
              >
                对比当前
              </button>
            </div>
          </header>

          <div class="min-h-0 flex-1 overflow-y-auto">
            <div
              v-if="detailLoading"
              class="flex h-full flex-col items-center justify-center py-16 text-[10.5px] text-slate-400"
            >
              <KiwiIcon name="loader" :size="16" spin class="mb-2" />
              读取版本内容…
            </div>
            <template v-else-if="detail">
              <div v-if="viewMode === 'diff'" class="p-3.5">
                <div
                  class="mb-2.5 flex flex-wrap items-center gap-2 rounded-xl border border-slate-200/70 bg-gradient-to-r from-white via-white to-kiwi-50/40 px-3 py-2"
                >
                  <span class="flex items-center gap-1 text-[10px] font-medium text-slate-500">
                    <KiwiIcon name="layers" :size="11" class="text-slate-400" />
                    历史 → 当前
                  </span>
                  <span
                    v-if="diffStats.identical"
                    class="inline-flex items-center gap-1 rounded-full bg-slate-100 px-2 py-0.5 text-[9.5px] text-slate-500"
                  >
                    内容一致
                  </span>
                  <template v-else>
                    <span
                      class="inline-flex items-center rounded-full bg-emerald-50 px-2 py-0.5 text-[9.5px] font-medium text-emerald-700 ring-1 ring-inset ring-emerald-200/60"
                    >
                      +{{ diffStats.added }} 行
                    </span>
                    <span
                      class="inline-flex items-center rounded-full bg-rose-50 px-2 py-0.5 text-[9.5px] font-medium text-rose-600 ring-1 ring-inset ring-rose-200/60"
                    >
                      −{{ diffStats.removed }} 行
                    </span>
                  </template>
                  <span class="ml-auto max-w-[55%] truncate text-[9.5px] text-slate-400">
                    当前：{{ currentTitle || '未命名' }} ·
                    {{ (currentBody || '').length.toLocaleString() }} 字符
                  </span>
                </div>

                <div
                  v-if="diffStats.identical"
                  class="flex flex-col items-center justify-center py-16 text-center"
                >
                  <span
                    class="mb-3 grid h-11 w-11 place-items-center rounded-2xl bg-emerald-50 text-emerald-500 ring-1 ring-inset ring-emerald-100"
                  >
                    <KiwiIcon name="check" :size="18" />
                  </span>
                  <p class="text-[11.5px] font-medium text-slate-600">该版本与当前内容一致</p>
                  <p class="mt-1 text-[10px] text-slate-400">没有需要对比的改动</p>
                </div>

                <div
                  v-else
                  class="overflow-hidden rounded-xl border border-slate-200/70 bg-white font-mono text-[11.5px] leading-[1.7] shadow-[0_16px_44px_-38px_rgba(15,23,42,0.5)]"
                >
                  <div
                    v-for="(line, index) in diffLines"
                    :key="index"
                    class="flex min-w-0 border-l-2"
                    :class="
                      line.kind === 'add'
                        ? 'border-emerald-300 bg-emerald-50/60'
                        : line.kind === 'del'
                          ? 'border-rose-300 bg-rose-50/60'
                          : 'border-transparent'
                    "
                  >
                    <span
                      class="w-9 shrink-0 select-none border-r border-slate-100 bg-slate-50/50 px-1.5 py-[3px] text-right text-[9.5px] tabular-nums text-slate-300"
                    >{{ line.oldNo ?? '' }}</span>
                    <span
                      class="w-9 shrink-0 select-none border-r border-slate-100 bg-slate-50/50 px-1.5 py-[3px] text-right text-[9.5px] tabular-nums text-slate-300"
                    >{{ line.newNo ?? '' }}</span>
                    <span
                      class="w-4 shrink-0 select-none py-[3px] text-center font-semibold"
                      :class="
                        line.kind === 'add'
                          ? 'text-emerald-500'
                          : line.kind === 'del'
                            ? 'text-rose-400'
                            : 'text-transparent'
                      "
                    >{{ diffPrefix(line.kind) }}</span>
                    <span
                      class="min-w-0 flex-1 px-2 py-[3px] break-words whitespace-pre-wrap"
                      :class="
                        line.kind === 'add'
                          ? 'text-emerald-800'
                          : line.kind === 'del'
                            ? 'text-rose-700'
                            : 'text-slate-600'
                      "
                    >{{ line.text || ' ' }}</span>
                  </div>
                </div>
              </div>

              <div v-else class="bg-gradient-to-b from-slate-50/80 to-white px-3.5 py-4">
                <div
                  class="mx-auto max-w-[720px] rounded-xl border border-slate-200/60 bg-white px-6 py-6 shadow-[0_24px_60px_-48px_rgba(15,23,42,0.5)]"
                >
                  <MarkdownView :content="detail.body_md || ''" />
                </div>
              </div>
            </template>
            <div
              v-else
              class="flex h-full flex-col items-center justify-center px-6 py-16 text-center"
            >
              <span
                class="mb-3 grid h-11 w-11 place-items-center rounded-2xl bg-slate-100 text-slate-300"
              >
                <KiwiIcon name="layers" :size="18" />
              </span>
              <p class="text-[11.5px] text-slate-400">从左侧选择一个版本查看内容</p>
            </div>
          </div>

          <footer
            class="flex shrink-0 items-center gap-2 border-t border-slate-200/60 bg-white/60 px-3.5 py-2.5"
          >
            <p class="hidden text-[9.5px] leading-relaxed text-slate-400 sm:block">
              还原后，当前内容会自动留档为「还原前」版本
            </p>
            <div class="ml-auto flex items-center gap-1.5">
              <button
                v-if="selected"
                class="inline-flex items-center gap-1 rounded-lg px-2 py-1.5 text-[10px] text-rose-400 transition-colors hover:bg-rose-50 hover:text-rose-600"
                title="删除该历史版本"
                @click="deleteTarget = selected"
              >
                <KiwiIcon name="trash" :size="11" />
                删除
              </button>
              <button
                class="kiwi-btn-primary !px-3 !py-1.5 !text-[10.5px]"
                :disabled="!selected || restoring || detailLoading"
                @click="restore"
              >
                <KiwiIcon :name="restoring ? 'loader' : 'undo'" :size="11" :spin="restoring" />
                还原此版本
              </button>
            </div>
          </footer>
        </section>
      </div>
    </div>

    <KiwiConfirm
      :model-value="deleteTarget !== null"
      danger
      title="删除历史版本"
      :message="`删除「${deleteTarget?.title || '无标题'}」的这个历史版本后无法恢复，当前笔记内容不受影响。`"
      confirm-text="删除"
      @update:model-value="deleteTarget = null"
      @confirm="confirmDelete"
    />
  </KiwiModal>
</template>

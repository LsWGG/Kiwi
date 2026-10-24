<script setup lang="ts">
/**
 * 「贴一贴」浮窗：独立于工作区的便签窗口。
 *
 * 直接按 noteId 拉取 / 保存笔记，不读写 notesStore.currentNote，因此可以在
 * 主窗口操作其他笔记时同时打开多个浮窗；位置与尺寸持久化到 localStorage。
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { request } from '@/api/client'
import { useKbsStore } from '@/stores/kbs'
import { useNotesStore, type NoteOut } from '@/stores/notes'
import { useStickyNotesStore, type StickyWindow } from '@/stores/stickyNotes'
import MarkdownView from '@/components/editor/MarkdownView.vue'
import NoteStickyPreview from '@/components/notes/NoteStickyPreview.vue'
import KiwiIcon from '@/components/ui/KiwiIcon.vue'
import { toast } from '@/components/ui/toast'
import { useFloatingWindowDrag } from '@/composables/useFloatingWindowDrag'

const props = defineProps<{ win: StickyWindow }>()

const notes = useNotesStore()
const sticky = useStickyNotesStore()
const kbs = useKbsStore()
const router = useRouter()

const note = ref<NoteOut | null>(null)
const loading = ref(true)
const error = ref('')
const draft = ref('')
const editing = ref(false)
const saving = ref(false)
const dirty = ref(false)
/** 点击「在主窗口打开」时先放大淡出，再切换路由。 */
const expanding = ref(false)
const windowEl = ref<HTMLElement | null>(null)

/** 从其他便签后面升到最前时给一个回弹，让「当前操作的是哪一张」更明确。 */
function pulseWindow() {
  const node = windowEl.value
  if (!node || expanding.value) return
  if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return
  node.animate(
    [
      { transform: 'scale(1)' },
      { transform: 'scale(1.05)', offset: 0.35 },
      { transform: 'scale(0.985)', offset: 0.7 },
      { transform: 'scale(1)' },
    ],
    { duration: 460, easing: 'cubic-bezier(0.2, 1.2, 0.3, 1)' },
  )
}

function onWindowPointerDown() {
  const topZ = Math.max(0, ...sticky.windows.map((item) => item.z))
  const rising = props.win.z < topZ
  sticky.focus(props.win.id)
  if (rising) pulseWindow()
}
let hydrating = false
let saveTimer: number | null = null

const KIND_META: Record<string, { label: string; icon: string }> = {
  doc: { label: '文档', icon: 'fileText' },
  import: { label: '导入文档', icon: 'fileImport' },
  link: { label: '链接', icon: 'link2' },
  sheet: { label: '表格', icon: 'table' },
  database: { label: '数据表', icon: 'database' },
  canvas: { label: '画布', icon: 'pen' },
  notebook: { label: 'Notebook', icon: 'notebook' },
}

const kind = computed(() => String(note.value?.kind || props.win.kind || 'doc'))
const kindMeta = computed(
  () => KIND_META[kind.value] || { label: '笔记', icon: 'note' },
)
const locked = computed(() => !!note.value?.is_locked)
/** 数据表 / 画布 / Notebook / 表格结构复杂，只做摘要展示，编辑回主窗口。 */
const textKind = computed(() => ['doc', 'import', 'link'].includes(kind.value))
const structuredKind = computed(() =>
  ['sheet', 'database', 'canvas', 'notebook'].includes(kind.value),
)
const canEdit = computed(() => textKind.value && !locked.value)
const title = computed(() => note.value?.title || props.win.title || '无标题')
const emptyBody = computed(() => !(note.value?.body_md || '').trim())
const savingLabel = computed(() => {
  if (saving.value) return '保存中…'
  return dirty.value ? '未保存' : '已保存'
})

// ---------- 数据表：字段与记录按需加载 ----------
type DbField = { id: string; name?: string; type?: string }
type DbRow = { id: string; data: Record<string, any> }

const dbFields = ref<DbField[]>([])
const dbRows = ref<DbRow[]>([])
const dbLoading = ref(false)
const dbError = ref('')

async function loadDatabase(target: NoteOut) {
  dbLoading.value = true
  dbError.value = ''
  try {
    const [meta, rows] = await Promise.all([
      request<{ fields: DbField[] }>(`/notes/${target.id}/database`, {
        kbId: props.win.kbId,
        headers: notes.noteHeaders(target.id),
      }),
      request<DbRow[]>(`/notes/${target.id}/rows`, {
        kbId: props.win.kbId,
        headers: notes.noteHeaders(target.id),
      }),
    ])
    dbFields.value = Array.isArray(meta?.fields) ? meta.fields : []
    dbRows.value = Array.isArray(rows) ? rows : []
  } catch (e: any) {
    dbError.value = e.message || '数据表加载失败'
  } finally {
    dbLoading.value = false
  }
}

async function load() {
  loading.value = true
  error.value = ''
  dbFields.value = []
  dbRows.value = []
  dbError.value = ''
  try {
    const data = await request<NoteOut>(`/notes/${props.win.noteId}`, {
      kbId: props.win.kbId,
      headers: notes.noteHeaders(props.win.noteId),
    })
    note.value = data
    hydrating = true
    draft.value = data.body_md || ''
    sticky.rename(props.win.id, data.title)
    // 浮窗默认阅读：主要用来对照参考，需要改动时再点铅笔。
    editing.value = false
    queueMicrotask(() => {
      hydrating = false
    })
    if (data.kind === 'database' && !data.is_locked) void loadDatabase(data)
  } catch (e: any) {
    error.value = e.message || '笔记加载失败'
  } finally {
    loading.value = false
  }
}

function scheduleSave() {
  if (saveTimer !== null) window.clearTimeout(saveTimer)
  saveTimer = window.setTimeout(() => {
    saveTimer = null
    void save(true)
  }, 900)
}

watch(draft, () => {
  if (hydrating || !editing.value) return
  dirty.value = true
  scheduleSave()
})

async function save(silent = false) {
  if (!note.value || !canEdit.value || !dirty.value || saving.value) return
  saving.value = true
  try {
    const saved = await request<NoteOut>(`/notes/${note.value.id}`, {
      method: 'PATCH',
      kbId: props.win.kbId,
      headers: notes.noteHeaders(note.value.id),
      body: JSON.stringify({ body_md: draft.value }),
    })
    note.value = saved
    dirty.value = false
    // 便签可能属于其他知识库，只同步当前工作区的目录摘要。
    if (saved.kb_id === kbs.currentKbId) notes.upsertSummary(saved)
    if (!silent) toast.success('已保存')
  } catch (e: any) {
    toast.error(e.message || '保存失败')
  } finally {
    saving.value = false
  }
}

function toggleMode() {
  if (!canEdit.value) return
  if (editing.value) void save(true)
  editing.value = !editing.value
}

async function close() {
  if (saveTimer !== null) {
    window.clearTimeout(saveTimer)
    saveTimer = null
  }
  await save(true)
  sticky.close(props.win.id)
}

async function openInWorkspace() {
  if (expanding.value) return
  // 便签可能属于另一个知识库，先切过去再打开，避免主窗口找不到笔记。
  if (kbs.currentKbId !== props.win.kbId) kbs.currentKbId = props.win.kbId
  expanding.value = true
  // 让卡片先放大淡出（与开启时的弹入动画呼应），再切到主窗口。
  if (!window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
    await new Promise((resolve) => window.setTimeout(resolve, 160))
  }
  void close()
  void router.push({ name: 'notes', params: { id: props.win.noteId } })
}

// ---------- 拖动 / 缩放 ----------
const { onDragStart, onResizeStart } = useFloatingWindowDrag({
  bounds: props.win,
  minW: sticky.MIN_W,
  minH: sticky.MIN_H,
  onCommit: () =>
    sticky.updateBounds(props.win.id, {
      x: props.win.x,
      y: props.win.y,
      w: props.win.w,
      h: props.win.h,
    }),
})

onMounted(load)
watch(() => props.win.noteId, load)

onBeforeUnmount(() => {
  if (saveTimer !== null) window.clearTimeout(saveTimer)
  void save(true)
})
</script>

<template>
  <!-- 外层由 NoteStickyLayer 挂到 <html> 下，用不受 body zoom 影响的视口坐标定位；
       内层单独按 --ui-scale 放大，与 2K / 4K 下整体 UI 的比例保持一致。 -->
  <div
    class="sticky-anchor fixed"
    :style="{ left: `${win.x}px`, top: `${win.y}px`, zIndex: win.z }"
    @pointerdown.capture="onWindowPointerDown"
  >
    <div
      ref="windowEl"
      class="sticky-window relative flex flex-col overflow-hidden rounded-2xl border border-slate-200/80 bg-white/95 shadow-lifted backdrop-blur-xl"
      :class="{ 'is-expanding': expanding }"
      :style="{ width: `${win.w}px`, height: `${win.h}px`, zoom: 'var(--ui-scale)' }"
      role="dialog"
      :aria-label="`便签：${title}`"
    >
      <!-- 标题栏：拖动区域 -->
      <header
        class="flex shrink-0 cursor-grab items-center gap-2 border-b border-slate-100 bg-gradient-to-b from-slate-50/90 to-white px-3 py-2 active:cursor-grabbing"
        @pointerdown="onDragStart"
        @dblclick.stop="openInWorkspace"
      >
        <KiwiIcon :name="kindMeta.icon" :size="14" class="shrink-0 text-kiwi-600" />
        <div class="min-w-0 flex-1">
          <p class="truncate text-[12.5px] font-medium text-slate-700" :title="title">
            {{ title }}
          </p>
          <p class="truncate text-[9.5px] text-slate-400">
            {{ kindMeta.label }} · {{ savingLabel }}
          </p>
        </div>
        <button
          v-if="canEdit"
          type="button"
          class="sticky-icon-button"
          :title="editing ? '预览' : '编辑'"
          @click.stop="toggleMode"
        >
          <KiwiIcon :name="editing ? 'eye' : 'edit'" :size="13" />
        </button>
        <button
          type="button"
          class="sticky-icon-button"
          title="在主窗口打开"
          @click.stop="openInWorkspace"
        >
          <KiwiIcon name="maximize" :size="13" />
        </button>
        <button
          type="button"
          class="sticky-icon-button hover:!bg-rose-50 hover:!text-rose-500"
          title="关闭便签"
          @click.stop="close"
        >
          <KiwiIcon name="close" :size="13" />
        </button>
      </header>

      <div class="min-h-0 flex-1 overflow-y-auto">
        <div v-if="loading" class="grid h-full place-items-center text-[11.5px] text-slate-400">
          <span class="flex items-center gap-1.5">
            <KiwiIcon name="loader" :size="14" :spin="true" /> 载入笔记…
          </span>
        </div>
        <div v-else-if="error" class="grid h-full place-items-center px-4 text-center">
          <div>
            <KiwiIcon name="alert" :size="20" class="mx-auto text-rose-300" />
            <p class="mt-2 text-[11.5px] text-slate-500">{{ error }}</p>
            <button class="kiwi-btn-secondary mt-3 !py-1 !text-[11px]" @click="load">重试</button>
          </div>
        </div>
        <div v-else-if="locked" class="grid h-full place-items-center px-5 text-center">
          <div>
            <KiwiIcon name="lock" :size="22" class="mx-auto text-amber-400" />
            <p class="mt-2 text-[12px] font-medium text-slate-600">笔记已上锁</p>
            <p class="mt-1 text-[10.5px] text-slate-400">请在主窗口解锁后查看与编辑。</p>
            <button class="kiwi-btn-secondary mt-3 !py-1 !text-[11px]" @click="openInWorkspace">
              打开主窗口
            </button>
          </div>
        </div>
        <template v-else-if="structuredKind">
          <div
            v-if="dbLoading"
            class="grid h-full place-items-center text-[11.5px] text-slate-400"
          >
            <span class="flex items-center gap-1.5">
              <KiwiIcon name="loader" :size="14" :spin="true" /> 载入内容…
            </span>
          </div>
          <div v-else-if="dbError" class="grid h-full place-items-center px-4 text-center">
            <div>
              <KiwiIcon name="alert" :size="20" class="mx-auto text-rose-300" />
              <p class="mt-2 text-[11.5px] text-slate-500">{{ dbError }}</p>
              <button class="kiwi-btn-secondary mt-3 !py-1 !text-[11px]" @click="load">
                重试
              </button>
            </div>
          </div>
          <NoteStickyPreview
            v-else-if="note"
            :note="note"
            :fields="dbFields"
            :rows="dbRows"
          />
        </template>
        <template v-else>
          <textarea
            v-if="editing"
            v-model="draft"
            class="sticky-editor h-full w-full resize-none border-0 bg-transparent px-4 py-3 font-mono text-[12.5px] leading-relaxed text-slate-700 outline-none"
            spellcheck="false"
            placeholder="写点什么…支持 Markdown"
            @pointerdown.stop
          />
          <div v-else-if="emptyBody" class="grid h-full place-items-center px-4 text-center">
            <div>
              <p class="text-[11.5px] text-slate-400">这篇笔记还没有正文</p>
              <button
                v-if="canEdit"
                class="kiwi-btn-secondary mt-2 !py-1 !text-[11px]"
                @click="editing = true"
              >
                开始编辑
              </button>
            </div>
          </div>
          <!-- MarkdownView 是 fragment 根节点，class 需由外层容器承载 -->
          <div v-else class="sticky-preview px-4 py-3">
            <MarkdownView :content="note?.body_md || ''" plugins />
          </div>
        </template>
      </div>

      <footer
        v-if="canEdit && editing"
        class="flex shrink-0 items-center justify-between border-t border-slate-100 px-3 py-1.5"
      >
        <span class="text-[9.5px] text-slate-400">自动保存 · Markdown</span>
        <button
          class="kiwi-btn-secondary !px-2 !py-0.5 !text-[10.5px]"
          :disabled="!dirty || saving"
          @click="save(false)"
        >
          <KiwiIcon :name="saving ? 'loader' : 'check'" :size="11" :spin="saving" />
          保存
        </button>
      </footer>

      <!-- 缩放手柄 -->
      <span
        class="absolute bottom-0 right-0 h-4 w-4 cursor-nwse-resize"
        title="拖动调整大小"
        @pointerdown="onResizeStart"
      >
        <svg viewBox="0 0 16 16" class="h-4 w-4 text-slate-300" aria-hidden="true">
          <path d="M15 6L6 15M15 10l-5 5" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" />
        </svg>
      </span>
    </div>
  </div>
</template>

<style scoped>
.sticky-window {
  min-width: 300px;
  min-height: 220px;
  transform-origin: 85% 8%;
  animation: sticky-pop 0.52s cubic-bezier(0.2, 1.45, 0.32, 1) both;
  transition:
    transform 0.16s ease-in,
    opacity 0.16s ease-in;
}
/* 弹入时沿卡片边缘连续扩散两圈主题色光晕。
   卡片本身 overflow-hidden 会裁掉外扩阴影，所以挂在未裁切的外层锚点上。 */
.sticky-anchor::before,
.sticky-anchor::after {
  content: '';
  position: absolute;
  inset: 0;
  border-radius: calc(1rem * var(--ui-scale, 1));
  pointer-events: none;
}
.sticky-anchor::after {
  animation: sticky-halo 0.8s cubic-bezier(0.16, 1, 0.3, 1) 0.12s;
}
.sticky-anchor::before {
  animation: sticky-halo 0.8s cubic-bezier(0.16, 1, 0.3, 1) 0.3s;
}
/* 从明显缩小并下沉的状态弹入，中途过冲再回弹。 */
@keyframes sticky-pop {
  0% {
    opacity: 0;
    transform: translateY(26px) scale(0.46) rotate(-1.5deg);
  }
  45% {
    opacity: 1;
  }
  62% {
    transform: translateY(-4px) scale(1.07) rotate(0.4deg);
  }
  80% {
    transform: translateY(1px) scale(0.985);
  }
  100% {
    opacity: 1;
    transform: translateY(0) scale(1);
  }
}
@keyframes sticky-halo {
  0% {
    opacity: 0.9;
    box-shadow:
      0 0 0 2px rgb(var(--kiwi-400) / 0.55),
      0 0 22px 5px rgb(var(--kiwi-300) / 0.35);
  }
  100% {
    opacity: 0;
    box-shadow:
      0 0 0 30px rgb(var(--kiwi-400) / 0),
      0 0 40px 20px rgb(var(--kiwi-300) / 0);
  }
}
/* 切换主窗口前：卡片放大淡出，避免瞬间消失。 */
.sticky-window.is-expanding {
  animation: none;
  transform: scale(1.12);
  opacity: 0;
}
@media (prefers-reduced-motion: reduce) {
  .sticky-window {
    animation: none;
    transition: none;
  }
  .sticky-anchor::before,
  .sticky-anchor::after {
    display: none;
  }
}
.sticky-icon-button {
  display: grid;
  place-items: center;
  width: 24px;
  height: 24px;
  border-radius: 7px;
  color: rgb(100 116 139);
  transition: background 0.15s ease, color 0.15s ease;
}
.sticky-icon-button:hover {
  background: rgb(241 245 249);
  color: rgb(30 41 59);
}
.sticky-editor {
  tab-size: 2;
}
.sticky-preview {
  min-height: 100%;
}
/* 便签空间有限：正文与标题整体缩小一档，长文仍可滚动阅读。 */
.sticky-preview :deep(.prose-wiki) {
  font-size: 12.5px;
  line-height: 1.7;
}
.sticky-preview :deep(.prose-wiki) > * + * {
  margin-top: 0.6em;
}
.sticky-preview :deep(h1) {
  margin: 0.3em 0 0.35em;
  font-size: 1.35rem;
  line-height: 1.3;
}
.sticky-preview :deep(h2) {
  margin: 0.4em 0 0.3em;
  font-size: 1.15rem;
}
.sticky-preview :deep(h3) {
  margin: 0.4em 0 0.25em;
  font-size: 1rem;
}
.sticky-preview :deep(pre) {
  font-size: 11px;
}
.sticky-preview :deep(img) {
  border-radius: 8px;
}
</style>

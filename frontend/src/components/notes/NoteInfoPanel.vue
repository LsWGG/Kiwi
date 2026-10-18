<script setup lang="ts">
/** 笔记详情右侧面板：元数据、标签、Wiki 关联、学习要点、相关笔记与生命周期操作。 */
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { request } from '@/api/client'
import { useKbsStore } from '@/stores/kbs'
import {
  useNotesStore,
  type NoteOut,
  type NoteSummary,
  type NoteStudyPoint,
  type NoteCompileStatus,
  type RelatedNoteItem,
} from '@/stores/notes'
import KiwiIcon from '@/components/ui/KiwiIcon.vue'
import KiwiConfirm from '@/components/ui/KiwiConfirm.vue'
import DatabaseCell from '@/components/notes/database/DatabaseCell.vue'
import type { DbField } from '@/stores/noteDatabase'
import { toast } from '@/components/ui/toast'

const props = defineProps<{ note: NoteOut; open: boolean }>()
const emit = defineEmits<{
  (e: 'close'): void
  (e: 'open-note', id: string, mentionId?: string): void
  (e: 'open-collection-row', databaseId: string, rowId: string): void
}>()

const kbs = useKbsStore()
const notes = useNotesStore()
const router = useRouter()

const KIND_LABEL: Record<string, string> = {
  doc: '文档',
  database: '数据表',
  link: '链接',
  import: '导入',
  canvas: '画布',
  notebook: 'Notebook',
}

const localTags = ref<string[]>([])
const tagInput = ref('')
const savingTags = ref(false)

const backlinks = ref<NoteSummary[]>([])
const related = ref<RelatedNoteItem[]>([])
const loadingRelated = ref(false)

const wikiPages = ref<Array<{ id: string; title: string; slug: string; page_type: string }>>([])
const wikiId = ref<string>('')
const wikiLoading = ref(false)

const studyPoints = ref<NoteStudyPoint[]>([])
const pointInput = ref('')
const savingPoints = ref(false)

/** 行笔记所属集合的字段与属性值（README：集合属性出现在笔记详情中）。 */
interface CollectionContext {
  database_note_id: string
  database_title: string
  row_id: string
  fields: DbField[]
  data: Record<string, any>
  title: string
}
const collectionContext = ref<CollectionContext | null>(null)
const collectionLoading = ref(false)
const collectionSaving = ref(false)
const isCollectionRow = computed(() => !!props.note.props_json?.collection_row_id)

const compileStatus = ref<NoteCompileStatus | null>(null)
const compiling = ref(false)
let compileTimer: number | null = null

const templateName = ref('')
const savingTemplate = ref(false)

const folderName = computed(
  () => notes.folders.find((f) => f.id === props.note.folder_id)?.name || '根目录',
)
const statusLabel = computed(() => {
  if (props.note.status === 'archived') return '已归档'
  if (props.note.status === 'trash') return '回收站'
  return '活跃'
})
const compileRunning = computed(
  () =>
    compiling.value ||
    compileStatus.value?.status === 'pending' ||
    compileStatus.value?.status === 'running',
)

function syncTags() {
  localTags.value = [...(props.note.tags || [])]
  tagInput.value = ''
}

async function addTag(name?: string) {
  const value = (name ?? tagInput.value).trim().replace(/^#/, '')
  if (!value || localTags.value.includes(value)) {
    tagInput.value = ''
    return
  }
  localTags.value = [...localTags.value, value]
  tagInput.value = ''
  await persistTags()
}

async function removeTag(name: string) {
  localTags.value = localTags.value.filter((t) => t !== name)
  await persistTags()
}

async function persistTags() {
  savingTags.value = true
  try {
    await notes.setNoteTags(props.note.id, localTags.value)
    toast.success('标签已更新')
  } catch (e: any) {
    toast.error(e.message || '保存标签失败')
    syncTags()
  } finally {
    savingTags.value = false
  }
}

async function loadRelated() {
  loadingRelated.value = true
  try {
    const [links, rel] = await Promise.all([
      notes.getBacklinks(props.note.id).catch(() => []),
      notes.getRelated(props.note.id).catch(() => []),
    ])
    backlinks.value = links
    related.value = rel
  } finally {
    loadingRelated.value = false
  }
}

async function loadWiki() {
  if (!kbs.currentKbId) return
  wikiLoading.value = true
  try {
    const [pages, link] = await Promise.all([
      request<Array<{ id: string; title: string; slug: string; page_type: string }>>(
        '/wiki',
        { kbId: kbs.currentKbId },
      ).catch(() => []),
      notes.getNoteWiki(props.note.id).catch(() => null),
    ])
    wikiPages.value = pages
    wikiId.value = link?.wiki_page_id || ''
  } finally {
    wikiLoading.value = false
  }
}

async function saveWiki() {
  try {
    await notes.setNoteWiki(props.note.id, wikiId.value || null)
    toast.success(wikiId.value ? '已关联 Wiki 页面' : '已取消关联')
  } catch (e: any) {
    toast.error(e.message || '保存关联失败')
    await loadWiki()
  }
}

function rowDisplayTitle(data: Record<string, any>, fields: DbField[]): string {
  for (const preferred of ['name', 'title']) {
    const value = data[preferred]
    if (typeof value === 'string' && value.trim()) return value.trim()
  }
  for (const field of fields) {
    if (['text', 'long_text', 'url'].includes(field.type)) {
      const value = data[field.id]
      if (typeof value === 'string' && value.trim()) return value.trim()
    }
  }
  return '未命名记录'
}

async function loadCollectionContext() {
  collectionContext.value = null
  if (!isCollectionRow.value || !kbs.currentKbId) return
  collectionLoading.value = true
  try {
    collectionContext.value = await request<CollectionContext>(
      `/notes/${props.note.id}/collection-context`,
      { kbId: kbs.currentKbId },
    )
  } catch {
    collectionContext.value = null
  } finally {
    collectionLoading.value = false
  }
}

async function updateCollectionProp(field: DbField, value: any) {
  const ctx = collectionContext.value
  if (!ctx) return
  const prev = ctx.data[field.id]
  ctx.data = { ...ctx.data, [field.id]: value }
  collectionSaving.value = true
  try {
    const row = await request<{ data: Record<string, any> }>(
      `/notes/${ctx.database_note_id}/rows/${ctx.row_id}`,
      {
        method: 'PATCH',
        kbId: kbs.currentKbId,
        body: JSON.stringify({ data: { [field.id]: value } }),
      },
    )
    ctx.data = row.data
    // 行标题字段变化时同步笔记标题（服务端已写回，本地刷新展示）
    if (rowDisplayTitle(ctx.data, ctx.fields) !== props.note.title) {
      await notes.getNote(props.note.id)
      void notes.fetchTree().catch(() => {})
    }
  } catch (e: any) {
    ctx.data = { ...ctx.data, [field.id]: prev }
    toast.error(e.message || '保存集合属性失败')
  } finally {
    collectionSaving.value = false
  }
}

async function loadPoints() {
  try {
    studyPoints.value = await notes.getStudyPoints(props.note.id)
  } catch {
    studyPoints.value = []
  }
}

async function addPoint() {
  const text = pointInput.value.trim()
  if (!text) return
  studyPoints.value = [...studyPoints.value, {
    id: `tmp-${Date.now()}`,
    text,
    wiki_slug: null,
    created_at: new Date().toISOString(),
  }]
  pointInput.value = ''
  await persistPoints()
}

async function removePoint(id: string) {
  studyPoints.value = studyPoints.value.filter((p) => p.id !== id)
  await persistPoints()
}

async function persistPoints() {
  savingPoints.value = true
  try {
    const saved = await notes.setStudyPoints(
      props.note.id,
      studyPoints.value.map((p) => ({ text: p.text, wiki_slug: p.wiki_slug })),
    )
    studyPoints.value = saved
  } catch (e: any) {
    toast.error(e.message || '保存学习要点失败')
    await loadPoints()
  } finally {
    savingPoints.value = false
  }
}

function stopCompilePolling() {
  if (compileTimer !== null) {
    window.clearTimeout(compileTimer)
    compileTimer = null
  }
}

async function refreshCompileStatus() {
  try {
    compileStatus.value = await notes.getCompileStatus(props.note.id)
    if (compileRunning.value) {
      compileTimer = window.setTimeout(refreshCompileStatus, 2000)
    } else if (compileStatus.value.status === 'succeeded') {
      compiling.value = false
    }
  } catch {
    compiling.value = false
  }
}

function openCompileJob() {
  const jobId = compileStatus.value?.job_id
  if (!jobId) return
  emit('close')
  void router.push({ name: 'sources', query: { tab: 'jobs', job: jobId } })
}

async function compileNote() {
  compiling.value = true
  compileTimer = null
  try {
    await notes.compileNote(props.note.id)
    toast.success('已提交编译，正在后台生成 Wiki 页面')
    await refreshCompileStatus()
  } catch (e: any) {
    compiling.value = false
    toast.error(e.message || '编译失败')
  }
}

async function saveAsTemplate() {
  const name = templateName.value.trim() || props.note.title
  if (!name) return
  savingTemplate.value = true
  try {
    await notes.createTemplate({
      name,
      description: `由笔记「${props.note.title}」保存`,
      icon: 'note',
      title_pattern: props.note.title,
      body_md: props.note.body_md,
      tags_json: localTags.value,
    })
    templateName.value = ''
    toast.success('已保存为笔记模板')
  } catch (e: any) {
    toast.error(e.message || '保存模板失败')
  } finally {
    savingTemplate.value = false
  }
}

async function archive() {
  try {
    await notes.archiveNote(props.note.id)
    toast.success('已归档')
    emit('close')
  } catch (e: any) {
    toast.error(e.message || '归档失败')
  }
}

async function unarchive() {
  try {
    await notes.unarchiveNote(props.note.id)
    toast.success('已取消归档')
  } catch (e: any) {
    toast.error(e.message || '操作失败')
  }
}

const trashOpen = ref(false)

async function moveToTrash() {
  try {
    await notes.deleteNote(props.note.id)
    trashOpen.value = false
    toast.success('已移入回收站，可在 30 天内恢复')
    emit('close')
  } catch (e: any) {
    toast.error(e.message || '删除失败')
  }
}

function reset() {
  syncTags()
  backlinks.value = []
  related.value = []
  studyPoints.value = []
  wikiId.value = ''
  compileStatus.value = null
  compiling.value = false
  templateName.value = ''
  loadingRelated.value = false
  collectionContext.value = null
  collectionLoading.value = false
  collectionSaving.value = false
  stopCompilePolling()
}

watch(
  () => props.note.id,
  () => {
    reset()
    if (props.open) {
      void loadRelated()
      void loadWiki()
      void loadPoints()
      void loadCollectionContext()
      void refreshCompileStatus()
    }
  },
)

watch(
  () => props.open,
  (open) => {
    if (!open) {
      stopCompilePolling()
      return
    }
    syncTags()
    void loadRelated()
    void loadWiki()
    void loadPoints()
    void loadCollectionContext()
    void refreshCompileStatus()
  },
  { immediate: true },
)

watch(() => props.note.tags, syncTags, { deep: true })

onBeforeUnmount(stopCompilePolling)
</script>

<template>
  <aside
    v-if="open"
    class="w-[300px] shrink-0 h-full border-l border-slate-200/60 bg-white/55 backdrop-blur-xl overflow-y-auto"
  >
    <div class="sticky top-0 z-10 flex items-center gap-2 px-4 h-11 bg-white/85 backdrop-blur border-b border-slate-200/50">
      <KiwiIcon name="fileText" :size="14" class="text-kiwi-500" />
      <span class="text-[12.5px] font-semibold text-slate-700">笔记信息</span>
      <div class="flex-1" />
      <button class="kiwi-btn-ghost !p-1" title="关闭" @click="emit('close')">
        <KiwiIcon name="close" :size="13" />
      </button>
    </div>

    <div class="p-4 space-y-5">
      <!-- 元数据 -->
      <section>
        <h4 class="info-title">属性</h4>
        <dl class="space-y-1.5 text-[11.5px]">
          <div class="info-row"><dt>类型</dt><dd>{{ KIND_LABEL[note.kind] || note.kind }}</dd></div>
          <div class="info-row"><dt>状态</dt><dd>{{ statusLabel }}</dd></div>
          <div class="info-row"><dt>分组</dt><dd>{{ folderName }}</dd></div>
          <div class="info-row">
            <dt>创建</dt>
            <dd>{{ new Date(note.created_at).toLocaleString('zh-CN') }}</dd>
          </div>
          <div class="info-row">
            <dt>更新</dt>
            <dd>{{ new Date(note.updated_at).toLocaleString('zh-CN') }}</dd>
          </div>
          <div v-if="note.source_id" class="info-row">
            <dt>素材</dt>
            <dd class="font-mono text-[10px]">{{ note.source_id.slice(0, 8) }}…</dd>
          </div>
        </dl>
      </section>

      <!-- 集合属性：行笔记才显示 -->
      <section v-if="isCollectionRow">
        <div class="flex items-center justify-between mb-1.5 gap-2">
          <h4 class="info-title !mb-0">集合属性</h4>
          <span v-if="collectionSaving" class="text-[10px] text-slate-400">保存中…</span>
          <button
            v-else-if="collectionContext"
            class="min-w-0 text-[10px] text-kiwi-600 hover:underline truncate"
            :title="`打开数据表「${collectionContext.database_title}」并定位当前记录`"
            @click="
              emit(
                'open-collection-row',
                collectionContext.database_note_id,
                collectionContext.row_id,
              )
            "
          >
            {{ collectionContext.database_title }} · 定位记录
          </button>
        </div>
        <p v-if="collectionLoading" class="text-[10.5px] text-slate-400">加载集合属性…</p>
        <p v-else-if="!collectionContext" class="text-[10.5px] text-slate-300">
          无法读取集合属性
        </p>
        <div v-else class="space-y-1.5">
          <div
            v-for="field in collectionContext.fields"
            :key="field.id"
            class="flex items-start gap-2"
          >
            <span class="w-[72px] shrink-0 pt-1.5 text-[11px] text-slate-400 truncate" :title="field.name">
              {{ field.name }}
            </span>
            <div class="flex-1 min-w-0">
              <DatabaseCell
                :field="field"
                :value="collectionContext.data[field.id]"
                @update="updateCollectionProp(field, $event)"
              />
            </div>
          </div>
        </div>
      </section>

      <!-- 标签 -->
      <section>
        <div class="flex items-center justify-between mb-1.5">
          <h4 class="info-title !mb-0">标签</h4>
          <span v-if="savingTags" class="text-[10px] text-slate-400">保存中…</span>
        </div>
        <div class="flex flex-wrap gap-1 mb-1.5">
          <span
            v-for="tag in localTags"
            :key="tag"
            class="inline-flex items-center gap-1 rounded-md bg-kiwi-50 border border-kiwi-100 px-1.5 py-0.5 text-[10.5px] text-kiwi-700"
          >
            {{ tag }}
            <button class="text-kiwi-400 hover:text-rose-500" @click="removeTag(tag)">
              <KiwiIcon name="close" :size="9" />
            </button>
          </span>
          <span v-if="!localTags.length" class="text-[10.5px] text-slate-300">暂无标签</span>
        </div>
        <input
          v-model="tagInput"
          list="note-tag-options"
          class="kiwi-input !py-1 !text-[11.5px]"
          placeholder="添加标签，回车确认（支持 项目/前端）"
          @keydown.enter.prevent="addTag()"
        />
        <datalist id="note-tag-options">
          <option v-for="tag in notes.tags" :key="tag.id" :value="tag.name" />
        </datalist>
      </section>

      <!-- Wiki 关联 -->
      <section>
        <h4 class="info-title">关联 Wiki 页面</h4>
        <select
          v-model="wikiId"
          class="kiwi-input !py-1 !text-[11.5px]"
          :disabled="wikiLoading"
          @change="saveWiki"
        >
          <option value="">未关联</option>
          <option v-for="page in wikiPages" :key="page.id" :value="page.id">
            {{ page.title }}（{{ page.slug }}）
          </option>
        </select>
        <p class="mt-1 text-[10px] text-slate-400 leading-relaxed">
          关联后笔记会以节点出现在 Wiki 图谱中，并可从学习模式跳转阅读。
        </p>
      </section>

      <!-- 学习要点 -->
      <section>
        <div class="flex items-center justify-between mb-1.5">
          <h4 class="info-title !mb-0">学习要点</h4>
          <span v-if="savingPoints" class="text-[10px] text-slate-400">保存中…</span>
        </div>
        <div class="space-y-1 mb-1.5">
          <div
            v-for="point in studyPoints"
            :key="point.id"
            class="group flex items-start gap-1.5 rounded-lg bg-amber-50/60 border border-amber-100/70 px-2 py-1.5"
          >
            <KiwiIcon name="target" :size="11" class="mt-0.5 text-amber-500 shrink-0" />
            <p class="flex-1 text-[10.5px] text-amber-800 leading-relaxed">{{ point.text }}</p>
            <button
              class="text-amber-300 opacity-0 group-hover:opacity-100 hover:text-rose-500"
              @click="removePoint(point.id)"
            >
              <KiwiIcon name="close" :size="9" />
            </button>
          </div>
          <p v-if="!studyPoints.length" class="text-[10.5px] text-slate-300">
            标记易错点或重点，作为复习时的锚点
          </p>
        </div>
        <div class="flex gap-1">
          <input
            v-model="pointInput"
            class="kiwi-input !py-1 !text-[11.5px] flex-1"
            placeholder="添加学习要点…"
            @keydown.enter.prevent="addPoint"
          />
          <button class="kiwi-btn-secondary !px-2 !py-1" :disabled="!pointInput.trim()" @click="addPoint">
            <KiwiIcon name="plus" :size="11" />
          </button>
        </div>
      </section>

      <!-- 编译 -->
      <section>
        <h4 class="info-title">笔记 → Wiki</h4>
        <button
          class="kiwi-btn-secondary w-full !text-[11.5px] !py-1.5"
          :disabled="compileRunning"
          @click="compileNote"
        >
          <KiwiIcon
            :name="compileRunning ? 'loader' : 'sparkle'"
            :size="12"
            :spin="compileRunning"
          />
          {{ compileRunning ? '编译中…' : compileStatus?.compiled ? '重新编译为 Wiki' : '以此笔记触发编译' }}
        </button>
        <p class="mt-1 text-[10px] leading-relaxed text-slate-400">
          支持全部笔记类型；数据表、画布与 Notebook 会先序列化为 Markdown 再编译。
        </p>
        <div v-if="compileStatus && compileStatus.status !== 'idle'" class="mt-1.5">
          <div class="flex items-center justify-between text-[10px] text-slate-400">
            <span>
              {{
                compileStatus.status === 'succeeded'
                  ? `编译完成 · 影响 ${compileStatus.page_count} 页`
                  : compileStatus.status === 'failed'
                    ? '编译失败'
                    : '后台编译中'
              }}
            </span>
            <span class="tabular-nums">{{ Math.round(compileStatus.progress * 100) }}%</span>
          </div>
          <div class="mt-1 h-1 rounded-full bg-slate-200/70 overflow-hidden">
            <div
              class="h-full rounded-full bg-kiwi-500 transition-all"
              :style="{ width: `${Math.max(2, Math.round(compileStatus.progress * 100))}%` }"
            />
          </div>
          <p v-if="compileStatus.error" class="mt-1 text-[10px] text-rose-500">
            {{ compileStatus.error }}
          </p>
          <button
            v-if="compileStatus.job_id"
            type="button"
            class="mt-1 text-[10px] text-kiwi-600 hover:text-kiwi-700 hover:underline"
            @click="openCompileJob"
          >
            查看任务执行详情 →
          </button>
        </div>
      </section>

      <!-- 反向链接：放在信息面板顶部，替代正文末尾的重复区块 -->
      <section v-if="backlinks.length">
        <div class="flex items-center justify-between mb-1.5">
          <h4 class="info-title !mb-0">反向链接 · {{ backlinks.length }}</h4>
          <span class="text-[10px] text-slate-400">谁引用了本文</span>
        </div>
        <div class="space-y-1">
          <button
            v-for="link in backlinks"
            :key="link.id"
            class="w-full rounded-lg px-2 py-1.5 text-left hover:bg-slate-50"
            :title="link.context || link.title"
            @click="emit('open-note', link.id, props.note.id)"
          >
            <div class="flex items-center gap-1.5">
              <KiwiIcon name="link2" :size="10" class="shrink-0 text-kiwi-300" />
              <span class="truncate text-[11px] text-slate-600">{{ link.title || '无标题' }}</span>
            </div>
            <p v-if="link.context" class="mt-0.5 line-clamp-2 text-[9.5px] leading-relaxed text-slate-400">
              {{ link.context }}
            </p>
          </button>
        </div>
      </section>

      <!-- 相关笔记 -->
      <section>
        <div class="flex items-center justify-between mb-1.5">
          <h4 class="info-title !mb-0">相关笔记</h4>
          <span v-if="loadingRelated" class="text-[10px] text-slate-400">分析中…</span>
        </div>
        <div class="space-y-1">
          <button
            v-for="item in related.slice(0, 6)"
            :key="item.note.id"
            class="w-full text-left rounded-lg px-2 py-1.5 hover:bg-slate-50"
            @click="emit('open-note', item.note.id)"
          >
            <div class="flex items-center gap-1.5">
              <KiwiIcon name="file" :size="10" class="text-slate-300 shrink-0" />
              <span class="text-[11px] text-slate-600 truncate">{{ item.note.title }}</span>
            </div>
            <p class="text-[9.5px] text-slate-400 truncate">{{ item.reasons.join(' · ') }}</p>
          </button>
          <p v-if="!related.length && !loadingRelated" class="text-[10.5px] text-slate-300">
            暂无通过标签、链接或内容推断出的关联
          </p>
        </div>
      </section>

      <!-- 模板 / 生命周期 -->
      <section class="pt-1 border-t border-slate-200/60">
        <h4 class="info-title">模板</h4>
        <div class="flex gap-1">
          <input
            v-model="templateName"
            class="kiwi-input !py-1 !text-[11.5px] flex-1"
            :placeholder="note.title"
          />
          <button
            class="kiwi-btn-secondary !px-2 !py-1 !text-[10.5px]"
            :disabled="savingTemplate"
            @click="saveAsTemplate"
          >
            存为模板
          </button>
        </div>
      </section>

      <section class="pt-1 border-t border-slate-200/60 space-y-1.5">
        <button
          v-if="note.status === 'archived'"
          class="kiwi-btn-secondary w-full !text-[11.5px] !py-1.5"
          @click="unarchive"
        >
          <KiwiIcon name="folder" :size="12" />
          取消归档
        </button>
        <button
          v-else
          class="kiwi-btn-secondary w-full !text-[11.5px] !py-1.5"
          @click="archive"
        >
          <KiwiIcon name="folder" :size="12" />
          归档笔记
        </button>
        <button
          type="button"
          class="inline-flex w-full items-center justify-center gap-1.5 rounded-lg px-2 py-1.5 text-[11.5px] text-slate-400 transition-colors hover:bg-rose-50/70 hover:text-rose-600"
          title="移入回收站，可在 30 天内恢复"
          @click="trashOpen = true"
        >
          <KiwiIcon name="trash" :size="12" />
          移入回收站
        </button>
      </section>
    </div>

    <KiwiConfirm
      v-model="trashOpen"
      danger
      title="移入回收站"
      :message="`将《${note.title || '无标题'}》移入回收站？可在 30 天内从回收站恢复。`"
      confirm-text="移入回收站"
      @confirm="moveToTrash"
    />
  </aside>
</template>

<style scoped>
.info-title {
  @apply text-[10.5px] font-semibold tracking-wide text-slate-400 uppercase mb-1.5;
}
.info-row {
  @apply flex items-start justify-between gap-2;
}
.info-row dt {
  @apply shrink-0 text-slate-400;
}
.info-row dd {
  @apply text-right text-slate-600 min-w-0 break-words;
}
</style>

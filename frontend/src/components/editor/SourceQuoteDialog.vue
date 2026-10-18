<script setup lang="ts">
/**
 * 插入来源引用块：选择一条原始素材，填写引用文字（默认取编辑器选中内容），
 * 生成带来源标识、内容指纹与「查看原文」链接的 Markdown 引用块。
 */
import { computed, ref, watch } from 'vue'
import { request } from '@/api/client'
import KiwiModal from '@/components/ui/KiwiModal.vue'
import KiwiIcon from '@/components/ui/KiwiIcon.vue'
import { useKbsStore } from '@/stores/kbs'
import { toast } from '@/components/ui/toast'

interface SourceItem {
  id: string
  title: string
  type: string
  status: string
  sha256: string
  parse_quality: string
  source_url: string
}

interface SourcePreview {
  text: string
}

interface WikiQuotePage {
  id: string
  title: string
  slug: string
  page_type: string
  summary: string
  tags: string[]
  link_count: number
}

type QuoteTab = 'source' | 'wiki'

const props = withDefaults(
  defineProps<{ open: boolean; initialQuote?: string }>(),
  { open: false, initialQuote: '' },
)
const emit = defineEmits<{
  (e: 'close'): void
  (e: 'insert', payload: { markdown: string }): void
}>()

const kbs = useKbsStore()

const sources = ref<SourceItem[]>([])
const loading = ref(false)
const error = ref('')
const keyword = ref('')
const selectedId = ref('')
const quote = ref('')
const seeding = ref(false)

// 素材 / Wiki 页面两种引用来源
const tab = ref<QuoteTab>('source')
const TABS: Array<{ key: QuoteTab; label: string }> = [
  { key: 'source', label: '素材' },
  { key: 'wiki', label: 'Wiki 页面' },
]
const wikiPages = ref<WikiQuotePage[]>([])
const wikiLoading = ref(false)
const wikiError = ref('')
const selectedWikiId = ref('')

const filtered = computed(() => {
  const kw = keyword.value.trim().toLowerCase()
  if (!kw) return sources.value
  return sources.value.filter(
    (s) => s.title.toLowerCase().includes(kw) || s.type.toLowerCase().includes(kw),
  )
})
const selected = computed(() => sources.value.find((s) => s.id === selectedId.value) || null)

const filteredWiki = computed(() => {
  const kw = keyword.value.trim().toLowerCase()
  if (!kw) return wikiPages.value
  return wikiPages.value.filter(
    (p) =>
      p.title.toLowerCase().includes(kw) ||
      p.slug.toLowerCase().includes(kw) ||
      p.tags.some((tag) => tag.toLowerCase().includes(kw)),
  )
})
const selectedWiki = computed(
  () => wikiPages.value.find((p) => p.id === selectedWikiId.value) || null,
)
const ready = computed(() =>
  tab.value === 'source'
    ? !!selected.value && !!quote.value.trim()
    : !!selectedWiki.value && !!quote.value.trim(),
)

const QUALITY_LABEL: Record<string, string> = {
  clean: '解析良好',
  ocr_aided: 'OCR 辅助',
  review: '待复核',
}

const WIKI_TYPE_LABEL: Record<string, string> = {
  entity: '实体',
  concept: '概念',
  summary: '摘要',
  synthesis: '综合',
}

function escapeMarkdown(text: string): string {
  return text.replace(/[[\]]/g, (ch) => `\\${ch}`)
}

async function loadSources() {
  loading.value = true
  error.value = ''
  try {
    sources.value = await request<SourceItem[]>('/sources', { kbId: kbs.currentKbId })
    if (!selectedId.value && sources.value.length) selectedId.value = sources.value[0].id
  } catch (e: any) {
    error.value = e.message || '素材加载失败'
    sources.value = []
  } finally {
    loading.value = false
  }
}

/** 未选中文字时，用素材开头片段做默认引用。 */
async function seedQuote(sourceId: string) {
  if (quote.value.trim()) return
  seeding.value = true
  try {
    const preview = await request<SourcePreview>(`/sources/${sourceId}/preview`, {
      kbId: kbs.currentKbId,
    })
    const text = (preview.text || '').replace(/\s+/g, ' ').trim()
    if (text && !quote.value.trim()) quote.value = text.slice(0, 260)
  } catch {
    /* 预览失败不阻塞手写引用 */
  } finally {
    seeding.value = false
  }
}

function pick(id: string) {
  selectedId.value = id
  void seedQuote(id)
}

/** 去掉 Markdown 标记，用作默认引用片段。 */
function plainMarkdown(md: string): string {
  return md
    .replace(/^---\r?\n[\s\S]*?\r?\n---\r?\n?/, '')
    .replace(/```[\s\S]*?```/g, ' ')
    .replace(/!\[[^\]]*\]\([^)]*\)/g, ' ')
    .replace(/\[([^\]]+)\]\([^)]*\)/g, '$1')
    .replace(/^#{1,6}\s+/gm, '')
    .replace(/[*_~`>#-]/g, '')
    .replace(/\s+/g, ' ')
    .trim()
}

async function loadWikiPages() {
  wikiLoading.value = true
  wikiError.value = ''
  try {
    wikiPages.value = await request<WikiQuotePage[]>('/wiki', { kbId: kbs.currentKbId })
    if (!selectedWikiId.value && wikiPages.value.length) {
      selectedWikiId.value = wikiPages.value[0].id
    }
  } catch (e: any) {
    wikiError.value = e.message || 'Wiki 页面加载失败'
    wikiPages.value = []
  } finally {
    wikiLoading.value = false
  }
}

/** 优先用列表自带的摘要；摘要为空时再取详情正文。 */
async function seedWikiQuote(id: string) {
  if (quote.value.trim()) return
  const page = wikiPages.value.find((p) => p.id === id)
  let text = (page?.summary || '').trim()
  if (!text) {
    seeding.value = true
    try {
      const detail = await request<{ body_md: string }>(`/wiki/${id}`, {
        kbId: kbs.currentKbId,
      })
      text = plainMarkdown(detail.body_md || '')
    } catch {
      /* 详情读取失败不阻塞手写引用 */
    } finally {
      seeding.value = false
    }
  }
  if (text && !quote.value.trim()) quote.value = text.slice(0, 260)
}

function switchTab(next: QuoteTab) {
  if (tab.value === next) return
  tab.value = next
  keyword.value = ''
  quote.value = props.initialQuote || ''
  if (next === 'wiki') {
    if (!wikiPages.value.length) void loadWikiPages()
    else if (selectedWikiId.value) void seedWikiQuote(selectedWikiId.value)
  } else if (selectedId.value) {
    void seedQuote(selectedId.value)
  }
}

function submit() {
  if (tab.value === 'wiki') {
    submitWiki()
    return
  }
  const source = selected.value
  if (!source) {
    toast.info('先选择一条素材')
    return
  }
  const text = quote.value.trim()
  if (!text) {
    toast.info('请填写要引用的原文片段')
    return
  }
  const title = escapeMarkdown(source.title || '未命名素材')
  const fingerprint = (source.sha256 || '').slice(0, 12)
  const anchor = text.replace(/\s+/g, ' ').slice(0, 120)
  const link = `/sources/${source.id}?q=${encodeURIComponent(anchor)}`
  const quoted = text
    .split(/\r?\n/)
    .map((line) => `> ${line}`)
    .join('\n')
  const markdown =
    `> **《${title}》** · 指纹 \`${fingerprint}\` · [查看原文](${link})\n` +
    `>\n${quoted}`
  emit('insert', { markdown })
  emit('close')
}

function submitWiki() {
  const page = selectedWiki.value
  if (!page) {
    toast.info('先选择一个 Wiki 页面')
    return
  }
  const text = quote.value.trim()
  if (!text) {
    toast.info('请填写要引用的页面内容')
    return
  }
  const title = escapeMarkdown(page.title || '未命名页面')
  const typeLabel = WIKI_TYPE_LABEL[page.page_type] || 'Wiki'
  const anchor = text.replace(/\s+/g, ' ').slice(0, 120)
  const link = `/wiki/${page.id}?q=${encodeURIComponent(anchor)}`
  const quoted = text
    .split(/\r?\n/)
    .map((line) => `> ${line}`)
    .join('\n')
  const markdown =
    `> **《${title}》** · ${typeLabel} · [查看页面](${link})\n` +
    `>\n${quoted}`
  emit('insert', { markdown })
  emit('close')
}

watch(
  () => props.open,
  (open) => {
    if (!open) return
    tab.value = 'source'
    keyword.value = ''
    quote.value = props.initialQuote || ''
    void loadSources()
  },
)

watch(selectedId, (id) => {
  if (id) void seedQuote(id)
})

watch(selectedWikiId, (id) => {
  if (id && tab.value === 'wiki') void seedWikiQuote(id)
})
</script>

<template>
  <KiwiModal :open="open" title="插入引用块" max-w="max-w-2xl" @close="emit('close')">
    <p class="mb-2 text-[11px] leading-relaxed text-slate-400">
      {{
        tab === 'source'
          ? '引用块会带上素材标题、内容指纹与「查看原文」链接；点击链接可跳转到原文并高亮该片段。'
          : '引用块会带上 Wiki 页面标题、页面类型与「查看页面」链接，便于回到知识页核对上下文。'
      }}
    </p>

    <div class="mb-3 inline-flex rounded-xl border border-slate-200/80 bg-white/70 p-0.5">
      <button
        v-for="t in TABS"
        :key="t.key"
        type="button"
        class="rounded-lg px-2.5 py-1 text-[11px] transition-colors"
        :class="
          tab === t.key
            ? 'bg-kiwi-50 font-medium text-kiwi-700 shadow-sm'
            : 'text-slate-500 hover:text-slate-700'
        "
        @click="switchTab(t.key)"
      >
        {{ t.label }}
      </button>
    </div>

    <div class="grid gap-3 md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
      <!-- 素材选择 -->
      <div
        v-if="tab === 'source'"
        class="flex min-h-0 flex-col rounded-xl border border-slate-200 bg-white/70"
      >
        <div class="border-b border-slate-100 p-2">
          <div class="relative">
            <KiwiIcon
              name="search"
              :size="12"
              class="pointer-events-none absolute left-2 top-1/2 -translate-y-1/2 text-slate-400"
            />
            <input
              v-model="keyword"
              class="kiwi-input !py-1.5 !pl-7 !text-[11.5px]"
              placeholder="搜索素材标题 / 类型"
            />
          </div>
        </div>
        <div class="max-h-64 min-h-[120px] overflow-y-auto p-1">
          <div v-if="loading" class="grid h-24 place-items-center text-[11px] text-slate-400">
            <span class="inline-flex items-center gap-1.5">
              <KiwiIcon name="loader" :size="12" spin class="text-kiwi-500" />
              加载素材…
            </span>
          </div>
          <p v-else-if="error" class="p-3 text-[11px] text-rose-500">{{ error }}</p>
          <p v-else-if="!filtered.length" class="p-3 text-[11px] text-slate-400">
            没有匹配的素材，请先导入资料。
          </p>
          <button
            v-for="source in filtered"
            :key="source.id"
            type="button"
            class="mb-0.5 flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left hover:bg-kiwi-50/70"
            :class="selectedId === source.id ? 'bg-kiwi-50 text-kiwi-700' : 'text-slate-600'"
            @click="pick(source.id)"
          >
            <KiwiIcon
              :name="source.type === 'pdf' ? 'file' : 'fileText'"
              :size="12"
              class="shrink-0 text-slate-400"
            />
            <span class="min-w-0 flex-1">
              <span class="block truncate text-[11.5px]">{{ source.title }}</span>
              <span class="text-[9.5px] text-slate-400">
                {{ source.type.toUpperCase() }} ·
                {{ QUALITY_LABEL[source.parse_quality] || source.parse_quality }}
              </span>
            </span>
            <KiwiIcon
              v-if="selectedId === source.id"
              name="check"
              :size="12"
              class="shrink-0 text-kiwi-500"
            />
          </button>
        </div>
      </div>

      <!-- Wiki 页面选择 -->
      <div v-else class="flex min-h-0 flex-col rounded-xl border border-slate-200 bg-white/70">
        <div class="border-b border-slate-100 p-2">
          <div class="relative">
            <KiwiIcon
              name="search"
              :size="12"
              class="pointer-events-none absolute left-2 top-1/2 -translate-y-1/2 text-slate-400"
            />
            <input
              v-model="keyword"
              class="kiwi-input !py-1.5 !pl-7 !text-[11.5px]"
              placeholder="搜索 Wiki 标题 / 标签"
            />
          </div>
        </div>
        <div class="max-h-64 min-h-[120px] overflow-y-auto p-1">
          <div v-if="wikiLoading" class="grid h-24 place-items-center text-[11px] text-slate-400">
            <span class="inline-flex items-center gap-1.5">
              <KiwiIcon name="loader" :size="12" spin class="text-kiwi-500" />
              加载 Wiki 页面…
            </span>
          </div>
          <p v-else-if="wikiError" class="p-3 text-[11px] text-rose-500">{{ wikiError }}</p>
          <p v-else-if="!filteredWiki.length" class="p-3 text-[11px] text-slate-400">
            没有匹配的 Wiki 页面。
          </p>
          <button
            v-for="pageItem in filteredWiki"
            :key="pageItem.id"
            type="button"
            class="mb-0.5 flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left hover:bg-kiwi-50/70"
            :class="selectedWikiId === pageItem.id ? 'bg-kiwi-50 text-kiwi-700' : 'text-slate-600'"
            @click="selectedWikiId = pageItem.id"
          >
            <KiwiIcon name="wiki" :size="12" class="shrink-0 text-kiwi-400" />
            <span class="min-w-0 flex-1">
              <span class="block truncate text-[11.5px]">{{ pageItem.title }}</span>
              <span class="block truncate text-[9.5px] text-slate-400">
                {{ WIKI_TYPE_LABEL[pageItem.page_type] || 'Wiki' }} ·
                {{ pageItem.link_count }} 链接
                <template v-if="pageItem.tags.length">
                  · {{ pageItem.tags.slice(0, 2).join(' / ') }}
                </template>
              </span>
            </span>
            <KiwiIcon
              v-if="selectedWikiId === pageItem.id"
              name="check"
              :size="12"
              class="shrink-0 text-kiwi-500"
            />
          </button>
        </div>
      </div>

      <!-- 引用内容 -->
      <div class="flex min-h-0 flex-col rounded-xl border border-slate-200 bg-white/70 p-2.5">
        <div class="mb-1 flex items-center gap-1.5">
          <span class="text-[11px] font-medium text-slate-500">引用文字</span>
          <span v-if="seeding" class="inline-flex items-center gap-1 text-[9.5px] text-slate-400">
            <KiwiIcon name="loader" :size="10" spin />
            {{ tab === 'source' ? '读取素材开头…' : '读取页面摘要…' }}
          </span>
          <button
            v-if="initialQuote && quote !== initialQuote"
            type="button"
            class="ml-auto text-[10px] text-kiwi-600 hover:underline"
            @click="quote = initialQuote"
          >
            恢复选中内容
          </button>
        </div>
        <textarea
          v-model="quote"
          rows="6"
          class="kiwi-input min-h-[128px] flex-1 resize-none !text-[12px] leading-relaxed"
          placeholder="粘贴或输入要引用的原文片段…"
        />
        <div
          v-if="tab === 'source' && selected"
          class="mt-1.5 truncate text-[9.5px] text-slate-400"
        >
          来源指纹：<code class="rounded bg-slate-100 px-1">{{ selected.sha256.slice(0, 12) }}</code>
        </div>
        <div
          v-else-if="tab === 'wiki' && selectedWiki"
          class="mt-1.5 truncate text-[9.5px] text-slate-400"
        >
          Wiki 页面：{{ WIKI_TYPE_LABEL[selectedWiki.page_type] || 'Wiki' }} ·
          <code class="rounded bg-slate-100 px-1">{{ selectedWiki.slug }}</code>
        </div>
      </div>
    </div>

    <div class="mt-4 flex items-center justify-end gap-2">
      <button type="button" class="kiwi-btn-secondary" @click="emit('close')">取消</button>
      <button type="button" class="kiwi-btn-primary" :disabled="!ready" @click="submit">
        <KiwiIcon name="quote" :size="13" />
        插入引用块
      </button>
    </div>
  </KiwiModal>
</template>

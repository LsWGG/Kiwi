<script setup lang="ts">
/** 素材原文阅读页：引用块「查看原文」目标，支持 ?q= 高亮定位。 */
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { request } from '@/api/client'
import { useKbsStore } from '@/stores/kbs'
import KiwiIcon from '@/components/ui/KiwiIcon.vue'

interface SourcePreview {
  id: string
  kb_id: string
  title: string
  type: string
  sha256: string
  source_url: string
  parse_quality: string
  parse_engine: string
  text: string
  truncated: boolean
}

const route = useRoute()
const router = useRouter()
const kbs = useKbsStore()

const preview = ref<SourcePreview | null>(null)
const loading = ref(false)
const error = ref('')
const sourceId = computed(() => String(route.params.id || ''))
const query = computed(() => String(route.query.q || '').trim())

const fingerprint = computed(() => (preview.value?.sha256 || '').slice(0, 12))

const parts = computed(() => {
  const text = preview.value?.text || ''
  const q = query.value
  if (!q) return [{ text, hit: false }]
  const index = text.indexOf(q)
  if (index < 0) return [{ text, hit: false }]
  return [
    { text: text.slice(0, index), hit: false },
    { text: q, hit: true },
    { text: text.slice(index + q.length), hit: false },
  ]
})

const QUALITY_LABEL: Record<string, string> = {
  clean: '解析良好',
  ocr_aided: 'OCR 辅助',
  review: '待复核',
}

async function load() {
  if (!sourceId.value || !kbs.currentKbId) return
  loading.value = true
  error.value = ''
  try {
    preview.value = await request<SourcePreview>(
      `/sources/${sourceId.value}/preview`,
      { kbId: kbs.currentKbId },
    )
    await nextTick()
    document.querySelector<HTMLElement>('.source-text mark')?.scrollIntoView({ block: 'center' })
  } catch (e: any) {
    error.value = e.message || '素材加载失败'
    preview.value = null
  } finally {
    loading.value = false
  }
}

watch(() => [sourceId.value, kbs.currentKbId], () => void load())
onMounted(() => void load())
</script>

<template>
  <div class="mx-auto flex h-full max-w-4xl flex-col px-6 py-5">
    <div class="mb-3 flex items-center gap-2">
      <button type="button" class="kiwi-btn-secondary !px-2.5 !py-1.5" @click="router.back()">
        <KiwiIcon name="arrowLeft" :size="13" />
        返回
      </button>
      <h1 class="min-w-0 truncate text-[15px] font-semibold text-slate-800">
        {{ preview?.title || '素材原文' }}
      </h1>
      <span
        v-if="preview"
        class="shrink-0 rounded-full bg-slate-100 px-2 py-0.5 text-[10px] text-slate-500"
      >
        {{ preview.type.toUpperCase() }} · {{ QUALITY_LABEL[preview.parse_quality] || preview.parse_quality }}
      </span>
      <a
        v-if="preview?.source_url"
        :href="preview.source_url"
        target="_blank"
        rel="noopener noreferrer"
        class="ml-auto inline-flex shrink-0 items-center gap-1 text-[11px] text-kiwi-600 hover:underline"
      >
        <KiwiIcon name="external" :size="12" />
        原始链接
      </a>
    </div>

    <div
      v-if="preview"
      class="mb-3 flex flex-wrap items-center gap-x-4 gap-y-1 rounded-lg border border-slate-200 bg-slate-50/70 px-3 py-1.5 text-[10.5px] text-slate-500"
    >
      <span>指纹 <code class="rounded bg-white px-1 py-0.5 text-slate-600">{{ fingerprint }}</code></span>
      <span>解析引擎 {{ preview.parse_engine }}</span>
      <span v-if="preview.text">约 {{ preview.text.length.toLocaleString() }} 字</span>
      <span v-if="query && !parts.some((p) => p.hit)" class="text-amber-600">
        未在原文中找到引用片段，已展示全文
      </span>
      <span v-else-if="query" class="text-emerald-600">已定位到引用位置</span>
      <span v-if="preview.truncated" class="text-amber-600">原文过长，仅展示前 40 万字</span>
    </div>

    <div class="min-h-0 flex-1 overflow-y-auto rounded-xl border border-slate-200 bg-white">
      <div v-if="loading" class="grid h-40 place-items-center text-[12px] text-slate-400">
        <span class="inline-flex items-center gap-2">
          <KiwiIcon name="loader" :size="14" spin class="text-kiwi-500" />
          正在解析素材原文…
        </span>
      </div>
      <p v-else-if="error" class="p-6 text-[12px] text-rose-500">{{ error }}</p>
      <pre
        v-else-if="preview"
        class="source-text whitespace-pre-wrap break-words px-6 py-5 text-[13px] leading-7 text-slate-700"
      ><template v-for="(part, i) in parts" :key="i"><mark v-if="part.hit" class="rounded bg-amber-200/80 px-0.5 text-slate-800">{{ part.text }}</mark><template v-else>{{ part.text }}</template></template></pre>
    </div>
  </div>
</template>

<style scoped>
.source-text {
  font-family: 'Noto Serif SC', 'Songti SC', Georgia, serif;
}
</style>

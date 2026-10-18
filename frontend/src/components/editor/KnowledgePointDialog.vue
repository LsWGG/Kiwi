<script setup lang="ts">
/**
 * 关联知识点：把一段学习笔记标记为某个知识点关联块。
 * 块内保存 `#kiwi-topic-<id>` 标记，学习模式复习时据此引用「我的笔记」。
 */
import { computed, ref, watch } from 'vue'
import { request } from '@/api/client'
import KiwiModal from '@/components/ui/KiwiModal.vue'
import KiwiIcon from '@/components/ui/KiwiIcon.vue'
import { useKbsStore } from '@/stores/kbs'
import { toast } from '@/components/ui/toast'

interface TopicItem {
  id: string
  slug: string
  title: string
  domain: string
  mastery: number
  weak: boolean
  wiki_page_id: string | null
}

const props = withDefaults(
  defineProps<{ open: boolean; initialText?: string }>(),
  { open: false, initialText: '' },
)
const emit = defineEmits<{
  (e: 'close'): void
  (e: 'insert', payload: { html: string }): void
}>()

const kbs = useKbsStore()
const topics = ref<TopicItem[]>([])
const loading = ref(false)
const error = ref('')
const keyword = ref('')
const selectedId = ref('')
const excerpt = ref('')

const filtered = computed(() => {
  const kw = keyword.value.trim().toLowerCase()
  if (!kw) return topics.value
  return topics.value.filter(
    (t) =>
      t.title.toLowerCase().includes(kw) ||
      t.slug.toLowerCase().includes(kw) ||
      t.domain.toLowerCase().includes(kw),
  )
})
const selected = computed(() => topics.value.find((t) => t.id === selectedId.value) || null)

function escapeHtml(text: string): string {
  return text.replace(/[&<>"']/g, (ch) => {
    const map: Record<string, string> = {
      '&': '&amp;',
      '<': '&lt;',
      '>': '&gt;',
      '"': '&quot;',
      "'": '&#39;',
    }
    return map[ch]
  })
}

function paragraphs(text: string): string {
  return text
    .split(/\n{2,}/)
    .map((part) => `<p>${escapeHtml(part).replace(/\n/g, '<br>')}</p>`)
    .join('')
}

async function loadTopics() {
  loading.value = true
  error.value = ''
  try {
    topics.value = await request<TopicItem[]>('/study/topics', { kbId: kbs.currentKbId })
    if (!selectedId.value && topics.value.length) selectedId.value = topics.value[0].id
  } catch (e: any) {
    error.value = e.message || '知识点加载失败'
    topics.value = []
  } finally {
    loading.value = false
  }
}

function submit() {
  const topic = selected.value
  const text = excerpt.value.trim()
  if (!topic) {
    toast.info('先选择一个知识点')
    return
  }
  if (!text) {
    toast.info('请填写要关联的学习笔记内容')
    return
  }
  const marker = `#kiwi-topic-${topic.id}`
  const percent = Math.round((topic.mastery || 0) * 100)
  const html =
    `<div data-type="callout" data-emoji="🎯">` +
    `<p><strong><a href="${marker}">关联知识点：${escapeHtml(topic.title)}</a></strong>` +
    ` · 当前掌握度 ${percent}%</p>` +
    paragraphs(text) +
    `</div>`
  emit('insert', { html })
  emit('close')
}

watch(
  () => props.open,
  (open) => {
    if (!open) return
    keyword.value = ''
    excerpt.value = props.initialText || ''
    void loadTopics()
  },
)
</script>

<template>
  <KiwiModal :open="open" title="关联知识点" max-w="max-w-2xl" @close="emit('close')">
    <p class="mb-3 text-[11px] leading-relaxed text-slate-400">
      关联块会写入笔记正文；学习模式复习该知识点时，会把这段内容作为「我的笔记」一并展示。
    </p>

    <div class="grid gap-3 md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
      <div class="flex min-h-0 flex-col rounded-xl border border-slate-200 bg-white/70">
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
              placeholder="搜索知识点 / 领域"
            />
          </div>
        </div>
        <div class="max-h-64 min-h-[120px] overflow-y-auto p-1">
          <div v-if="loading" class="grid h-24 place-items-center text-[11px] text-slate-400">
            <span class="inline-flex items-center gap-1.5">
              <KiwiIcon name="loader" :size="12" spin class="text-kiwi-500" />
              加载知识点…
            </span>
          </div>
          <p v-else-if="error" class="p-3 text-[11px] text-rose-500">{{ error }}</p>
          <p v-else-if="!filtered.length" class="p-3 text-[11px] text-slate-400">
            还没有知识点。先在 Wiki 中编译页面，或在学习模式完成冷启动。
          </p>
          <button
            v-for="topic in filtered"
            :key="topic.id"
            type="button"
            class="mb-0.5 flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left hover:bg-kiwi-50/70"
            :class="selectedId === topic.id ? 'bg-kiwi-50 text-kiwi-700' : 'text-slate-600'"
            @click="selectedId = topic.id"
          >
            <span class="min-w-0 flex-1">
              <span class="block truncate text-[11.5px]">{{ topic.title }}</span>
              <span class="text-[9.5px] text-slate-400">
                {{ topic.domain || '未分领域' }} · 掌握度
                {{ Math.round(topic.mastery * 100) }}%
              </span>
            </span>
            <span
              v-if="topic.weak"
              class="shrink-0 rounded bg-amber-100 px-1 py-0.5 text-[9px] text-amber-700"
            >
              薄弱
            </span>
            <KiwiIcon
              v-if="selectedId === topic.id"
              name="check"
              :size="12"
              class="shrink-0 text-kiwi-500"
            />
          </button>
        </div>
      </div>

      <div class="flex min-h-0 flex-col rounded-xl border border-slate-200 bg-white/70 p-2.5">
        <div class="mb-1 flex items-center gap-1.5">
          <span class="text-[11px] font-medium text-slate-500">我的笔记</span>
          <button
            v-if="initialText && excerpt !== initialText"
            type="button"
            class="ml-auto text-[10px] text-kiwi-600 hover:underline"
            @click="excerpt = initialText"
          >
            恢复选中内容
          </button>
        </div>
        <textarea
          v-model="excerpt"
          rows="6"
          class="kiwi-input min-h-[128px] flex-1 resize-none !text-[12px] leading-relaxed"
          placeholder="写下你对这个知识点的理解、易错点或记忆线索…"
        />
        <div v-if="selected" class="mt-1.5 truncate text-[9.5px] text-slate-400">
          关联到：{{ selected.title }}
        </div>
      </div>
    </div>

    <div class="mt-4 flex items-center justify-end gap-2">
      <button type="button" class="kiwi-btn-secondary" @click="emit('close')">取消</button>
      <button
        type="button"
        class="kiwi-btn-primary"
        :disabled="!selected || !excerpt.trim()"
        @click="submit"
      >
        <KiwiIcon name="target" :size="13" />
        插入关联块
      </button>
    </div>
  </KiwiModal>
</template>

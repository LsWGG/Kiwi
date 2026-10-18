<script setup lang="ts">
/** Wiki 正文渲染：支持 [[双链]]、标题锚点、表格横向滚动与任务列表。 */
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import {
  createWikiMarkdown,
  normalizeWikiKey,
  type WikiLinkTarget,
} from '@/lib/wikiMarkdown'

const props = withDefaults(
  defineProps<{
    content: string
    /** 全库页面索引，用于把 [[slug]] / [[标题]] 解析为路由链接 */
    pages?: WikiLinkTarget[]
  }>(),
  { pages: () => [] },
)

const router = useRouter()
const md = createWikiMarkdown()

const lookup = computed(() => {
  const map = new Map<string, WikiLinkTarget>()
  for (const page of props.pages) {
    map.set(normalizeWikiKey(page.slug), page)
    map.set(normalizeWikiKey(page.title), page)
  }
  return map
})

const html = computed(() =>
  md.render(props.content || '', {
    resolveWikiLink: (target: string) => lookup.value.get(normalizeWikiKey(target)) ?? null,
  }),
)

function onClick(event: MouseEvent) {
  const anchor = (event.target as HTMLElement | null)?.closest('a')
  if (!(anchor instanceof HTMLAnchorElement)) return
  const wikiId = anchor.dataset.wikiId
  if (wikiId) {
    event.preventDefault()
    void router.push({ name: 'wiki-page', params: { id: wikiId } })
    return
  }
  if (anchor.dataset.wikiMissing !== undefined) {
    event.preventDefault()
    return
  }
  const href = anchor.getAttribute('href') ?? ''
  if (href.startsWith('#')) {
    event.preventDefault()
    const el = document.getElementById(href.slice(1))
    el?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }
}
</script>

<template>
  <div class="prose-wiki wiki-body" @click="onClick" v-html="html" />
</template>

<style scoped>
.wiki-body :deep(.wiki-link) {
  @apply rounded px-0.5 font-medium text-kiwi-600 underline decoration-kiwi-300 decoration-2 underline-offset-2 transition-colors hover:text-kiwi-700;
}
.wiki-body :deep(.wiki-link-missing) {
  @apply cursor-not-allowed border-b border-dashed border-rose-300 px-0.5 text-rose-400 no-underline;
}
.wiki-body :deep(.wiki-heading) {
  scroll-margin-top: 5rem;
}
.wiki-body :deep(table) {
  @apply my-4;
}
</style>

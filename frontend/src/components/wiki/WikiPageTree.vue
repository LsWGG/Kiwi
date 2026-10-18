<script setup lang="ts">
/**
 * Wiki 页面树：按页面类型分组，支持搜索、折叠与当前页高亮。
 * 数据来自 GET /wiki 列表，供详情页左栏与窄屏抽屉复用。
 */
import { computed, ref, watch } from 'vue'
import KiwiIcon from '@/components/ui/KiwiIcon.vue'
import KiwiSkeleton from '@/components/ui/KiwiSkeleton.vue'

interface TreePage {
  id: string
  slug: string
  title: string
  page_type: string
  annotation_count?: number
}

const props = withDefaults(
  defineProps<{
    pages: TreePage[]
    activeId?: string
    loading?: boolean
  }>(),
  { activeId: '', loading: false },
)

const emit = defineEmits<{
  (e: 'select', id: string): void
}>()

const TYPE_ORDER = ['entity', 'concept', 'summary', 'synthesis']
const TYPE_LABEL: Record<string, string> = {
  entity: '实体',
  concept: '概念',
  summary: '摘要',
  synthesis: '综合',
}
const TYPE_TONE: Record<string, string> = {
  entity: 'text-sky-500',
  concept: 'text-kiwi-500',
  summary: 'text-amber-500',
  synthesis: 'text-violet-500',
}

const query = ref('')
const collapsed = ref<Set<string>>(new Set())

const groups = computed(() => {
  const keyword = query.value.trim().toLowerCase()
  const buckets = new Map<string, TreePage[]>()
  for (const page of props.pages) {
    if (
      keyword &&
      !page.title.toLowerCase().includes(keyword) &&
      !page.slug.toLowerCase().includes(keyword)
    ) {
      continue
    }
    const type = TYPE_ORDER.includes(page.page_type) ? page.page_type : 'other'
    const list = buckets.get(type) ?? []
    list.push(page)
    buckets.set(type, list)
  }
  const order = [...TYPE_ORDER, 'other']
  return order
    .filter((type) => (buckets.get(type)?.length ?? 0) > 0)
    .map((type) => ({
      type,
      label: TYPE_LABEL[type] ?? '其他',
      tone: TYPE_TONE[type] ?? 'text-slate-400',
      pages: (buckets.get(type) ?? []).sort((a, b) =>
        a.title.localeCompare(b.title, 'zh-CN'),
      ),
    }))
})

// 搜索时自动展开；无搜索词时尊重用户折叠状态
watch(query, (value) => {
  if (value.trim()) collapsed.value = new Set()
})

function toggle(type: string) {
  const next = new Set(collapsed.value)
  if (next.has(type)) next.delete(type)
  else next.add(type)
  collapsed.value = next
}

function select(id: string) {
  if (id === props.activeId) return
  emit('select', id)
}
</script>

<template>
  <div class="flex h-full min-h-0 flex-col">
    <div class="relative mb-2 shrink-0">
      <KiwiIcon
        name="search"
        :size="12"
        class="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-300"
      />
      <input
        v-model="query"
        class="w-full rounded-lg border border-slate-200/80 bg-white/70 py-1.5 pl-7 pr-2 text-[11.5px] text-slate-600 outline-none placeholder:text-slate-300 focus:border-kiwi-300"
        placeholder="搜索页面标题或 slug"
      />
    </div>

    <div class="min-h-0 flex-1 overflow-y-auto pr-0.5">
      <KiwiSkeleton v-if="loading && !pages.length" variant="row" :cols="6" />
      <p
        v-else-if="!groups.length"
        class="py-6 text-center text-[11px] text-slate-300"
      >
        {{ query ? '没有匹配的页面' : '暂无 Wiki 页面' }}
      </p>

      <div v-for="group in groups" :key="group.type" class="mb-1.5">
        <button
          class="flex w-full items-center gap-1.5 rounded-md px-1.5 py-1 text-[10.5px] font-medium text-slate-400 hover:bg-white/60 hover:text-slate-600"
          @click="toggle(group.type)"
        >
          <KiwiIcon
            name="chevronRight"
            :size="10"
            class="transition-transform"
            :class="collapsed.has(group.type) ? '' : 'rotate-90'"
          />
          <span :class="group.tone">{{ group.label }}</span>
          <span class="ml-auto tabular-nums text-slate-300">{{ group.pages.length }}</span>
        </button>
        <div v-show="!collapsed.has(group.type)" class="space-y-0.5">
          <button
            v-for="page in group.pages"
            :key="page.id"
            class="group flex w-full items-center gap-1.5 rounded-lg px-2 py-1.5 text-left transition-colors"
            :class="
              page.id === activeId
                ? 'bg-kiwi-100/80 text-kiwi-800'
                : 'text-slate-600 hover:bg-white/70'
            "
            :title="page.slug"
            @click="select(page.id)"
          >
            <KiwiIcon
              name="file"
              :size="11"
              class="shrink-0"
              :class="page.id === activeId ? 'text-kiwi-500' : 'text-slate-300'"
            />
            <span class="min-w-0 flex-1 truncate text-[11.5px]">{{ page.title }}</span>
            <span
              v-if="page.annotation_count"
              class="shrink-0 rounded bg-amber-100/70 px-1 text-[9px] text-amber-600"
              title="学习批注数量"
            >
              {{ page.annotation_count }}
            </span>
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

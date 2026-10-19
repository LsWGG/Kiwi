<script setup lang="ts">
/** 全局键盘快捷键面板：分类筛选 + 即时搜索，入口在顶栏与 `?` 键。 */
import { computed, nextTick, ref, watch } from 'vue'
import KiwiModal from '@/components/ui/KiwiModal.vue'
import KiwiIcon from '@/components/ui/KiwiIcon.vue'
import { SHORTCUT_GROUPS, type ShortcutGroup } from '@/constants/shortcuts'

const props = defineProps<{ open: boolean }>()
const emit = defineEmits<{ (e: 'close'): void }>()

const query = ref('')
const activeGroup = ref('all')
const searchEl = ref<HTMLInputElement | null>(null)

watch(
  () => props.open,
  async (open) => {
    if (!open) return
    query.value = ''
    activeGroup.value = 'all'
    await nextTick()
    searchEl.value?.focus()
  },
)

watch(query, (value) => {
  if (value.trim()) activeGroup.value = 'all'
})

const groupTabs = computed(() => [
  {
    id: 'all',
    title: '全部',
    count: SHORTCUT_GROUPS.reduce((sum, group) => sum + group.items.length, 0),
  },
  ...SHORTCUT_GROUPS.map((group) => ({
    id: group.id,
    title: group.title,
    count: group.items.length,
  })),
])

/** 让「Ctrl + K」也能命中「Ctrl / Cmd + K」。 */
function normalize(text: string): string {
  return text
    .toLowerCase()
    .replace(/\s*\/\s*cmd\b/g, '')
    .replace(/\s+/g, ' ')
    .trim()
}

const filteredGroups = computed<ShortcutGroup[]>(() => {
  const q = normalize(query.value)
  // 搜索始终覆盖全部分组；仅在没有搜索词时按分类筛选。
  const source = q
    ? SHORTCUT_GROUPS
    : activeGroup.value === 'all'
      ? SHORTCUT_GROUPS
      : SHORTCUT_GROUPS.filter((group) => group.id === activeGroup.value)
  if (!q) return source
  return source
    .map((group) => ({
      ...group,
      items: group.items.filter((item) =>
        [item.label, item.keys, item.hint ?? ''].some((text) => normalize(text).includes(q)),
      ),
    }))
    .filter((group) => group.items.length > 0)
})

const total = computed(() =>
  filteredGroups.value.reduce((sum, group) => sum + group.items.length, 0),
)

/** 单个分类条目较多时铺成两列，减少滚动；少量结果保持单列更易读。 */
const singleGroupWide = computed(() => {
  const groups = filteredGroups.value
  return groups.length === 1 && groups[0].items.length > 8
})

/** 把 `Ctrl / Cmd + Shift + Z` 拆成独立键帽，长组合键更易读。 */
function keyParts(keys: string): string[] {
  return keys.split(' + ')
}
</script>

<template>
  <KiwiModal :open="open" title="键盘快捷键" max-w="max-w-5xl" @close="emit('close')">
    <div class="space-y-4">
      <!-- 搜索 -->
      <div class="relative">
        <span class="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-300">
          <KiwiIcon name="search" :size="14" />
        </span>
        <input
          ref="searchEl"
          v-model="query"
          class="kiwi-input !pl-9 !pr-9"
          placeholder="搜索功能或按键，例如「分页」「Delete」"
        />
        <button
          v-if="query"
          type="button"
          class="absolute right-2 top-1/2 grid h-6 w-6 -translate-y-1/2 place-items-center rounded-md text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-600"
          title="清空搜索"
          @click="query = ''"
        >
          <KiwiIcon name="close" :size="12" />
        </button>
      </div>

      <!-- 分类筛选 -->
      <div class="-mt-1 flex flex-wrap items-center gap-1.5">
        <button
          v-for="tab in groupTabs"
          :key="tab.id"
          type="button"
          class="inline-flex items-center gap-1 rounded-full border px-2.5 py-1 text-[11px] leading-none transition-all duration-150"
          :class="
            activeGroup === tab.id
              ? 'border-kiwi-200 bg-kiwi-50 font-medium text-kiwi-700 shadow-[0_1px_2px_rgba(90,85,199,0.08)]'
              : 'border-slate-200/80 bg-white/60 text-slate-500 hover:border-kiwi-200 hover:bg-white hover:text-kiwi-600'
          "
          :aria-pressed="activeGroup === tab.id"
          @click="activeGroup = tab.id"
        >
          {{ tab.title }}
          <span class="text-[10px] tabular-nums opacity-60">{{ tab.count }}</span>
        </button>
      </div>

      <!-- 说明 -->
      <div
        class="flex flex-wrap items-center gap-x-2 gap-y-1 rounded-lg bg-slate-50/70 px-3 py-2 text-[10.5px] leading-relaxed text-slate-400"
      >
        <span>
          <kbd class="font-mono text-slate-500">Ctrl / Cmd</kbd>
          表示 Windows / Linux 的 Ctrl 或 macOS 的 ⌘
        </span>
        <span class="text-slate-200">·</span>
        <span>快捷键只在当前上下文生效，输入框内不会误触发</span>
        <span class="ml-auto shrink-0 rounded-full bg-white px-2 py-0.5 tabular-nums text-slate-500 shadow-sm">
          {{ total }} 项
        </span>
      </div>

      <!-- 分组列表 -->
      <div
        v-if="filteredGroups.length"
        :class="
          filteredGroups.length === 1
            ? 'grid grid-cols-1'
            : 'columns-1 gap-3 sm:columns-2'
        "
      >
        <section
          v-for="group in filteredGroups"
          :key="group.id"
          class="break-inside-avoid overflow-hidden rounded-xl border border-slate-200/70 bg-white/75 shadow-[0_1px_2px_rgba(15,23,42,0.03)]"
          :class="filteredGroups.length === 1 ? '' : 'mb-3'"
        >
          <header
            class="flex items-center gap-2 border-b border-slate-100 bg-gradient-to-r from-slate-50/90 to-white/40 px-3 py-2"
          >
            <span class="grid h-6 w-6 shrink-0 place-items-center rounded-lg bg-kiwi-50 text-kiwi-600">
              <KiwiIcon :name="group.icon" :size="13" />
            </span>
            <h3 class="text-[12px] font-semibold tracking-wide text-slate-700">{{ group.title }}</h3>
            <span class="ml-auto rounded-full bg-white/80 px-1.5 py-0.5 text-[9.5px] tabular-nums text-slate-400">
              {{ group.items.length }}
            </span>
          </header>
          <dl
            class="px-3 py-1"
            :class="singleGroupWide ? 'grid grid-cols-1 gap-x-6 sm:grid-cols-2' : ''"
          >
            <div
              v-for="item in group.items"
              :key="`${group.id}-${item.keys}-${item.label}`"
              class="-mx-1.5 flex items-start justify-between gap-3 rounded-md px-1.5 py-1.5 transition-colors hover:bg-kiwi-50/50"
            >
              <dt class="min-w-0 text-[11.5px] leading-snug text-slate-600">
                {{ item.label }}
                <span v-if="item.hint" class="mt-0.5 block text-[10px] leading-snug text-slate-400">
                  {{ item.hint }}
                </span>
              </dt>
              <dd class="flex shrink-0 flex-wrap items-center justify-end gap-1 pt-px">
                <template v-for="(part, index) in keyParts(item.keys)" :key="`${part}-${index}`">
                  <span v-if="index" class="text-[9px] font-medium text-slate-300">+</span>
                  <kbd
                    class="inline-flex min-h-[20px] items-center rounded-[5px] border border-slate-200 bg-gradient-to-b from-white to-slate-50 px-1.5 font-mono text-[10px] leading-4 text-slate-600 shadow-[0_1px_0_rgba(15,23,42,0.06)]"
                  >{{ part }}</kbd>
                </template>
              </dd>
            </div>
          </dl>
        </section>
      </div>

      <!-- 空态 -->
      <div
        v-else
        class="grid place-items-center rounded-xl border border-dashed border-slate-200 bg-white/50 px-4 py-10"
      >
        <span class="grid h-10 w-10 place-items-center rounded-full bg-slate-100 text-slate-300">
          <KiwiIcon name="search" :size="20" />
        </span>
        <p class="mt-2.5 text-[12px] font-medium text-slate-500">没有匹配的快捷键</p>
        <p class="mt-1 text-[11px] text-slate-400">试试「保存」「画布」或「Ctrl + K」</p>
      </div>

      <!-- 底部提示 -->
      <p
        class="flex items-center justify-center gap-1.5 border-t border-slate-100 pt-3 text-[10.5px] text-slate-400"
      >
        随时按
        <kbd
          class="inline-flex min-h-[20px] items-center rounded-[5px] border border-slate-200 bg-gradient-to-b from-white to-slate-50 px-1.5 font-mono text-[10px] text-slate-600 shadow-[0_1px_0_rgba(15,23,42,0.06)]"
        >?</kbd>
        打开本面板
        <span class="mx-1 text-slate-200">·</span>
        按
        <kbd
          class="inline-flex min-h-[20px] items-center rounded-[5px] border border-slate-200 bg-gradient-to-b from-white to-slate-50 px-1.5 font-mono text-[10px] text-slate-600 shadow-[0_1px_0_rgba(15,23,42,0.06)]"
        >Esc</kbd>
        关闭
      </p>
    </div>
  </KiwiModal>
</template>

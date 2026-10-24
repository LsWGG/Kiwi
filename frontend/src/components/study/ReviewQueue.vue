<script setup lang="ts">
// ReviewQueue：今日到期复习队列（间隔复习调度）。
import { computed, onMounted, ref } from 'vue'
import { useStudyStore, type ReviewItem } from '@/stores/study'
import KiwiIcon from '@/components/ui/KiwiIcon.vue'
import KiwiEmpty from '@/components/ui/KiwiEmpty.vue'
import KiwiDropdown from '@/components/ui/KiwiDropdown.vue'
import { toast } from '@/components/ui/toast'

const emit = defineEmits<{ (e: 'start', mode: 'drill' | 'review'): void }>()

const study = useStudyStore()

const hasDue = computed(() => study.dueReviews.length > 0)

// 按知识域分组，避免到期列表在知识点多时失去结构
const groups = computed(() => {
  const map = new Map<string, ReviewItem[]>()
  for (const item of study.dueReviews) {
    const key = (item.domain || '').trim() || '未分类'
    if (!map.has(key)) map.set(key, [])
    map.get(key)!.push(item)
  }
  return [...map.entries()]
    .map(([domain, items]) => ({ domain, items }))
    .sort((a, b) => b.items.length - a.items.length || a.domain.localeCompare(b.domain))
})

function dueLabel(dueAt: string) {
  const diff = Date.now() - new Date(dueAt).getTime()
  const days = Math.floor(diff / 86400000)
  if (days >= 1) return `逾期 ${days} 天`
  return '今日到期'
}

function nextDueLabel() {
  if (!study.nextDueAt) return ''
  const d = new Date(study.nextDueAt)
  return d.toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function pct(v: number) {
  return Math.round(v * 100)
}

const exporting = ref(false)
const importing = ref(false)
const fileInput = ref<HTMLInputElement | null>(null)

const EXPORT_GROUPS = [
  { value: 'none' as const, label: '导出为单牌组' },
  { value: 'type' as const, label: '按题型拆分子牌组' },
  { value: 'topic' as const, label: '按知识点拆分子牌组' },
]

function pickAnkiFile() {
  if (!importing.value) fileInput.value?.click()
}

async function onAnkiFile(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return
  importing.value = true
  try {
    const result = await study.importAnki(file)
    if (result.imported) {
      toast.success(
        `已导入 ${result.imported} 道题${result.skipped ? `，跳过 ${result.skipped} 道重复题` : ''}`,
      )
    } else {
      toast.info(`没有新题目，${result.skipped} 道题已在题库中`)
    }
  } catch (e: any) {
    toast.error(e.message || '导入 Anki 牌组失败')
  } finally {
    importing.value = false
  }
}

async function exportAnki(groupBy: 'none' | 'type' | 'topic' = 'none') {
  if (exporting.value) return
  exporting.value = true
  try {
    const { blob, filename, count } = await study.exportAnki(groupBy)
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = filename
    document.body.appendChild(anchor)
    anchor.click()
    anchor.remove()
    URL.revokeObjectURL(url)
    toast.success(`已导出 ${count || ''} 道题到 Anki 牌组`)
  } catch (e: any) {
    toast.error(e.message || '导出 Anki 牌组失败')
  } finally {
    exporting.value = false
  }
}

onMounted(() => {
  study.loadDueReviews()
})
</script>

<template>
  <div class="space-y-4 animate-fade-up">
    <div class="flex items-center justify-between">
      <div class="flex items-center gap-2">
        <span
          class="w-9 h-9 rounded-xl bg-gradient-to-br from-kiwi-400 to-kiwi-600 text-white grid place-items-center shadow-sm"
        >
          <KiwiIcon name="refresh" :size="16" />
        </span>
        <div>
          <h3 class="font-semibold text-slate-800">今日复习</h3>
          <p class="text-xs text-slate-400">
            {{ study.dueReviews.length }} 个知识点到期 · 按间隔复习调度
          </p>
        </div>
      </div>
      <div class="flex items-center gap-1">
        <KiwiDropdown align="right" width="w-44">
          <template #trigger="{ open }">
            <button
              class="kiwi-btn-ghost !px-2 !py-1 text-[11px] disabled:opacity-50"
              :class="open ? 'text-kiwi-700 bg-kiwi-50' : ''"
              title="导出 Anki 牌组（含题干、答案与解析）"
              :disabled="exporting"
            >
              <KiwiIcon name="fileExport" :size="13" :spin="exporting" />
              Anki
              <KiwiIcon name="chevron" :size="11" />
            </button>
          </template>
          <template #default="{ close }">
            <button
              v-for="option in EXPORT_GROUPS"
              :key="option.value"
              type="button"
              class="w-full flex items-center gap-2 rounded-lg px-2.5 py-1.5 text-left text-[12px] text-slate-600 hover:bg-kiwi-50 disabled:opacity-40"
              :disabled="exporting"
              @click="close(); exportAnki(option.value)"
            >
              <KiwiIcon name="fileExport" :size="12" class="text-slate-400" />
              {{ option.label }}
            </button>
            <div class="my-1 border-t border-slate-100" />
            <button
              type="button"
              class="w-full flex items-center gap-2 rounded-lg px-2.5 py-1.5 text-left text-[12px] text-slate-600 hover:bg-kiwi-50 disabled:opacity-40"
              :disabled="importing"
              @click="close(); pickAnkiFile()"
            >
              <KiwiIcon :name="importing ? 'loader' : 'fileImport'" :size="12" :spin="importing" class="text-slate-400" />
              {{ importing ? '导入中…' : '导入 Anki 牌组…' }}
            </button>
          </template>
        </KiwiDropdown>
        <input
          ref="fileInput"
          type="file"
          accept=".apkg,.colpkg"
          class="hidden"
          @change="onAnkiFile"
        />
        <button class="kiwi-btn-ghost !p-1.5" title="刷新" @click="study.loadDueReviews()">
          <KiwiIcon name="refresh" :size="15" />
        </button>
      </div>
    </div>

    <!-- 加载中 -->
    <div v-if="study.dueLoading && !study.dueReviews.length" class="space-y-2.5">
      <div v-for="i in 3" :key="i" class="kiwi-card p-4 flex items-center gap-3">
        <div class="w-9 h-9 rounded-xl bg-slate-200/60 animate-pulse" />
        <div class="flex-1 space-y-2">
          <div class="h-3 rounded bg-slate-200/60 animate-pulse w-1/2" />
          <div class="h-2 rounded bg-slate-200/40 animate-pulse w-1/3" />
        </div>
      </div>
    </div>

    <!-- 空态 -->
    <KiwiEmpty
      v-else-if="!hasDue"
      icon="check"
      title="今日复习已完成"
      :desc="
        study.nextDueAt
          ? `下一次到期：${nextDueLabel()}`
          : '完成训练后，答过的知识点会自动进入复习调度'
      "
    >
      <button class="kiwi-btn-secondary" @click="emit('start', 'drill')">
        <KiwiIcon name="target" :size="14" />
        去训练新知识点
      </button>
    </KiwiEmpty>

    <!-- 到期列表 -->
    <template v-else>
      <div class="flex justify-end">
        <button class="kiwi-btn-primary" @click="emit('start', 'review')">
          <KiwiIcon name="arrowRight" :size="15" />
          开始复习（{{ study.dueReviews.length }}）
        </button>
      </div>

      <div class="space-y-2.5">
        <template v-for="group in groups" :key="group.domain">
          <div class="flex items-center gap-2 pt-1">
            <span class="text-[10px] font-medium text-slate-500">{{ group.domain }}</span>
            <span class="text-[10px] text-slate-300">{{ group.items.length }}</span>
            <span class="flex-1 h-px bg-slate-200/60" />
          </div>
          <div
          v-for="item in group.items"
          :key="item.slug"
          class="kiwi-card p-4 flex items-center gap-3"
        >
          <span
            class="w-9 h-9 shrink-0 rounded-xl bg-gradient-to-br from-amber-100 to-white border border-amber-100 text-amber-600 grid place-items-center"
          >
            <KiwiIcon name="bookOpen" :size="15" />
          </span>
          <div class="min-w-0 flex-1">
            <div class="flex items-center gap-2">
              <p class="text-sm font-medium text-slate-700 truncate">{{ item.title }}</p>
              <span class="text-[10px] px-1.5 py-0.5 rounded bg-amber-100/80 text-amber-700 shrink-0">
                {{ dueLabel(item.due_at) }}
              </span>
              <span
                v-if="item.content_updated"
                class="text-[10px] px-1.5 py-0.5 rounded bg-kiwi-100/80 text-kiwi-700 shrink-0"
                title="知识点内容已更新，建议重新学习"
              >
                内容已更新
              </span>
            </div>
            <div class="flex items-center gap-2 mt-1.5">
              <div class="flex-1 h-1.5 rounded-full bg-slate-200/50 overflow-hidden">
                <div
                  class="h-full rounded-full bg-kiwi-500 transition-all duration-500"
                  :style="{ width: `${pct(item.mastery)}%` }"
                />
              </div>
              <span class="text-[10px] text-slate-400 tabular-nums shrink-0">
                掌握 {{ pct(item.mastery) }}%
              </span>
              <span class="text-[10px] text-slate-300 shrink-0">
                · 间隔 {{ item.interval_days }} 天 · 连对 {{ item.repetitions }}
              </span>
            </div>
          </div>
          </div>
        </template>
      </div>
    </template>
  </div>
</template>
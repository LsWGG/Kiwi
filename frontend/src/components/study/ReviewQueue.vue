<script setup lang="ts">
// ReviewQueue：今日到期复习队列（间隔复习调度）。
import { computed, onMounted } from 'vue'
import { useStudyStore, type ReviewItem } from '@/stores/study'
import KiwiIcon from '@/components/ui/KiwiIcon.vue'
import KiwiEmpty from '@/components/ui/KiwiEmpty.vue'

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
      <button class="kiwi-btn-ghost !p-1.5" title="刷新" @click="study.loadDueReviews()">
        <KiwiIcon name="refresh" :size="15" />
      </button>
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
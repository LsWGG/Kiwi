<script setup lang="ts">
import { computed } from 'vue'
import { toasts, dismiss, type ToastItem } from './toast'
import KiwiIcon from './KiwiIcon.vue'

const badge = (t: string) =>
  t === 'success' ? 'check' : t === 'error' ? 'alert' : t === 'progress' ? 'upload' : 'sparkle'
const badgeClass = (t: string) =>
  t === 'success'
    ? 'text-emerald-600 bg-emerald-50'
    : t === 'error'
      ? 'text-rose-600 bg-rose-50'
      : 'text-kiwi-600 bg-kiwi-50'

const percent = (t: ToastItem) => Math.round((t.progress ?? 0) * 100)
// 上传进度固定在顶部居中：GB 级文件耗时长，右下角消息容易被忽略。
const progressToasts = computed(() => toasts.filter((t) => t.type === 'progress'))
const noticeToasts = computed(() => toasts.filter((t) => t.type !== 'progress'))
</script>

<template>
  <Teleport to="body">
    <div
      class="fixed top-20 left-1/2 z-[120] flex w-[min(92vw,420px)] -translate-x-1/2 flex-col items-stretch gap-2 pointer-events-none"
    >
      <TransitionGroup
        enter-active-class="transition-all duration-300 ease-spring"
        enter-from-class="opacity-0 -translate-y-3 scale-95"
        leave-active-class="transition duration-200"
        leave-to-class="opacity-0 -translate-y-3"
      >
        <div
          v-for="t in progressToasts"
          :key="t.id"
          class="pointer-events-auto flex flex-col rounded-xl border border-slate-200/80 bg-white/95 px-4 py-3 shadow-lifted backdrop-blur-sm"
          role="status"
          aria-live="polite"
        >
          <div class="flex items-center gap-2.5">
            <span class="w-6 h-6 rounded-lg grid place-items-center shrink-0" :class="badgeClass(t.type)">
              <KiwiIcon :name="badge(t.type)" :size="14" />
            </span>
            <span class="min-w-0 flex-1 truncate text-sm text-slate-700">{{ t.message }}</span>
            <span class="ml-auto pl-2 text-xs tabular-nums text-slate-600">{{ percent(t) }}%</span>
            <button
              v-if="t.onCancel"
              type="button"
              class="shrink-0 rounded-md bg-slate-100 px-2 py-0.5 text-[11px] font-medium text-slate-500 transition hover:bg-slate-200 hover:text-slate-700"
              @click.stop="t.onCancel()"
            >
              取消
            </button>
          </div>
          <div class="mt-2 h-1.5 rounded-full bg-slate-200/80 overflow-hidden">
            <div
              class="h-full rounded-full bg-kiwi-500 transition-[width] duration-200"
              :class="percent(t) === 0 ? 'animate-pulse' : ''"
              :style="{ width: `${percent(t) === 0 ? 12 : percent(t)}%` }"
            />
          </div>
          <p v-if="percent(t) === 0" class="mt-1.5 text-[11px] text-slate-500">
            正在读取文件并建立连接…
          </p>
        </div>
      </TransitionGroup>
    </div>

    <div class="fixed bottom-6 right-6 z-[100] flex flex-col gap-2 items-end pointer-events-none">
      <TransitionGroup
        enter-active-class="transition-all duration-300 ease-spring"
        enter-from-class="opacity-0 translate-y-3 scale-95"
        leave-active-class="transition duration-200"
        leave-to-class="opacity-0 translate-x-4"
      >
        <div
          v-for="t in noticeToasts"
          :key="t.id"
          class="pointer-events-auto flex items-center gap-2.5 rounded-xl px-4 py-2.5 glass-strong shadow-lifted min-w-[220px] max-w-sm"
          @click="dismiss(t.id)"
        >
          <span class="w-6 h-6 rounded-lg grid place-items-center shrink-0" :class="badgeClass(t.type)">
            <KiwiIcon :name="badge(t.type)" :size="14" />
          </span>
          <span class="text-sm text-slate-700">{{ t.message }}</span>
        </div>
      </TransitionGroup>
    </div>
  </Teleport>
</template>

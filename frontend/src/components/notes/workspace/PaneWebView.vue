<script setup lang="ts">
/**
 * 分栏中的网页窗口：与正文网页嵌入使用相同的 sandbox 策略。
 *
 * 部分站点（如腾讯云）依赖第三方 Cookie 做访问校验/登录：在跨站 iframe 中
 * Cookie 被浏览器拦截后，校验页会无限刷新，表现为一直转圈。这里统计 iframe
 * 的加载次数，短时间内连续多次即判定为校验循环，给出在浏览器打开的出口。
 */
import { ref } from 'vue'
import KiwiIcon from '@/components/ui/KiwiIcon.vue'
import { IS_DESKTOP } from '@/desktop/env'

const props = defineProps<{
  url: string
  title: string
  site?: string
}>()

const frameKey = ref(0)
const loadCount = ref(0)
const firstLoadAt = ref(0)
/** 判定为第三方 Cookie / 反爬校验循环后不再渲染 iframe，避免持续刷新。 */
const loopBlocked = ref(false)

const SANDBOX =
  'allow-scripts allow-same-origin allow-popups allow-popups-to-escape-sandbox ' +
  'allow-forms allow-modals allow-downloads allow-storage-access-by-user-activation'

function onLoad() {
  if (loopBlocked.value) return
  const now = Date.now()
  if (!firstLoadAt.value) firstLoadAt.value = now
  loadCount.value += 1
  // 正常站点最多一次重定向；10 秒内加载 3 次以上视为校验循环。
  if (loadCount.value >= 3 && now - firstLoadAt.value < 10_000) {
    loopBlocked.value = true
  }
}

function reload() {
  frameKey.value += 1
  loadCount.value = 0
  firstLoadAt.value = 0
  loopBlocked.value = false
}

function openExternal() {
  window.open(props.url, '_blank', 'noopener,noreferrer')
}
</script>

<template>
  <div class="h-full min-h-0 flex flex-col bg-white">
    <div class="shrink-0 flex items-center gap-1.5 border-b border-slate-200/70 bg-slate-50/70 px-2 py-1">
      <span class="min-w-0 flex-1 truncate text-[10.5px] text-slate-400" :title="url">
        {{ url }}
      </span>
      <button
        type="button"
        class="flex h-6 items-center gap-1 rounded px-1.5 text-[10.5px] text-slate-500 transition-colors hover:bg-white hover:text-kiwi-600"
        title="在浏览器新窗口打开（登录请使用此方式）"
        @click="openExternal"
      >
        <KiwiIcon name="external" :size="11" />
        浏览器打开
      </button>
      <button
        type="button"
        class="grid h-6 w-6 place-items-center rounded text-slate-400 transition-colors hover:bg-white hover:text-kiwi-600"
        title="刷新"
        @click="reload"
      >
        <KiwiIcon name="refresh" :size="12" />
      </button>
    </div>

    <div v-if="IS_DESKTOP" class="flex-1 grid place-items-center px-6 text-center">
      <div>
        <KiwiIcon name="globe" :size="28" class="mx-auto text-slate-300" />
        <p class="mt-3 text-[12.5px] font-medium text-slate-500">外部网页已在桌面版禁用</p>
        <p class="mt-1 max-w-full break-all text-[10.5px] text-slate-400">{{ url }}</p>
      </div>
    </div>

    <div v-else-if="loopBlocked" class="flex-1 grid place-items-center px-6 text-center">
      <div class="max-w-[340px]">
        <KiwiIcon name="globe" :size="28" class="mx-auto text-slate-300" />
        <p class="mt-3 text-[12.5px] font-medium text-slate-600">网页在分栏内反复刷新</p>
        <p class="mt-1.5 text-[11px] leading-relaxed text-slate-400">
          该站点需要第三方 Cookie 做访问校验或登录，浏览器在分栏内会拦截 Cookie，导致校验无法完成。
          请在浏览器新窗口打开后登录使用。
        </p>
        <p class="mt-2 max-w-full break-all text-[10px] text-slate-300">{{ url }}</p>
        <div class="mt-3 flex items-center justify-center gap-2">
          <button
            type="button"
            class="rounded-lg bg-kiwi-600 px-3 py-1.5 text-[11.5px] font-medium text-white transition-colors hover:bg-kiwi-700"
            @click="openExternal"
          >
            在浏览器打开
          </button>
          <button
            type="button"
            class="rounded-lg border border-slate-200 px-3 py-1.5 text-[11.5px] text-slate-500 transition-colors hover:bg-slate-50"
            @click="reload"
          >
            仍然重试
          </button>
        </div>
      </div>
    </div>

    <iframe
      v-else
      :key="frameKey"
      :src="url"
      :title="title || site || url"
      class="flex-1 min-h-0 w-full border-0"
      referrerpolicy="no-referrer"
      :sandbox="SANDBOX"
      @load="onLoad"
    />
  </div>
</template>

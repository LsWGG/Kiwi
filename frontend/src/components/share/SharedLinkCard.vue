<script setup lang="ts">
/** 公开分享页的链接笔记书签卡：站点、标题、地址与摘要。 */
import { computed, ref, watch } from 'vue'
import KiwiIcon from '@/components/ui/KiwiIcon.vue'

interface LinkPayload {
  url?: string
  final_url?: string
  site?: string
  favicon?: string
  excerpt?: string
  fetch_status?: string
  fetch_error?: string | null
}

const props = defineProps<{ payload?: LinkPayload | null; title?: string | null }>()

const faviconBroken = ref(false)
const openUrl = computed(() => String(props.payload?.final_url || props.payload?.url || ''))
const failed = computed(() => props.payload?.fetch_status === 'failed')
const excerpt = computed(() => String(props.payload?.excerpt || '').trim())
const site = computed(() => {
  const saved = String(props.payload?.site || '').trim()
  if (saved) return saved
  try {
    return new URL(openUrl.value).host
  } catch {
    return ''
  }
})
const faviconSrc = computed(() => {
  const saved = String(props.payload?.favicon || '').trim()
  if (/^(https?:\/\/|\/)/i.test(saved)) return saved
  try {
    const parsed = new URL(openUrl.value)
    if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') return ''
    return `${parsed.origin}/favicon.ico`
  } catch {
    return ''
  }
})
watch(faviconSrc, () => {
  faviconBroken.value = false
})
</script>

<template>
  <div class="relative mb-7 overflow-hidden rounded-2xl border border-slate-200/70 bg-gradient-to-br from-white/90 to-kiwi-50/60 p-4 shadow-soft">
    <div class="flex items-start gap-3">
      <div class="grid h-9 w-9 shrink-0 place-items-center overflow-hidden rounded-xl border border-slate-200/70 bg-white">
        <img
          v-if="faviconSrc && !faviconBroken"
          :src="faviconSrc"
          class="h-5 w-5"
          alt=""
          referrerpolicy="no-referrer"
          @error="faviconBroken = true"
        />
        <KiwiIcon v-else name="link2" :size="15" class="text-sky-500" />
      </div>
      <div class="min-w-0 flex-1">
        <div class="flex items-center gap-2">
          <span class="truncate text-[11px] font-medium text-slate-500">
            {{ site || '外部链接' }}
          </span>
          <span
            v-if="failed"
            class="shrink-0 rounded-md border border-amber-200 bg-amber-50 px-1.5 py-0.5 text-[9.5px] text-amber-600"
          >
            仅书签
          </span>
        </div>
        <a
          v-if="openUrl"
          :href="openUrl"
          target="_blank"
          rel="noopener noreferrer"
          class="mt-0.5 inline-flex items-center gap-1 text-[13px] font-medium text-slate-700 transition-colors hover:text-kiwi-700"
        >
          <span class="truncate">{{ title || openUrl }}</span>
          <KiwiIcon name="external" :size="11" class="shrink-0 text-slate-400" />
        </a>
        <p v-if="openUrl" class="mt-0.5 truncate text-[10.5px] text-slate-400">{{ openUrl }}</p>
      </div>
    </div>
    <p v-if="excerpt" class="mt-3 text-[12px] leading-relaxed text-slate-500 line-clamp-3">
      {{ excerpt }}
    </p>
    <p
      v-if="failed"
      class="mt-2 flex items-start gap-1.5 text-[11px] leading-relaxed text-amber-600"
    >
      <KiwiIcon name="alert" :size="12" class="mt-0.5 shrink-0" />
      {{ payload?.fetch_error || '网页抓取失败，仅展示书签信息。' }}
    </p>
  </div>
</template>

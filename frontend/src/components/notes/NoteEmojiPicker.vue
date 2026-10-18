<script setup lang="ts">
/**
 * 笔记表情选择面板（右键菜单 / 标题按钮共用）。
 * 与右键菜单相同的定位方式：外层视口坐标、内层 --ui-scale，避免 4K 下漂移。
 */
import { computed, nextTick, ref, watch } from 'vue'
import KiwiIcon from '@/components/ui/KiwiIcon.vue'
import { NOTE_EMOJIS } from './emojis'

const props = withDefaults(
  defineProps<{
    open: boolean
    x: number
    y: number
    current?: string
  }>(),
  { current: '' },
)

const emit = defineEmits<{
  (e: 'select', emoji: string): void
  (e: 'close'): void
}>()

const panelEl = ref<HTMLElement | null>(null)
const pos = ref({ left: '0px', top: '0px' })
const custom = ref('')

const currentEmoji = computed(() => (props.current || '').trim())

function applyCustom() {
  const value = custom.value.trim()
  if (!value) return
  custom.value = ''
  emit('select', value)
}

function place() {
  if (!props.open) return
  void nextTick(() => {
    const rect = panelEl.value?.getBoundingClientRect()
    const width = rect?.width ?? 288
    const height = rect?.height ?? 260
    pos.value = {
      left: `${Math.max(8, Math.min(props.x, window.innerWidth - width - 8))}px`,
      top: `${Math.max(8, Math.min(props.y, window.innerHeight - height - 8))}px`,
    }
  })
}

watch(() => [props.open, props.x, props.y], place, { immediate: true })
watch(
  () => props.open,
  (open) => {
    if (open) custom.value = ''
  },
)
</script>

<template>
  <Teleport to="html">
    <div
      v-if="open"
      class="fixed inset-0 z-[90]"
      @mousedown="emit('close')"
      @contextmenu.prevent="emit('close')"
    >
      <div class="absolute" :style="pos">
        <div
          ref="panelEl"
          class="w-72 rounded-xl border border-slate-200/70 bg-white/95 backdrop-blur-xl shadow-lifted p-2 animate-scale-in"
          :style="{ zoom: 'var(--ui-scale)' }"
          @mousedown.stop
        >
          <div class="px-1 pb-1.5 text-[10.5px] text-slate-400">选择文档表情</div>
          <div class="grid grid-cols-8 gap-0.5 max-h-56 overflow-y-auto pr-0.5">
            <button
              v-for="emoji in NOTE_EMOJIS"
              :key="emoji"
              type="button"
              class="h-8 grid place-items-center rounded-lg text-[17px] leading-none transition-colors hover:bg-kiwi-50"
              :class="emoji === currentEmoji ? 'bg-kiwi-100/80' : ''"
              @click="emit('select', emoji)"
            >
              {{ emoji }}
            </button>
          </div>
          <div class="mt-1.5 flex items-center gap-1.5 border-t border-slate-100 pt-1.5">
            <input
              v-model="custom"
              class="min-w-0 flex-1 rounded-lg border border-slate-200 bg-white px-2 py-1 text-[11.5px] text-slate-600 outline-none focus:border-kiwi-300 focus:ring-2 focus:ring-kiwi-100"
              placeholder="自定义表情 / 文字，如 🦄"
              maxlength="8"
              @keydown.enter.prevent="applyCustom"
            />
            <button
              type="button"
              class="shrink-0 rounded-lg bg-kiwi-500 px-2 py-1 text-[11px] text-white transition-colors hover:bg-kiwi-600 disabled:opacity-50"
              :disabled="!custom.trim()"
              @click="applyCustom"
            >
              使用
            </button>
          </div>
          <button
            v-if="currentEmoji"
            type="button"
            class="mt-1 w-full flex items-center gap-1.5 rounded-lg px-2 py-1.5 text-[11.5px] text-slate-500 transition-colors hover:bg-slate-100"
            @click="emit('select', '')"
          >
            <KiwiIcon name="close" :size="12" />
            恢复默认图标
          </button>
        </div>
      </div>
    </div>
  </Teleport>
</template>

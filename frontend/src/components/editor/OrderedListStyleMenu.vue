<script setup lang="ts">
/** 文档级多级有序列表编号样式选择（参考 WPS 多级编号）。 */
import { computed } from 'vue'
import KiwiDropdown from '@/components/ui/KiwiDropdown.vue'
import KiwiIcon from '@/components/ui/KiwiIcon.vue'
import {
  DEFAULT_ORDERED_LIST_STYLE,
  ORDERED_LIST_STYLE_PRESETS,
  resolveOrderedListStyle,
  type OrderedListStyleKey,
} from './orderedListStyles'

const props = withDefaults(
  defineProps<{
    value?: string | null
    disabled?: boolean
    /** button：独立图标按钮；chevron：仅下拉箭头，供工具栏合并控件使用 */
    variant?: 'button' | 'chevron'
  }>(),
  { value: null, disabled: false, variant: 'button' },
)

const emit = defineEmits<{ (e: 'change', key: OrderedListStyleKey): void }>()

const current = computed(() => resolveOrderedListStyle(props.value))
const customized = computed(() => current.value !== DEFAULT_ORDERED_LIST_STYLE)
</script>

<template>
  <KiwiDropdown
    width="w-60"
    align="right"
    panel-class="!rounded-xl !border-slate-200/90 !bg-white/98 !p-1.5 !shadow-xl !backdrop-blur"
  >
    <template #trigger>
      <!-- 合并控件：箭头只负责展开「多级编号样式」，列表开关由父级按钮承担 -->
      <button
        v-if="variant === 'chevron'"
        type="button"
        class="grid h-7 w-[18px] shrink-0 place-items-center rounded-r-lg text-slate-400 transition-colors hover:text-kiwi-700 disabled:cursor-not-allowed disabled:opacity-50"
        :disabled="disabled"
        title="多级编号样式"
        aria-label="多级编号样式"
        aria-haspopup="menu"
      >
        <KiwiIcon name="chevron" :size="9" />
      </button>
      <button
        v-else
        type="button"
        class="inline-flex h-7 shrink-0 items-center gap-0.5 rounded-lg px-1 text-slate-500 transition-colors hover:bg-kiwi-50 hover:text-kiwi-700 disabled:cursor-not-allowed disabled:opacity-50"
        :class="customized ? 'bg-kiwi-50 text-kiwi-700' : ''"
        :disabled="disabled"
        title="多级有序列表编号样式"
        aria-label="多级有序列表编号样式"
        aria-haspopup="menu"
      >
        <KiwiIcon name="listOrdered" :size="14" />
        <KiwiIcon name="chevron" :size="8" class="text-slate-400" />
      </button>
    </template>
    <template #default="{ close }">
      <p class="px-2 pb-1 pt-1 text-[10px] font-medium uppercase tracking-[0.12em] text-slate-400">
        多级编号样式
      </p>
      <button
        v-for="preset in ORDERED_LIST_STYLE_PRESETS"
        :key="preset.key"
        type="button"
        role="menuitemradio"
        :aria-checked="current === preset.key"
        class="flex w-full items-center gap-2.5 rounded-lg px-2 py-1.5 text-left transition-colors hover:bg-kiwi-50"
        :class="current === preset.key ? 'bg-kiwi-50' : ''"
        @click="emit('change', preset.key); close()"
      >
        <span
          class="grid h-7 w-9 shrink-0 place-items-center rounded-lg text-[10px] font-medium tabular-nums"
          :class="
            current === preset.key
              ? 'bg-kiwi-100 text-kiwi-700'
              : 'bg-slate-100 text-slate-500'
          "
        >
          {{ preset.sample[0] }}
        </span>
        <span class="min-w-0">
          <span
            class="block text-[12px] font-medium"
            :class="current === preset.key ? 'text-kiwi-700' : 'text-slate-700'"
          >{{ preset.label }}</span>
          <span class="block truncate text-[10px] text-slate-400 tabular-nums">
            {{ preset.sample.join(' · ') }}
          </span>
        </span>
      </button>
    </template>
  </KiwiDropdown>
</template>

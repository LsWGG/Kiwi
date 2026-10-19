<script setup lang="ts">
/** 文档级多级有序列表编号样式选择（参考 WPS 多级编号）。 */
import { computed } from 'vue'
import KiwiDropdown from '@/components/ui/KiwiDropdown.vue'
import KiwiIcon from '@/components/ui/KiwiIcon.vue'
import {
  ORDERED_LIST_STYLE_PRESETS,
  resolveOrderedListStyle,
  type OrderedListStyleKey,
} from './orderedListStyles'

const props = withDefaults(
  defineProps<{ value?: string | null; disabled?: boolean }>(),
  { value: null, disabled: false },
)

const emit = defineEmits<{ (e: 'change', key: OrderedListStyleKey): void }>()

const current = computed(() => resolveOrderedListStyle(props.value))
</script>

<template>
  <KiwiDropdown width="w-64" align="right" panel-class="!p-1.5">
    <template #trigger>
      <button
        type="button"
        class="inline-flex shrink-0 items-center gap-1 rounded-lg px-2 py-1 text-[10.5px] text-slate-500 transition-colors hover:bg-kiwi-50 hover:text-kiwi-700 disabled:cursor-not-allowed disabled:opacity-50"
        :disabled="disabled"
        title="多级有序列表编号样式"
        aria-label="多级有序列表编号样式"
        aria-haspopup="menu"
      >
        <KiwiIcon name="listOrdered" :size="12" />
        编号
        <KiwiIcon name="chevron" :size="9" class="text-slate-400" />
      </button>
    </template>
    <template #default="{ close }">
      <p class="px-2 pb-1 pt-1 text-[10px] font-medium tracking-wide text-slate-400">
        多级编号样式
      </p>
      <button
        v-for="preset in ORDERED_LIST_STYLE_PRESETS"
        :key="preset.key"
        type="button"
        role="menuitemradio"
        :aria-checked="current === preset.key"
        class="flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left transition-colors"
        :class="
          current === preset.key
            ? 'bg-kiwi-50 text-kiwi-700'
            : 'text-slate-600 hover:bg-slate-50'
        "
        @click="emit('change', preset.key); close()"
      >
        <KiwiIcon
          v-if="current === preset.key"
          name="check"
          :size="12"
          class="shrink-0 text-kiwi-600"
        />
        <span v-else class="w-3 shrink-0" />
        <span class="min-w-0 flex-1">
          <span class="block text-[12px] leading-5">{{ preset.label }}</span>
          <span class="block truncate text-[10.5px] leading-4 text-slate-400 tabular-nums">
            {{ preset.sample.join('  ·  ') }}
          </span>
        </span>
      </button>
    </template>
  </KiwiDropdown>
</template>

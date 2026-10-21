<script setup lang="ts">
/** 编辑器模式切换：标准编辑 / DOCX（放在「阅读」按钮前）。 */
import { computed } from 'vue'
import KiwiDropdown from '@/components/ui/KiwiDropdown.vue'
import KiwiIcon from '@/components/ui/KiwiIcon.vue'
import {
  EDITOR_MODE_TABS,
  editorModeMeta,
  editorModeTabLabel,
  type EditorMode,
} from './modes'

const props = defineProps<{ mode: EditorMode }>()
const emit = defineEmits<{ (e: 'change', mode: EditorMode): void }>()

const items = computed(() =>
  EDITOR_MODE_TABS.map((id) => ({ ...editorModeMeta(id), label: editorModeTabLabel(id) })),
)
const current = computed(() => editorModeMeta(props.mode))
const currentLabel = computed(() => editorModeTabLabel(props.mode))
</script>

<template>
  <KiwiDropdown width="w-64" align="right">
    <template #trigger="{ open }">
      <button
        type="button"
        class="kiwi-btn-ghost !py-1 !px-2 !text-[11px] max-w-[170px]"
        :class="open ? 'bg-kiwi-50 text-kiwi-700' : ''"
        title="切换编辑器模式"
      >
        <KiwiIcon :name="current.icon" :size="12" class="text-kiwi-500 shrink-0" />
        <span class="truncate">{{ currentLabel }}</span>
        <KiwiIcon name="chevron" :size="10" class="shrink-0 text-slate-400" />
      </button>
    </template>
    <template #default="{ close }">
      <button
        v-for="item in items"
        :key="item.id"
        type="button"
        class="w-full flex items-start gap-2.5 rounded-lg px-2.5 py-2 text-left transition-colors hover:bg-kiwi-50/80"
        :class="item.id === mode ? 'bg-kiwi-50/70' : ''"
        @click="close(); emit('change', item.id)"
      >
        <span
          class="mt-0.5 w-7 h-7 shrink-0 grid place-items-center rounded-lg border"
          :class="
            item.id === mode
              ? 'border-kiwi-200 bg-white text-kiwi-600'
              : 'border-slate-200/70 bg-white/70 text-slate-400'
          "
        >
          <KiwiIcon :name="item.icon" :size="14" />
        </span>
        <span class="min-w-0 flex-1">
          <span class="flex items-center gap-1.5 text-[12.5px] font-medium text-slate-700">
            {{ item.label }}
            <KiwiIcon v-if="item.id === mode" name="check" :size="11" class="text-kiwi-500" />
          </span>
          <span class="block text-[10.5px] leading-snug text-slate-400">{{ item.hint }}</span>
        </span>
      </button>
    </template>
  </KiwiDropdown>
</template>

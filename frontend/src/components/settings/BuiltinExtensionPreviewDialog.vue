<script setup lang="ts">
/** 内置扩展组件只读预览：复用阅读视图渲染，确保与编辑器效果一致。 */
import { computed } from 'vue'
import KiwiIcon from '@/components/ui/KiwiIcon.vue'
import KiwiModal from '@/components/ui/KiwiModal.vue'
import MarkdownView from '@/components/editor/MarkdownView.vue'
import type { EditorExtension } from '@/stores/extensions'

const props = defineProps<{
  open: boolean
  extension: EditorExtension | null
}>()

const emit = defineEmits<{ (e: 'close'): void }>()

const content = computed(() => props.extension?.preview_markdown || '')
</script>

<template>
  <KiwiModal
    :open="open"
    :title="extension ? `预览 · ${extension.label}` : '扩展组件预览'"
    max-w="max-w-3xl"
    @close="emit('close')"
  >
    <div v-if="extension" class="space-y-4">
      <div class="flex flex-wrap items-center gap-2 text-[11px] text-slate-500">
        <span class="rounded-full bg-kiwi-50 px-2 py-0.5 text-kiwi-600">内置扩展组件</span>
        <span class="rounded-full bg-slate-100 px-2 py-0.5 font-mono">{{ extension.key }}</span>
        <span
          class="rounded-full px-2 py-0.5"
          :class="extension.enabled ? 'bg-emerald-50 text-emerald-600' : 'bg-slate-100 text-slate-400'"
        >
          {{ extension.enabled ? '已启用' : '已停用' }}
        </span>
        <span class="text-slate-400">{{ extension.hint }}</span>
      </div>

      <div class="overflow-hidden rounded-2xl border border-slate-200/80 bg-white shadow-sm">
        <div
          class="flex flex-wrap items-center justify-between gap-2 border-b border-slate-100 bg-slate-50/70 px-4 py-2 text-[10.5px] text-slate-400"
        >
          <span class="inline-flex items-center gap-1.5">
            <KiwiIcon name="eye" :size="12" /> 交互预览
          </span>
          <span>与编辑器使用同一套解析规则；操作不会写回笔记</span>
        </div>
        <div class="max-h-[56vh] overflow-y-auto overscroll-contain px-6 py-5">
          <MarkdownView v-if="content" :content="content" interactive />
          <p v-else class="py-8 text-center text-[11.5px] text-slate-400">
            该组件暂未提供预览样例。
          </p>
        </div>
      </div>

      <div class="flex flex-wrap items-center justify-between gap-2">
        <p class="text-[10.5px] leading-relaxed text-slate-400">
          预览中的勾选等操作只在弹窗内生效；在编辑器「+ → 扩展组件」或斜杠菜单中可插入真实组件。
        </p>
        <button class="kiwi-btn-secondary" @click="emit('close')">关闭</button>
      </div>
    </div>
  </KiwiModal>
</template>

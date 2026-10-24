<script setup lang="ts">
/**
 * 同知识库内移动：把笔记 / 分组移动到指定分组。
 * 移动分组时会隐藏自身及其后代，避免把父分组移进子分组形成环。
 */
import { computed, ref, watch } from 'vue'
import KiwiModal from '@/components/ui/KiwiModal.vue'
import KiwiIcon from '@/components/ui/KiwiIcon.vue'
import type { NoteFolder } from '@/stores/notes'

const props = withDefaults(
  defineProps<{
    open: boolean
    title: string
    folders: NoteFolder[]
    currentFolderId?: string | null
    /** 不可作为目标的节点（移动分组时 = 自身 + 后代）。 */
    excludeIds?: string[]
  }>(),
  { currentFolderId: null, excludeIds: () => [] },
)

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'move', folderId: string | null): void
}>()

const target = ref<string | null>(null)
const submitting = ref(false)

const blocked = computed(() => new Set(props.excludeIds))

const flatFolders = computed(() => {
  const out: Array<{ id: string; name: string; depth: number }> = []
  const walk = (parentId: string | null, depth: number) => {
    const siblings = props.folders
      .filter((folder) => folder.parent_id === parentId)
      .sort((a, b) => a.sort_order - b.sort_order)
    for (const folder of siblings) {
      if (blocked.value.has(folder.id)) continue
      out.push({ id: folder.id, name: folder.name, depth })
      walk(folder.id, depth + 1)
    }
  }
  walk(null, 0)
  return out
})

/** 分组被收起时父节点可能不在列表里，仍按层级缩进展示。 */
watch(
  () => props.open,
  (open) => {
    if (!open) return
    submitting.value = false
    target.value = props.currentFolderId ?? null
  },
)

function submit() {
  if (submitting.value) return
  submitting.value = true
  emit('move', target.value)
}
</script>

<template>
  <KiwiModal :open="open" :title="title" max-w="max-w-md" @close="emit('close')">
    <div class="space-y-3.5">
      <p class="text-[12px] leading-relaxed text-slate-500">
        选择一个目标分组；子笔记会脱离原父笔记，分组会连同其内容一起移动。
      </p>

      <div class="max-h-72 overflow-y-auto rounded-xl border border-slate-200/80 bg-white/70 p-1">
        <button
          type="button"
          class="flex w-full items-center gap-2 rounded-lg px-2.5 py-2 text-left text-[12.5px] transition-colors"
          :class="target === null ? 'bg-kiwi-50 text-kiwi-700' : 'text-slate-600 hover:bg-slate-50'"
          @click="target = null"
        >
          <KiwiIcon name="folderOpen" :size="14" class="text-amber-400" />
          <span class="flex-1">根目录</span>
          <KiwiIcon v-if="target === null" name="check" :size="13" class="text-kiwi-500" />
        </button>

        <button
          v-for="folder in flatFolders"
          :key="folder.id"
          type="button"
          class="flex w-full items-center gap-2 rounded-lg px-2.5 py-2 text-left text-[12.5px] transition-colors"
          :class="target === folder.id ? 'bg-kiwi-50 text-kiwi-700' : 'text-slate-600 hover:bg-slate-50'"
          :style="{ paddingLeft: `${10 + folder.depth * 14}px` }"
          @click="target = folder.id"
        >
          <KiwiIcon name="folder" :size="14" class="text-amber-400" />
          <span class="flex-1 truncate">{{ folder.name }}</span>
          <KiwiIcon v-if="target === folder.id" name="check" :size="13" class="text-kiwi-500" />
        </button>

        <p v-if="!flatFolders.length" class="px-3 py-4 text-center text-[11.5px] text-slate-400">
          当前知识库还没有其他分组，可以先移动到根目录。
        </p>
      </div>

      <div class="flex justify-end gap-2 pt-0.5">
        <button class="kiwi-btn-secondary" @click="emit('close')">取消</button>
        <button class="kiwi-btn-primary" :disabled="submitting" @click="submit">
          <KiwiIcon name="folder" :size="13" />
          移动到此处
        </button>
      </div>
    </div>
  </KiwiModal>
</template>

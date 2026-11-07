<script setup lang="ts">
/** 跨知识库移动笔记：选择目标知识库与目标分组（可选）。 */
import { computed, ref, watch } from 'vue'
import KiwiModal from '@/components/ui/KiwiModal.vue'
import KiwiIcon from '@/components/ui/KiwiIcon.vue'
import KiwiSelect from '@/components/ui/KiwiSelect.vue'
import { request } from '@/api/client'
import { useKbsStore } from '@/stores/kbs'
import type { NoteFolder, NoteTree } from '@/stores/notes'

const props = defineProps<{
  open: boolean
  currentKbId: string | null
  noteTitle: string
}>()

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'move', payload: { kbId: string; folderId: string | null }): void
}>()

const kbs = useKbsStore()
const targetKbId = ref('')
const folderId = ref('')
const folders = ref<NoteFolder[]>([])
const loading = ref(false)
const error = ref('')

const targets = computed(() => kbs.kbs.filter((kb) => kb.id !== props.currentKbId))

const flatFolders = computed(() => {
  const out: Array<{ id: string; name: string; depth: number }> = []
  const walk = (parentId: string | null, depth: number) => {
    for (const folder of [...folders.value]
      .filter((f) => f.parent_id === parentId)
      .sort((a, b) => a.sort_order - b.sort_order)) {
      out.push({ id: folder.id, name: folder.name, depth })
      walk(folder.id, depth + 1)
    }
  }
  walk(null, 0)
  return out
})

const kbOptions = computed(() =>
  targets.value.map((kb) => ({ value: kb.id, label: kb.name })),
)
const folderOptions = computed(() => [
  { value: '', label: '根目录' },
  ...flatFolders.value.map((folder) => ({
    value: folder.id,
    label: `${'　'.repeat(folder.depth)}${folder.name}`,
  })),
])

function setTargetKbId(value: string | number) {
  targetKbId.value = String(value)
}

function setFolderId(value: string | number) {
  folderId.value = String(value)
}

async function loadFolders() {
  folderId.value = ''
  folders.value = []
  if (!targetKbId.value) return
  loading.value = true
  try {
    const tree = await request<NoteTree>('/notes/tree', { kbId: targetKbId.value })
    folders.value = tree.folders
  } catch {
    folders.value = []
  } finally {
    loading.value = false
  }
}

watch(
  () => props.open,
  (open) => {
    if (!open) return
    error.value = ''
    targetKbId.value = targets.value[0]?.id ?? ''
    void loadFolders()
  },
)
watch(targetKbId, () => {
  if (props.open) void loadFolders()
})

function submit() {
  if (!targetKbId.value) {
    error.value = '请选择目标知识库'
    return
  }
  emit('move', { kbId: targetKbId.value, folderId: folderId.value || null })
}
</script>

<template>
  <KiwiModal :open="open" title="移动到其他知识库" max-w="max-w-md" @close="emit('close')">
    <div class="space-y-3.5">
      <p class="text-[12px] leading-relaxed text-slate-500">
        将「{{ noteTitle || '无标题文档' }}」移动到其他知识库，移动后从当前目录移除。
      </p>

      <div v-if="!targets.length" class="rounded-xl border border-dashed border-slate-200 px-4 py-6 text-center">
        <KiwiIcon name="database" :size="20" class="mx-auto text-slate-300" />
        <p class="mt-2 text-[12px] text-slate-400">没有其他知识库可移动</p>
      </div>

      <template v-else>
        <div>
          <label class="block text-[11px] font-medium text-slate-500 mb-1.5">目标知识库</label>
          <KiwiSelect
            :model-value="targetKbId"
            :options="kbOptions"
            width="w-72"
            trigger-class="!h-9 !w-full !justify-between !rounded-lg !border !border-slate-200 !bg-white !px-3 !text-[12.5px] !text-slate-700"
            @update:model-value="setTargetKbId"
          />
        </div>

        <div>
          <label class="block text-[11px] font-medium text-slate-500 mb-1.5">
            目标分组<span class="text-slate-300">（可选）</span>
          </label>
          <KiwiSelect
            :model-value="folderId"
            :options="folderOptions"
            :disabled="loading"
            width="w-72"
            trigger-class="!h-9 !w-full !justify-between !rounded-lg !border !border-slate-200 !bg-white !px-3 !text-[12.5px] !text-slate-700"
            @update:model-value="setFolderId"
          />
          <p v-if="loading" class="mt-1 text-[10.5px] text-slate-400">正在载入目标分组…</p>
        </div>
      </template>

      <p v-if="error" class="text-[11.5px] text-rose-500">{{ error }}</p>

      <div class="flex items-center justify-end gap-2 pt-1">
        <button type="button" class="kiwi-btn-ghost" @click="emit('close')">取消</button>
        <button
          type="button"
          class="kiwi-btn-primary"
          :disabled="!targets.length"
          @click="submit"
        >
          移动
        </button>
      </div>
    </div>
  </KiwiModal>
</template>

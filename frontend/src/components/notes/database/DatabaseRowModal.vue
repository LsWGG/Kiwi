<script setup lang="ts">
/** 数据表行详情 / 新建记录弹窗。 */
import { computed, ref, watch } from 'vue'
import KiwiModal from '@/components/ui/KiwiModal.vue'
import KiwiIcon from '@/components/ui/KiwiIcon.vue'
import KiwiConfirm from '@/components/ui/KiwiConfirm.vue'
import DatabaseCell from './DatabaseCell.vue'
import MarkdownView from '@/components/editor/MarkdownView.vue'
import type { DbField, DbRow } from '@/stores/noteDatabase'
import type { NoteOut } from '@/stores/notes'

const props = withDefaults(
  defineProps<{
    open: boolean
    mode?: 'create' | 'edit'
    fields: DbField[]
    row?: DbRow | null
    preset?: Record<string, any> | null
    /** 记录对应的完整笔记（用于表格内预览正文） */
    note?: NoteOut | null
    noteLoading?: boolean
    noteError?: string
    generating?: boolean
    /** 内嵌数据表的记录没有独立笔记，隐藏「记录笔记」相关区域 */
    noteIntegration?: boolean
  }>(),
  {
    mode: 'edit',
    row: null,
    preset: null,
    note: null,
    noteLoading: false,
    noteError: '',
    generating: false,
    noteIntegration: true,
  },
)

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'save', data: Record<string, any>): void
  (e: 'delete'): void
  (e: 'open-note', noteId: string): void
  (e: 'generate-note'): void
  (e: 'save-template'): void
}>()

const data = ref<Record<string, any>>({})
const confirmOpen = ref(false)

const isCreate = computed(() => props.mode === 'create')
const title = computed(() => {
  const firstText = props.fields.find(
    (f) => f.type === 'text' || f.type === 'long_text' || f.type === 'url',
  )
  const value = firstText ? data.value[firstText.id] : ''
  return value ? String(value) : isCreate.value ? '新建记录' : '记录详情'
})

watch(
  () => props.open,
  (open) => {
    if (!open) {
      confirmOpen.value = false
      return
    }
    const base = props.row?.data ?? props.preset ?? {}
    const next: Record<string, any> = {}
    for (const field of props.fields) {
      const value = base[field.id]
      next[field.id] =
        value !== undefined
          ? value
          : field.type === 'checkbox'
            ? false
            : field.type === 'multi_select'
              ? []
              : null
    }
    data.value = next
  },
  { immediate: true },
)

function update(field: DbField, value: any) {
  data.value = { ...data.value, [field.id]: value }
}

function save() {
  const payload: Record<string, any> = {}
  for (const field of props.fields) {
    const value = data.value[field.id]
    payload[field.id] =
      value === undefined ? (field.type === 'checkbox' ? false : null) : value
  }
  emit('save', payload)
}
</script>

<template>
  <KiwiModal
    :open="open"
    :title="title"
    :max-w="isCreate ? 'max-w-lg' : 'max-w-3xl'"
    @close="emit('close')"
  >
    <div class="max-h-[62vh] overflow-y-auto -mx-1 px-1 space-y-2.5">
      <div v-for="field in fields" :key="field.id" class="flex items-start gap-3">
        <span class="w-24 shrink-0 pt-1.5 text-[11.5px] text-slate-500 truncate">{{ field.name }}</span>
        <div class="flex-1 min-w-0">
          <DatabaseCell
            :field="field"
            :value="data[field.id]"
            boxed
            @update="update(field, $event)"
          />
        </div>
      </div>
      <p v-if="!fields.length" class="py-6 text-center text-[12px] text-slate-400">
        请先添加字段
      </p>

      <!-- 集合记录笔记：表格中的完整内容预览 -->
      <section v-if="noteIntegration && !isCreate && row" class="!mt-4 border-t border-slate-200/70 pt-3">
        <div class="flex items-center gap-2">
          <h4 class="text-[11.5px] font-medium text-slate-600">记录笔记</h4>
          <span
            v-if="row.note_id"
            class="rounded-full border border-kiwi-100 bg-kiwi-50/70 px-1.5 py-0.5 text-[9.5px] text-kiwi-600"
          >
            已生成
          </span>
          <span v-else class="text-[10px] text-slate-400">尚未生成</span>
          <div class="flex-1" />
          <button
            v-if="row.note_id"
            type="button"
            class="flex items-center gap-1 text-[10.5px] text-kiwi-600 hover:underline disabled:text-slate-300"
            :disabled="noteLoading"
            @click="emit('open-note', row.note_id)"
          >
            <KiwiIcon name="bookOpen" :size="11" />
            打开编辑
          </button>
          <button
            v-else
            type="button"
            class="flex items-center gap-1 rounded-md border border-kiwi-200 bg-kiwi-50/60 px-2 py-0.5 text-[10.5px] text-kiwi-600 hover:bg-kiwi-50 disabled:opacity-50"
            :disabled="generating"
            @click="emit('generate-note')"
          >
            <KiwiIcon :name="generating ? 'loader' : 'plus'" :size="11" :spin="generating" />
            生成笔记
          </button>
        </div>
        <p v-if="!row.note_id" class="mt-1.5 text-[10.5px] leading-relaxed text-slate-400">
          导入的记录默认只保存在数据表中；生成后才会有独立正文，可参与标签、@ 提及与知识编译。
        </p>
        <p v-else-if="noteLoading" class="mt-2 flex items-center gap-1.5 text-[11px] text-slate-400">
          <KiwiIcon name="loader" :size="11" spin />
          加载笔记内容…
        </p>
        <p v-else-if="noteError" class="mt-2 text-[11px] text-rose-500">{{ noteError }}</p>
        <div v-else-if="note" class="mt-2">
          <div class="mb-1.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-[10px] text-slate-400">
            <span class="font-medium text-slate-500">{{ note.title }}</span>
            <span>更新于 {{ new Date(note.updated_at).toLocaleString('zh-CN') }}</span>
            <span v-for="tag in note.tags" :key="tag" class="rounded bg-slate-100 px-1 py-0.5 text-slate-500">
              #{{ tag }}
            </span>
          </div>
          <div
            v-if="note.body_md.trim()"
            class="rounded-lg border border-slate-200/70 bg-white/70 px-3 py-2"
          >
            <MarkdownView :content="note.body_md" />
          </div>
          <p v-else class="rounded-lg border border-dashed border-slate-200 px-3 py-4 text-center text-[11px] text-slate-400">
            这篇记录笔记还没有正文，点击「打开编辑」开始补充内容。
          </p>
        </div>
      </section>
    </div>

    <div class="flex items-center gap-2 mt-5">
      <button
        v-if="noteIntegration && !isCreate && row?.note_id"
        class="kiwi-btn-ghost !px-2"
        title="打开这一行对应的完整笔记"
        @click="emit('open-note', row!.note_id!)"
      >
        <KiwiIcon name="bookOpen" :size="14" />
        打开笔记
      </button>
      <button
        v-if="noteIntegration && !isCreate && row"
        class="kiwi-btn-ghost !px-2"
        title="把当前记录保存为可复用的集合模板"
        @click="emit('save-template')"
      >
        <KiwiIcon name="layoutTemplate" :size="14" />
        存为模板
      </button>
      <button
        v-if="!isCreate"
        class="kiwi-btn-ghost !text-rose-500 !px-2"
        @click="confirmOpen = true"
      >
        <KiwiIcon name="trash" :size="14" />
        删除
      </button>
      <div class="flex-1" />
      <button class="kiwi-btn-secondary" @click="emit('close')">取消</button>
      <button class="kiwi-btn-primary" @click="save">
        {{ isCreate ? '创建' : '保存' }}
      </button>
    </div>

    <KiwiConfirm
      v-model="confirmOpen"
      danger
      title="删除记录"
      message="删除后不可恢复。"
      confirm-text="删除"
      @confirm="emit('delete'); emit('close')"
    />
  </KiwiModal>
</template>

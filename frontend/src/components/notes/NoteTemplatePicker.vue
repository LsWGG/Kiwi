<script setup lang="ts">
/** 笔记模板：内置 + 自定义模板的浏览、套用、创建、编辑与删除。 */
import { computed, ref, watch } from 'vue'
import { useNotesStore, type NoteOut, type NoteTemplate } from '@/stores/notes'
import KiwiIcon from '@/components/ui/KiwiIcon.vue'
import KiwiModal from '@/components/ui/KiwiModal.vue'
import MarkdownView from '@/components/editor/MarkdownView.vue'
import KiwiConfirm from '@/components/ui/KiwiConfirm.vue'
import { toast } from '@/components/ui/toast'

const props = withDefaults(
  defineProps<{
    open: boolean
    folderId?: string | null
    /** 非空时创建为该笔记的子笔记；分组跟随父笔记 */
    parentNoteId?: string | null
  }>(),
  { folderId: null, parentNoteId: null },
)
const emit = defineEmits<{
  (e: 'close'): void
  (e: 'created', note: NoteOut): void
}>()

const notes = useNotesStore()

const loading = ref(false)
const usingId = ref<string | null>(null)
const folderId = ref<string>('')

interface TemplateForm {
  id: string | null
  name: string
  description: string
  icon: string
  title_pattern: string
  body_md: string
  tags: string
}

const EMPTY_FORM: TemplateForm = {
  id: null,
  name: '',
  description: '',
  icon: 'note',
  title_pattern: '',
  body_md: '',
  tags: '',
}
const editing = ref(false)
const form = ref<TemplateForm>({ ...EMPTY_FORM })
const saving = ref(false)
const deleting = ref<NoteTemplate | null>(null)
/** 内置模板预览：在同一个弹窗内切换，避免嵌套弹窗互相抢 Esc。 */
const previewing = ref<NoteTemplate | null>(null)

const ICONS = ['note', 'fileText', 'bookOpen', 'layoutTemplate', 'sparkle', 'target']
const ICON_LABEL: Record<string, string> = {
  note: '笔记',
  fileText: '文档',
  bookOpen: '文献',
  layoutTemplate: '结构',
  sparkle: '灵感',
  target: '目标',
}

const folders = computed(() =>
  [...notes.folders].sort(
    (a, b) => a.sort_order - b.sort_order || a.name.localeCompare(b.name, 'zh-CN'),
  ),
)
const builtin = computed(() => notes.templates.filter((t) => t.is_builtin))
const custom = computed(() => notes.templates.filter((t) => !t.is_builtin))
const formTags = computed(() =>
  form.value.tags
    .split(/[,，\s]+/)
    .map((t) => t.trim().replace(/^#/, ''))
    .filter(Boolean),
)

async function load() {
  loading.value = true
  try {
    if (!notes.folders.length) await notes.fetchTree().catch(() => {})
    await notes.fetchTemplates()
  } catch (e: any) {
    toast.error(e.message || '加载模板失败')
  } finally {
    loading.value = false
  }
}

watch(
  () => props.open,
  (open) => {
    if (!open) {
      editing.value = false
      deleting.value = null
      previewing.value = null
      return
    }
    editing.value = false
    previewing.value = null
    folderId.value = props.folderId ?? ''
    void load()
  },
)

watch(
  () => props.folderId,
  (value) => {
    if (props.open) folderId.value = value ?? ''
  },
)

async function use(template: NoteTemplate) {
  usingId.value = template.id
  try {
    const note = await notes.useTemplate(template.id, {
      folder_id: folderId.value || null,
      parent_note_id: props.parentNoteId,
    })
    toast.success(`已从「${template.name}」创建笔记`)
    emit('created', note)
    emit('close')
  } catch (e: any) {
    toast.error(e.message || '创建笔记失败')
  } finally {
    usingId.value = null
  }
}

function startCreate() {
  form.value = { ...EMPTY_FORM }
  editing.value = true
}

function startEdit(template: NoteTemplate) {
  form.value = {
    id: template.id,
    name: template.name,
    description: template.description,
    icon: template.icon,
    title_pattern: template.title_pattern,
    body_md: template.body_md,
    tags: (template.tags_json || []).join(', '),
  }
  editing.value = true
}

async function save() {
  const name = form.value.name.trim()
  if (!name) return
  saving.value = true
  try {
    const payload = {
      name,
      description: form.value.description.trim(),
      icon: form.value.icon,
      title_pattern: form.value.title_pattern.trim(),
      body_md: form.value.body_md,
      tags_json: formTags.value,
    }
    if (form.value.id) {
      await notes.updateTemplate(form.value.id, payload)
      toast.success('模板已更新')
    } else {
      await notes.createTemplate(payload)
      toast.success('模板已创建')
    }
    editing.value = false
  } catch (e: any) {
    toast.error(e.message || '保存模板失败')
  } finally {
    saving.value = false
  }
}

async function confirmDelete() {
  const template = deleting.value
  deleting.value = null
  if (!template) return
  try {
    await notes.deleteTemplate(template.id)
    toast.success('模板已删除')
  } catch (e: any) {
    toast.error(e.message || '删除模板失败')
  }
}

function iconOf(template: NoteTemplate): string {
  return ICONS.includes(template.icon) ? template.icon : 'note'
}
</script>

<template>
  <KiwiModal
    :open="open"
    :title="
      editing
        ? form.id
          ? '编辑模板'
          : '新建模板'
        : previewing
          ? `预览：${previewing.name}`
          : '从模板新建'
    "
    max-w="max-w-3xl"
    @close="emit('close')"
  >
    <!-- 编辑器 -->
    <div v-if="editing" class="space-y-3">
      <div class="grid grid-cols-2 gap-3">
        <label class="block">
          <span class="form-label">模板名称</span>
          <input v-model="form.name" class="kiwi-input" placeholder="例如：周报模板" />
        </label>
        <label class="block">
          <span class="form-label">默认标题</span>
          <input
            v-model="form.title_pattern"
            class="kiwi-input"
            placeholder="支持 {{date}} 占位，可留空"
          />
        </label>
      </div>
      <label class="block">
        <span class="form-label">说明</span>
        <input v-model="form.description" class="kiwi-input" placeholder="这个模板适合什么场景？" />
      </label>
      <div>
        <span class="form-label">图标</span>
        <div class="flex gap-1.5">
          <button
            v-for="icon in ICONS"
            :key="icon"
            type="button"
            class="flex items-center gap-1 rounded-lg border px-2 py-1 text-[11px] transition-colors"
            :class="
              form.icon === icon
                ? 'border-kiwi-300 bg-kiwi-50 text-kiwi-700'
                : 'border-slate-200 text-slate-500 hover:border-kiwi-200'
            "
            @click="form.icon = icon"
          >
            <KiwiIcon :name="icon" :size="13" />
            {{ ICON_LABEL[icon] }}
          </button>
        </div>
      </div>
      <label class="block">
        <span class="form-label">标签（逗号分隔，支持 项目/子标签）</span>
        <input v-model="form.tags" class="kiwi-input" placeholder="会议, 项目/复盘" />
      </label>
      <label class="block">
        <span class="form-label">正文结构（Markdown）</span>
        <textarea
          v-model="form.body_md"
          class="kiwi-input h-48 resize-y font-mono !text-[12px] leading-relaxed"
          placeholder="## 背景&#10;&#10;## 目标&#10;&#10;## 行动项"
        />
      </label>
      <div class="flex justify-end gap-2 pt-1">
        <button class="kiwi-btn-secondary" @click="editing = false">取消</button>
        <button class="kiwi-btn-primary" :disabled="!form.name.trim() || saving" @click="save">
          <KiwiIcon name="check" :size="13" />
          {{ saving ? '保存中…' : '保存模板' }}
        </button>
      </div>
    </div>

    <!-- 模板列表 -->
    <div v-else-if="!previewing">
      <div class="flex items-center gap-2 mb-3">
        <div class="flex items-center gap-1.5 text-[11px] text-slate-500">
          <KiwiIcon name="folder" :size="13" class="text-slate-400" />
          <template v-if="parentNoteId">
            创建到
            <span class="max-w-[12rem] truncate rounded-md bg-kiwi-50 px-1.5 py-0.5 text-kiwi-700">
              {{ notes.notes.find((n) => n.id === parentNoteId)?.title || '父笔记' }} 下级
            </span>
          </template>
          <template v-else>
            创建到
            <select v-model="folderId" class="rounded-lg border border-slate-200 bg-white px-2 py-1 text-[11px] outline-none focus:border-kiwi-300">
              <option value="">根目录</option>
              <option v-for="folder in folders" :key="folder.id" :value="folder.id">
                {{ folder.name }}
              </option>
            </select>
          </template>
        </div>
        <div class="flex-1" />
        <button class="kiwi-btn-secondary !text-[11.5px] !py-1.5" @click="startCreate">
          <KiwiIcon name="plus" :size="12" />
          新建模板
        </button>
      </div>

      <div v-if="loading && !notes.templates.length" class="py-12 text-center text-[12px] text-slate-400">
        <KiwiIcon name="loader" :size="18" spin class="mx-auto mb-2" />
        加载模板中…
      </div>

      <div v-else class="max-h-[58vh] overflow-y-auto pr-1 space-y-5">
        <section v-if="builtin.length">
          <h3 class="tpl-section-title">内置模板</h3>
          <div class="grid grid-cols-1 gap-2.5 sm:grid-cols-2">
            <div
              v-for="template in builtin"
              :key="template.id"
              class="group relative overflow-hidden rounded-2xl border border-slate-200/70 bg-gradient-to-b from-white/90 to-white/55 p-3 transition-all duration-200 hover:-translate-y-0.5 hover:border-kiwi-200 hover:shadow-lifted"
            >
              <span
                class="pointer-events-none absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-kiwi-200/80 to-transparent opacity-0 transition-opacity group-hover:opacity-100"
              />
              <div class="flex items-start gap-2.5">
                <span
                  class="grid h-8 w-8 shrink-0 place-items-center rounded-xl bg-gradient-to-br from-kiwi-50 to-white text-kiwi-600 ring-1 ring-inset ring-kiwi-100"
                >
                  <KiwiIcon :name="iconOf(template)" :size="15" />
                </span>
                <div class="min-w-0 flex-1">
                  <div class="flex items-center gap-1.5">
                    <h3
                      class="truncate text-[12.5px] font-semibold text-slate-700 transition-colors group-hover:text-kiwi-700"
                    >
                      {{ template.name }}
                    </h3>
                    <span class="shrink-0 rounded bg-slate-100 px-1 py-0.5 text-[9px] text-slate-400">
                      内置
                    </span>
                  </div>
                  <p class="mt-0.5 text-[10.5px] text-slate-400 leading-relaxed line-clamp-2">
                    {{ template.description || '预置结构与标签' }}
                  </p>
                </div>
              </div>
              <div class="mt-2 flex flex-wrap items-center gap-1 min-h-[18px]">
                <span
                  v-for="tag in template.tags_json.slice(0, 4)"
                  :key="tag"
                  class="rounded-full bg-kiwi-50/70 px-1.5 py-px text-[9px] text-kiwi-600"
                >
                  {{ tag }}
                </span>
                <span v-if="template.title_pattern" class="truncate text-[9.5px] text-slate-300">
                  标题：{{ template.title_pattern }}
                </span>
              </div>
              <div class="mt-2.5 flex items-center gap-1">
                <button
                  class="kiwi-btn-primary !px-3 !py-1 !text-[10.5px]"
                  :disabled="usingId === template.id"
                  @click="use(template)"
                >
                  <KiwiIcon name="plus" :size="11" />
                  {{ usingId === template.id ? '创建中…' : '使用模板' }}
                </button>
                <span class="flex-1" />
                <button
                  class="kiwi-btn-ghost !p-1"
                  title="预览模板内容"
                  @click="previewing = template"
                >
                  <KiwiIcon name="eye" :size="12" />
                </button>
                <button
                  class="kiwi-btn-ghost !p-1"
                  title="另存为自定义模板"
                  @click="startEdit({ ...template, id: '', is_builtin: false } as any)"
                >
                  <KiwiIcon name="copy" :size="11" />
                </button>
              </div>
            </div>
          </div>
        </section>

        <section>
          <div class="flex items-center justify-between mb-1.5">
            <h3 class="tpl-section-title !mb-0">自定义模板</h3>
            <span class="text-[10px] text-slate-300">{{ custom.length }} 个</span>
          </div>
          <div v-if="custom.length" class="grid grid-cols-1 gap-2.5 sm:grid-cols-2">
            <div
              v-for="template in custom"
              :key="template.id"
              class="group relative overflow-hidden rounded-2xl border border-slate-200/70 bg-gradient-to-b from-white/90 to-white/55 p-3 transition-all duration-200 hover:-translate-y-0.5 hover:border-kiwi-200 hover:shadow-lifted"
            >
              <div class="flex items-start gap-2.5">
                <span
                  class="grid h-8 w-8 shrink-0 place-items-center rounded-xl bg-gradient-to-br from-slate-50 to-white text-slate-500 ring-1 ring-inset ring-slate-200/70"
                >
                  <KiwiIcon :name="iconOf(template)" :size="15" />
                </span>
                <div class="min-w-0 flex-1">
                  <div class="flex items-center gap-1.5">
                    <h3
                      class="truncate text-[12.5px] font-semibold text-slate-700 transition-colors group-hover:text-kiwi-700"
                    >
                      {{ template.name }}
                    </h3>
                    <span
                      v-if="template.props_json?.collection_note_id"
                      class="shrink-0 rounded bg-kiwi-50 px-1 py-0.5 text-[9px] text-kiwi-600"
                    >
                      集合模板
                    </span>
                  </div>
                  <p class="mt-0.5 text-[10.5px] text-slate-400 leading-relaxed line-clamp-2">
                    {{ template.description || '自定义模板' }}
                  </p>
                </div>
              </div>
              <div class="mt-2 flex flex-wrap items-center gap-1 min-h-[18px]">
                <span
                  v-for="tag in template.tags_json.slice(0, 4)"
                  :key="tag"
                  class="rounded-full bg-kiwi-50/70 px-1.5 py-px text-[9px] text-kiwi-600"
                >
                  {{ tag }}
                </span>
              </div>
              <div class="mt-2.5 flex items-center gap-1">
                <button
                  class="kiwi-btn-primary !px-3 !py-1 !text-[10.5px]"
                  :disabled="usingId === template.id"
                  @click="use(template)"
                >
                  <KiwiIcon name="plus" :size="11" />
                  {{ usingId === template.id ? '创建中…' : '使用模板' }}
                </button>
                <span class="flex-1" />
                <button class="kiwi-btn-ghost !p-1" title="编辑" @click="startEdit(template)">
                  <KiwiIcon name="edit" :size="11" />
                </button>
                <button class="kiwi-btn-ghost !p-1" title="删除" @click="deleting = template">
                  <KiwiIcon name="trash" :size="11" />
                </button>
              </div>
            </div>
          </div>
          <p v-else class="rounded-lg border border-dashed border-slate-200 py-5 text-center text-[11px] text-slate-400">
            还没有自定义模板。可以把常用结构保存下来，或从任意笔记「存为模板」。
          </p>
        </section>
      </div>
    </div>

    <!-- 内置模板预览：同一弹窗内切换，保留模板列表的滚动位置 -->
    <div v-else>
      <div v-if="previewing" class="space-y-3">
        <div class="flex items-center gap-2.5">
          <button
            class="kiwi-btn-ghost shrink-0 !p-1.5"
            title="返回模板列表"
            @click="previewing = null"
          >
            <KiwiIcon name="arrowLeft" :size="14" />
          </button>
          <span class="grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-kiwi-50 text-kiwi-600">
            <KiwiIcon :name="iconOf(previewing)" :size="17" />
          </span>
          <div class="min-w-0 flex-1">
            <div class="flex items-center gap-1.5">
              <h3 class="truncate text-[14px] font-semibold text-slate-700">
                {{ previewing.name }}
              </h3>
              <span class="shrink-0 rounded bg-slate-100 px-1 py-0.5 text-[9px] text-slate-400">
                内置
              </span>
            </div>
            <p class="mt-0.5 text-[11px] text-slate-400">
              {{ previewing.description || '预置结构与标签' }}
            </p>
          </div>
          <button
            class="kiwi-btn-primary shrink-0 !py-1.5 !text-[11.5px]"
            :disabled="usingId === previewing.id"
            @click="use(previewing)"
          >
            <KiwiIcon name="plus" :size="11" />
            {{ usingId === previewing.id ? '创建中…' : '使用模板' }}
          </button>
        </div>
        <div class="flex flex-wrap items-center gap-1.5">
          <span
            v-for="tag in previewing.tags_json"
            :key="tag"
            class="rounded-full bg-kiwi-50 px-2 py-0.5 text-[10px] text-kiwi-600"
          >
            #{{ tag }}
          </span>
          <span v-if="previewing.title_pattern" class="text-[10px] text-slate-400">
            默认标题：{{ previewing.title_pattern }}
          </span>
        </div>
        <div class="max-h-[52vh] overflow-y-auto rounded-xl border border-slate-200/80 bg-white/80 px-5 py-4">
          <MarkdownView :content="previewing.body_md || '*该模板没有正文结构*'" />
        </div>
      </div>
    </div>

    <KiwiConfirm
      :model-value="deleting !== null"
      danger
      title="删除模板"
      :message="`确定删除模板「${deleting?.name || ''}」？已用该模板创建的笔记不受影响。`"
      confirm-text="删除"
      @update:model-value="(v: boolean) => { if (!v) deleting = null }"
      @confirm="confirmDelete"
    />
  </KiwiModal>
</template>

<style scoped>
.form-label {
  @apply block text-[10.5px] font-medium text-slate-500 mb-1;
}
.tpl-section-title {
  @apply text-[10.5px] font-semibold tracking-wide text-slate-400 uppercase mb-1.5;
}
</style>

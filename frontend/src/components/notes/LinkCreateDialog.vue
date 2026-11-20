<script setup lang="ts">
/** 新建链接笔记：解析正文 / 只读书签 / iframe 内嵌网页三种打开方式。 */
import { computed, ref, watch } from 'vue'
import KiwiModal from '@/components/ui/KiwiModal.vue'
import KiwiIcon from '@/components/ui/KiwiIcon.vue'
import { useNotesStore, type NoteOut } from '@/stores/notes'
import { toast } from '@/components/ui/toast'

type LinkMode = 'fetch' | 'readonly' | 'embed'

const LINK_MODES: { id: LinkMode; label: string; icon: string; hint: string }[] = [
  {
    id: 'fetch',
    label: '解析正文',
    icon: 'file',
    hint: '由服务器抓取网页正文并转为 Markdown；抓取失败时仍会保存书签卡片。',
  },
  {
    id: 'readonly',
    label: '只读书签',
    icon: 'bookOpen',
    hint: '不抓取网页正文，仅保存标题与摘要，作为纯阅读书签。',
  },
  {
    id: 'embed',
    label: '内嵌网页',
    icon: 'globe',
    hint: '不解析正文，直接在笔记里用 iframe 打开网页。部分网站禁止被内嵌，打不开时可在新窗口打开。',
  },
]

const props = withDefaults(
  defineProps<{
    open: boolean
    folderId?: string | null
    /** 非空时创建为该笔记的子笔记 */
    parentNoteId?: string | null
  }>(),
  { folderId: null, parentNoteId: null },
)

const emit = defineEmits<{ (e: 'close'): void; (e: 'created', note: NoteOut): void }>()

const notes = useNotesStore()
const url = ref('')
const title = ref('')
const loading = ref(false)
const error = ref('')
/** 打开方式：解析正文（默认）/ 只读书签 / iframe 内嵌网页。 */
const mode = ref<LinkMode>('fetch')
const modeHint = computed(
  () => LINK_MODES.find((item) => item.id === mode.value)?.hint ?? '',
)
const submitLabel = computed(() => {
  if (loading.value) return mode.value === 'fetch' ? '抓取中…' : '创建中…'
  return '创建链接'
})

watch(
  () => props.open,
  (open) => {
    if (!open) return
    url.value = ''
    title.value = ''
    error.value = ''
    loading.value = false
    mode.value = 'fetch'
  },
)

async function submit() {
  const raw = url.value.trim()
  if (!raw) {
    error.value = '请输入链接地址'
    return
  }
  let parsed: URL
  try {
    parsed = new URL(raw)
  } catch {
    error.value = '链接格式不正确'
    return
  }
  if (!['http:', 'https:'].includes(parsed.protocol)) {
    error.value = '仅支持 http / https 链接'
    return
  }
  loading.value = true
  error.value = ''
  try {
    const note = await notes.createLink({
      url: parsed.toString(),
      title: title.value.trim() || undefined,
      folder_id: props.folderId,
      parent_note_id: props.parentNoteId,
      readonly: mode.value === 'readonly',
      embed: mode.value === 'embed',
    })
    const ok = note.props_json?.link?.fetch_status === 'ok'
    toast[ok ? 'success' : 'info'](
      mode.value === 'embed'
        ? '已创建内嵌网页笔记'
        : mode.value === 'readonly'
          ? '已创建只读链接'
          : ok
            ? '已抓取网页正文'
            : '暂时无法抓取正文，已保存为书签',
    )
    emit('created', note)
    emit('close')
  } catch (e: any) {
    error.value = e.message || '创建失败'
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <KiwiModal :open="open" title="新建链接" max-w="max-w-md" @close="emit('close')">
    <div class="space-y-3">
      <div>
        <label class="block text-[11px] font-medium text-slate-500 mb-1.5">链接地址</label>
        <div class="relative">
          <span class="absolute left-3 top-1/2 -translate-y-1/2 text-slate-300">
            <KiwiIcon name="link2" :size="14" />
          </span>
          <input
            v-model="url"
            class="kiwi-input !pl-9"
            placeholder="https://example.com/article"
            autofocus
            @keyup.enter="submit"
          />
        </div>
      </div>
      <div>
        <label class="block text-[11px] font-medium text-slate-500 mb-1.5">标题（可选）</label>
        <input v-model="title" class="kiwi-input" placeholder="留空则使用网页标题" @keyup.enter="submit" />
      </div>
      <div>
        <label class="block text-[11px] font-medium text-slate-500 mb-1.5">打开方式</label>
        <div class="grid grid-cols-3 gap-2">
          <button
            v-for="item in LINK_MODES"
            :key="item.id"
            type="button"
            class="flex flex-col items-center gap-1 rounded-lg border px-2 py-2 transition-colors"
            :class="
              mode === item.id
                ? 'border-kiwi-300 bg-kiwi-50 text-kiwi-700'
                : 'border-slate-200 text-slate-500 hover:border-slate-300 hover:text-slate-600'
            "
            @click="mode = item.id"
          >
            <KiwiIcon :name="item.icon" :size="15" />
            <span class="text-[11px] font-medium">{{ item.label }}</span>
          </button>
        </div>
        <p class="mt-2 flex items-start gap-1.5 text-[10.5px] leading-relaxed text-slate-400">
          <KiwiIcon name="sparkle" :size="12" class="mt-0.5 shrink-0" />
          {{ modeHint }}
        </p>
      </div>
      <p v-if="error" class="text-[11.5px] text-rose-500">{{ error }}</p>
    </div>
    <div class="flex justify-end gap-2 mt-5">
      <button class="kiwi-btn-secondary" @click="emit('close')">取消</button>
      <button class="kiwi-btn-primary" :disabled="loading" @click="submit">
        <KiwiIcon v-if="loading" name="loader" :size="14" spin />
        {{ submitLabel }}
      </button>
    </div>
  </KiwiModal>
</template>

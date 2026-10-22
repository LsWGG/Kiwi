<script setup lang="ts">
/** 笔记内容卡片：展示标题、类型、摘要与标签，点击打开原笔记。 */
import { computed, onMounted, ref } from 'vue'
import { NodeViewWrapper, nodeViewProps } from '@tiptap/vue-3'
import { useRouter } from 'vue-router'
import { useKbsStore } from '@/stores/kbs'
import { useNotesStore, type NoteKind, type NoteOut } from '@/stores/notes'
import { request } from '@/api/client'
import KiwiIcon from '@/components/ui/KiwiIcon.vue'
import { useEditorEditable } from './useEditorEditable'

const props = defineProps(nodeViewProps)
const router = useRouter()
const kbs = useKbsStore()
const notes = useNotesStore()

const editable = useEditorEditable(props.editor)
const detail = ref<NoteOut | null>(null)
const missing = ref(false)
const loading = ref(false)

const META: Record<string, { label: string; icon: string; color: string; bg: string }> = {
  doc: { label: '文档', icon: 'file', color: 'text-kiwi-600', bg: 'bg-kiwi-100' },
  import: { label: '导入文档', icon: 'download', color: 'text-orange-500', bg: 'bg-orange-50' },
  database: { label: '数据表', icon: 'table', color: 'text-sky-600', bg: 'bg-sky-50' },
  canvas: { label: '画布', icon: 'pen', color: 'text-violet-600', bg: 'bg-violet-50' },
  notebook: { label: 'Notebook', icon: 'code', color: 'text-emerald-600', bg: 'bg-emerald-50' },
  link: { label: '链接', icon: 'link2', color: 'text-cyan-600', bg: 'bg-cyan-50' },
}

const meta = computed(() => META[String(detail.value?.kind || props.node.attrs.kind)] ?? META.doc)
const summary = computed(
  () =>
    notes.notes.find((note) => note.id === String(props.node.attrs.noteId)) ?? null,
)
const title = computed(
  () =>
    detail.value?.title ||
    summary.value?.title ||
    String(props.node.attrs.title || '') ||
    '未命名笔记',
)
const tags = computed(() => detail.value?.tags ?? summary.value?.tags ?? [])

const excerpt = computed(() => {
  const note = detail.value
  if (!note) return ''
  const kind = note.kind
  if (kind === 'link') {
    return String(note.props_json?.excerpt || '')
  }
  if (kind === 'database' || kind === 'canvas' || kind === 'notebook' || kind === 'sheet') {
    return ''
  }
  return String(note.body_md || '')
    .replace(/```[\s\S]*?```/g, ' ')
    .replace(/!\[[^\]]*\]\([^)]*\)/g, ' ')
    .replace(/\[([^\]]*)\]\([^)]*\)/g, '$1')
    .replace(/[#>*_`~]/g, '')
    .replace(/\s+/g, ' ')
    .trim()
    .slice(0, 150)
})

async function load() {
  const id = String(props.node.attrs.noteId || '')
  if (!id) {
    missing.value = true
    return
  }
  loading.value = true
  try {
    detail.value = await request<NoteOut>(`/notes/${encodeURIComponent(id)}`, {
      kbId: kbs.currentKbId,
    })
  } catch {
    missing.value = true
  } finally {
    loading.value = false
  }
}

function open() {
  const id = String(props.node.attrs.noteId || '')
  if (!id || missing.value) return
  void router.push({ name: 'notes', params: { id } })
}

onMounted(load)
</script>

<template>
  <NodeViewWrapper
    class="kiwi-note-embed-block"
    :class="{ 'is-selected': selected, 'is-missing': missing }"
    data-type="kiwi-note-embed"
    contenteditable="false"
  >
    <div class="kiwi-note-embed-card" @click="open">
      <span class="kiwi-note-embed-icon" :class="[meta.bg, meta.color]">
        <KiwiIcon :name="missing ? 'alert' : meta.icon" :size="17" />
      </span>
      <span class="min-w-0 flex-1">
        <span class="flex items-center gap-2 min-w-0">
          <span class="truncate text-[13px] font-semibold text-slate-700">
            {{ missing ? '原笔记已删除' : title }}
          </span>
          <span
            class="shrink-0 rounded px-1.5 py-[1px] text-[10px] font-medium"
            :class="[meta.bg, meta.color]"
          >
            {{ missing ? '失效引用' : meta.label }}
          </span>
        </span>
        <span v-if="loading" class="mt-0.5 block text-[11px] text-slate-300">加载中…</span>
        <span
          v-else-if="excerpt"
          class="kiwi-note-embed-excerpt mt-0.5 block truncate text-[11px] leading-relaxed text-slate-400"
        >
          {{ excerpt }}
        </span>
        <span v-else-if="!missing" class="mt-0.5 flex items-center gap-2 text-[10.5px] text-slate-400">
          <span v-if="tags.length" class="flex min-w-0 items-center gap-1">
            <KiwiIcon name="hash" :size="10" class="shrink-0 text-slate-300" />
            <span class="truncate">{{ tags.slice(0, 3).map((tag) => `#${tag}`).join(' ') }}</span>
          </span>
          <span v-else>点击打开笔记</span>
        </span>
      </span>
      <span v-if="editable" class="kiwi-note-embed-actions">
        <button
          v-if="!missing"
          type="button"
          class="kiwi-note-embed-open"
          title="打开笔记"
          @mousedown.prevent
          @click.stop="open"
        >
          <KiwiIcon name="arrowRight" :size="13" />
        </button>
        <button
          type="button"
          class="kiwi-note-embed-remove"
          title="移除内容卡片"
          @mousedown.prevent
          @click.stop="props.deleteNode()"
        >
          <KiwiIcon name="close" :size="12" />
        </button>
      </span>
    </div>
  </NodeViewWrapper>
</template>

<style scoped>
.kiwi-note-embed-block {
  margin: 0.6rem 0;
}
.kiwi-note-embed-card {
  position: relative;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 9px 11px 9px 13px;
  border-radius: 11px;
  border: 1px solid rgb(226 232 240);
  background: linear-gradient(180deg, #fff, rgb(var(--kiwi-50) / 0.45));
  cursor: pointer;
  transition: border-color 0.15s ease, box-shadow 0.15s ease, transform 0.15s ease;
}
.kiwi-note-embed-card::before {
  content: '';
  position: absolute;
  inset: 8px auto 8px 0;
  width: 3px;
  border-radius: 999px;
  background: linear-gradient(180deg, rgb(var(--kiwi-400)), rgb(var(--kiwi-600)));
  opacity: 0.55;
  transition: opacity 0.15s ease;
}
.kiwi-note-embed-card:hover {
  border-color: rgb(var(--kiwi-300));
  box-shadow: 0 6px 18px rgb(var(--kiwi-600) / 0.1);
  transform: translateY(-1px);
}
.kiwi-note-embed-card:hover::before {
  opacity: 1;
}
.kiwi-note-embed-block.is-selected .kiwi-note-embed-card {
  border-color: rgb(var(--kiwi-300));
  box-shadow: 0 0 0 3px rgb(var(--kiwi-100) / 0.55);
}
.kiwi-note-embed-block.is-missing .kiwi-note-embed-card {
  border-style: dashed;
  background: rgb(248 250 252);
  cursor: default;
}
.kiwi-note-embed-icon {
  display: grid;
  place-items: center;
  width: 34px;
  height: 34px;
  flex: 0 0 auto;
  border-radius: 9px;
}
.kiwi-note-embed-actions {
  display: flex;
  align-items: center;
  gap: 1px;
  flex: 0 0 auto;
  color: rgb(203 213 225);
}
.kiwi-note-embed-open,
.kiwi-note-embed-remove {
  padding: 4px;
  border-radius: 6px;
  transition: color 0.15s ease, background 0.15s ease;
}
.kiwi-note-embed-open:hover {
  color: rgb(var(--kiwi-600));
  background: rgb(var(--kiwi-50));
}
.kiwi-note-embed-remove:hover {
  color: rgb(220 38 38);
  background: rgb(254 242 242);
}
</style>

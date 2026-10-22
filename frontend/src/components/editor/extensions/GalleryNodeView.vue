<script setup lang="ts">
/** 图册：多图上传、网格 / 横向滑动、说明文字与大图预览。 */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { NodeViewWrapper, nodeViewProps } from '@tiptap/vue-3'
import KiwiIcon from '@/components/ui/KiwiIcon.vue'
import type { GalleryImage } from './gallery'
import { useEditorEditable } from './useEditorEditable'

const props = defineProps(nodeViewProps)

const fileInput = ref<HTMLInputElement | null>(null)
const track = ref<HTMLElement | null>(null)
const uploading = ref(0)
const uploadError = ref('')
const dragOver = ref(false)
const lightbox = ref<number | null>(null)

const editable = useEditorEditable(props.editor)
const images = computed<GalleryImage[]>(() =>
  Array.isArray(props.node.attrs.images)
    ? (props.node.attrs.images as GalleryImage[]).filter((item) => item?.url)
    : [],
)
const columns = computed(() => {
  const value = Number(props.node.attrs.columns)
  return value >= 2 && value <= 4 ? value : 3
})
const layout = computed(() => (props.node.attrs.layout === 'carousel' ? 'carousel' : 'grid'))

const gridStyle = computed(() => ({
  gridTemplateColumns: `repeat(${columns.value}, minmax(0, 1fr))`,
}))

async function addFiles(files: File[]) {
  const picked = files.filter((file) => file.type.startsWith('image/'))
  if (!picked.length) return
  const upload = (props.extension.options as any)?.upload as
    | ((file: File) => Promise<{ url: string; filename?: string }>)
    | undefined
  if (!upload) {
    uploadError.value = '当前编辑器未配置图片上传'
    return
  }
  uploadError.value = ''
  const added: GalleryImage[] = []
  for (const file of picked) {
    uploading.value += 1
    try {
      const result = await upload(file)
      if (result?.url) {
        added.push({ url: result.url, name: result.filename || file.name, caption: '' })
      }
    } catch (e: any) {
      uploadError.value = e?.message || '图片上传失败'
    } finally {
      uploading.value -= 1
    }
  }
  if (added.length) {
    props.updateAttributes({ images: [...images.value, ...added] })
  }
}

function onPick(event: Event) {
  const input = event.target as HTMLInputElement
  void addFiles(Array.from(input.files ?? []))
  input.value = ''
}

function onDrop(event: DragEvent) {
  dragOver.value = false
  if (!editable.value) return
  void addFiles(Array.from(event.dataTransfer?.files ?? []))
}

function setCaption(index: number, value: string) {
  const next = images.value.map((item, i) =>
    i === index ? { ...item, caption: value } : item,
  )
  props.updateAttributes({ images: next })
}

function removeImage(index: number) {
  const next = images.value.filter((_, i) => i !== index)
  if (lightbox.value !== null) {
    if (!next.length) lightbox.value = null
    else if (lightbox.value >= next.length) lightbox.value = next.length - 1
  }
  props.updateAttributes({ images: next })
}

function moveImage(index: number, delta: number) {
  const target = index + delta
  if (target < 0 || target >= images.value.length) return
  const next = [...images.value]
  const [item] = next.splice(index, 1)
  next.splice(target, 0, item)
  props.updateAttributes({ images: next })
}

function scrollTrack(direction: number) {
  const el = track.value
  if (!el) return
  el.scrollBy({ left: direction * Math.max(240, el.clientWidth * 0.72), behavior: 'smooth' })
}

function openLightbox(index: number) {
  lightbox.value = index
}

function stepLightbox(delta: number) {
  if (lightbox.value === null || !images.value.length) return
  lightbox.value = (lightbox.value + delta + images.value.length) % images.value.length
}

function onKeydown(event: KeyboardEvent) {
  if (lightbox.value === null) return
  if (event.key === 'Escape') lightbox.value = null
  if (event.key === 'ArrowLeft') stepLightbox(-1)
  if (event.key === 'ArrowRight') stepLightbox(1)
}

/** 画册被选中时，直接把剪贴板里的图片粘贴进图册。 */
function onPaste(event: ClipboardEvent) {
  if (!editable.value || !props.selected) return
  const files = Array.from(event.clipboardData?.files ?? []).filter((file) =>
    file.type.startsWith('image/'),
  )
  if (!files.length) return
  event.preventDefault()
  event.stopPropagation()
  void addFiles(files)
}

onMounted(() => {
  document.addEventListener('keydown', onKeydown)
  // 捕获阶段优先于 ProseMirror 的粘贴处理，避免图片被插到图册外面。
  document.addEventListener('paste', onPaste, true)
})
onBeforeUnmount(() => {
  document.removeEventListener('keydown', onKeydown)
  document.removeEventListener('paste', onPaste, true)
})
</script>

<template>
  <NodeViewWrapper
    class="kiwi-gallery-block"
    :class="{ 'is-selected': selected, 'is-drag': dragOver, 'is-readonly': !editable }"
    data-type="kiwi-gallery"
    contenteditable="false"
    @dragenter.prevent="editable && (dragOver = true)"
    @dragover.prevent="editable && (dragOver = true)"
    @dragleave.prevent="dragOver = false"
    @drop.prevent="onDrop"
  >
    <div v-if="editable" class="kiwi-gallery-toolbar">
      <span class="kiwi-gallery-tag">
        <KiwiIcon name="image" :size="11" />
        图册
        <em v-if="images.length">{{ images.length }} 张</em>
      </span>
      <span v-if="uploading" class="kiwi-gallery-status">上传中 {{ uploading }}…</span>
      <span v-else-if="uploadError" class="kiwi-gallery-status is-error">{{ uploadError }}</span>
      <div class="ml-auto flex items-center gap-1.5">
        <div class="kiwi-gallery-seg">
          <button
            type="button"
            :class="layout === 'grid' ? 'is-on' : ''"
            title="网格布局"
            @mousedown.prevent
            @click="props.updateAttributes({ layout: 'grid' })"
          >
            <KiwiIcon name="layoutTemplate" :size="12" />
          </button>
          <button
            type="button"
            :class="layout === 'carousel' ? 'is-on' : ''"
            title="横向滑动"
            @mousedown.prevent
            @click="props.updateAttributes({ layout: 'carousel' })"
          >
            <KiwiIcon name="columns" :size="12" />
          </button>
        </div>
        <div v-if="layout === 'grid'" class="kiwi-gallery-seg">
          <button
            v-for="n in [2, 3, 4]"
            :key="n"
            type="button"
            :class="columns === n ? 'is-on' : ''"
            :title="`每行 ${n} 张`"
            @mousedown.prevent
            @click="props.updateAttributes({ columns: n })"
          >
            {{ n }}
          </button>
        </div>
        <button
          type="button"
          class="kiwi-gallery-action"
          title="添加图片"
          @mousedown.prevent
          @click="fileInput?.click()"
        >
          <KiwiIcon name="plus" :size="13" />
        </button>
        <button
          type="button"
          class="kiwi-gallery-action is-danger"
          title="删除图册"
          @mousedown.prevent
          @click="props.deleteNode()"
        >
          <KiwiIcon name="trash" :size="12" />
        </button>
      </div>
      <input
        ref="fileInput"
        type="file"
        accept="image/*"
        multiple
        class="hidden"
        @change="onPick"
      />
    </div>

    <div v-if="!images.length && editable" class="kiwi-gallery-empty" @click="fileInput?.click()">
      <span class="kiwi-gallery-empty-icon"><KiwiIcon name="image" :size="22" /></span>
      <span class="text-[13px] font-medium text-slate-500">点击上传，或把图片拖进来</span>
      <span class="text-[11px] text-slate-400">支持 PNG / JPG / WebP / GIF，可一次选择多张</span>
    </div>

    <div v-else-if="!images.length" class="kiwi-gallery-readonly-empty">暂无图片</div>

    <div v-else-if="layout === 'grid'" class="kiwi-gallery-grid" :style="gridStyle">
      <figure v-for="(image, index) in images" :key="`${image.url}-${index}`" class="kiwi-gallery-item group/item">
        <button type="button" class="kiwi-gallery-thumb" @mousedown.prevent @click="openLightbox(index)">
          <img :src="image.url" :alt="image.caption || image.name || `图片 ${index + 1}`" loading="lazy" />
        </button>
        <div v-if="editable" class="kiwi-gallery-item-bar">
          <input
            :value="image.caption || ''"
            class="kiwi-gallery-caption"
            placeholder="添加说明…"
            @change="setCaption(index, ($event.target as HTMLInputElement).value)"
          />
          <button type="button" class="kiwi-gallery-mini" title="前移" @mousedown.prevent @click="moveImage(index, -1)">
            <KiwiIcon name="arrowLeft" :size="11" />
          </button>
          <button type="button" class="kiwi-gallery-mini" title="后移" @mousedown.prevent @click="moveImage(index, 1)">
            <KiwiIcon name="arrowRight" :size="11" />
          </button>
          <button type="button" class="kiwi-gallery-mini is-danger" title="移除" @mousedown.prevent @click="removeImage(index)">
            <KiwiIcon name="close" :size="11" />
          </button>
        </div>
        <figcaption v-else-if="image.caption" class="kiwi-gallery-caption-static">
          {{ image.caption }}
        </figcaption>
      </figure>
    </div>

    <div v-else class="kiwi-gallery-carousel">
      <button type="button" class="kiwi-gallery-arrow left" @mousedown.prevent @click="scrollTrack(-1)">
        <KiwiIcon name="chevron" :size="16" class="rotate-90" />
      </button>
      <div ref="track" class="kiwi-gallery-track">
        <figure v-for="(image, index) in images" :key="`${image.url}-c-${index}`" class="kiwi-gallery-slide">
          <button type="button" class="kiwi-gallery-thumb" @mousedown.prevent @click="openLightbox(index)">
            <img :src="image.url" :alt="image.caption || image.name || `图片 ${index + 1}`" loading="lazy" />
          </button>
          <figcaption class="kiwi-gallery-slide-caption">
            {{ image.caption || `图片 ${index + 1}` }}
          </figcaption>
        </figure>
      </div>
      <button type="button" class="kiwi-gallery-arrow right" @mousedown.prevent @click="scrollTrack(1)">
        <KiwiIcon name="chevron" :size="16" class="-rotate-90" />
      </button>
    </div>

    <Teleport to="body">
      <div v-if="lightbox !== null && images[lightbox]" class="kiwi-lightbox" @click.self="lightbox = null">
        <button type="button" class="kiwi-lightbox-close" title="关闭 Esc" @click="lightbox = null">
          <KiwiIcon name="close" :size="18" />
        </button>
        <button
          v-if="images.length > 1"
          type="button"
          class="kiwi-lightbox-nav left"
          title="上一张"
          @click.stop="stepLightbox(-1)"
        >
          <KiwiIcon name="chevron" :size="20" class="rotate-90" />
        </button>
        <figure class="kiwi-lightbox-figure">
          <img :src="images[lightbox].url" :alt="images[lightbox].caption || ''" />
          <figcaption v-if="images[lightbox].caption">
            {{ images[lightbox].caption }}
            <span class="kiwi-lightbox-count">{{ lightbox + 1 }} / {{ images.length }}</span>
          </figcaption>
        </figure>
        <button
          v-if="images.length > 1"
          type="button"
          class="kiwi-lightbox-nav right"
          title="下一张"
          @click.stop="stepLightbox(1)"
        >
          <KiwiIcon name="chevron" :size="20" class="-rotate-90" />
        </button>
      </div>
    </Teleport>
  </NodeViewWrapper>
</template>

<style scoped>
.kiwi-gallery-block {
  margin: 0.75rem 0;
  border-radius: 12px;
  border: 1px solid rgb(226 232 240);
  background: rgb(248 250 252 / 0.7);
  transition: border-color 0.15s ease, box-shadow 0.15s ease;
}
/* 阅读模式：去掉组件外框与编辑控件，让图片成为主体 */
.kiwi-gallery-block.is-readonly {
  margin: 0.9rem 0;
  border: 0;
  background: transparent;
  border-radius: 0;
}
.kiwi-gallery-block.is-readonly .kiwi-gallery-grid {
  padding: 0;
}
.kiwi-gallery-block.is-readonly .kiwi-gallery-item,
.kiwi-gallery-block.is-readonly .kiwi-gallery-slide {
  border: 0;
  background: transparent;
}
.kiwi-gallery-caption-static {
  padding: 6px 2px 2px;
  font-size: 11.5px;
  line-height: 1.55;
  color: rgb(100 116 139);
}
.kiwi-gallery-readonly-empty {
  padding: 1.5rem 0;
  text-align: center;
  font-size: 11.5px;
  color: rgb(148 163 184);
}
.kiwi-gallery-block.is-selected,
.kiwi-gallery-block.is-drag {
  border-color: rgb(var(--kiwi-300));
  box-shadow: 0 0 0 3px rgb(var(--kiwi-100) / 0.55);
}
.kiwi-gallery-toolbar {
  display: flex;
  align-items: center;
  gap: 8px;
  min-height: 30px;
  padding: 4px 10px;
  border-bottom: 1px solid rgb(226 232 240 / 0.8);
  color: rgb(100 116 139);
  font-size: 11px;
}
.kiwi-gallery-tag {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-weight: 500;
  color: rgb(71 85 105);
}
.kiwi-gallery-tag em {
  font-style: normal;
  color: rgb(148 163 184);
}
.kiwi-gallery-status {
  color: rgb(148 163 184);
}
.kiwi-gallery-status.is-error {
  color: rgb(220 38 38);
}
.kiwi-gallery-seg {
  display: inline-flex;
  align-items: center;
  padding: 1px;
  border-radius: 7px;
  background: rgb(241 245 249);
}
.kiwi-gallery-seg button {
  min-width: 20px;
  height: 20px;
  padding: 0 4px;
  border-radius: 6px;
  color: rgb(148 163 184);
  font-size: 10.5px;
  line-height: 1;
}
.kiwi-gallery-seg button.is-on {
  color: rgb(63 98 18);
  background: #fff;
  box-shadow: 0 1px 2px rgb(15 23 42 / 0.08);
}
.kiwi-gallery-action {
  padding: 3px;
  border-radius: 6px;
  color: rgb(148 163 184);
}
.kiwi-gallery-action:hover {
  color: rgb(var(--kiwi-600));
  background: rgb(var(--kiwi-50));
}
.kiwi-gallery-action.is-danger:hover {
  color: rgb(220 38 38);
  background: rgb(254 242 242);
}
.kiwi-gallery-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 5px;
  padding: 28px 16px;
  cursor: pointer;
  border-radius: 0 0 12px 12px;
  transition: background 0.15s ease;
}
.kiwi-gallery-empty:hover {
  background: rgb(var(--kiwi-50) / 0.7);
}
.kiwi-gallery-empty-icon {
  display: grid;
  place-items: center;
  width: 42px;
  height: 42px;
  margin-bottom: 2px;
  border-radius: 12px;
  background: rgb(var(--kiwi-100));
  color: rgb(var(--kiwi-600));
}
.kiwi-gallery-grid {
  display: grid;
  gap: 8px;
  padding: 10px;
}
.kiwi-gallery-item {
  min-width: 0;
  overflow: hidden;
  border-radius: 9px;
  border: 1px solid rgb(226 232 240);
  background: #fff;
}
.kiwi-gallery-thumb {
  display: block;
  width: 100%;
  overflow: hidden;
  background: rgb(241 245 249);
}
.kiwi-gallery-thumb img {
  display: block;
  width: 100%;
  height: 136px;
  object-fit: cover;
  transition: transform 0.25s ease;
}
.kiwi-gallery-thumb:hover img {
  transform: scale(1.025);
}
.kiwi-gallery-item-bar {
  display: flex;
  align-items: center;
  gap: 1px;
  padding: 3px 4px 3px 7px;
}
.kiwi-gallery-caption {
  flex: 1;
  min-width: 0;
  border: 0;
  outline: none;
  background: transparent;
  font-size: 11px;
  color: rgb(71 85 105);
}
.kiwi-gallery-caption::placeholder {
  color: rgb(203 213 225);
}
.kiwi-gallery-mini {
  padding: 3px;
  border-radius: 5px;
  color: rgb(203 213 225);
}
.kiwi-gallery-mini:hover {
  color: rgb(71 85 105);
  background: rgb(241 245 249);
}
.kiwi-gallery-mini.is-danger:hover {
  color: rgb(220 38 38);
  background: rgb(254 242 242);
}
.kiwi-gallery-carousel {
  position: relative;
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 10px 6px;
}
.kiwi-gallery-track {
  display: flex;
  gap: 8px;
  overflow-x: auto;
  scroll-snap-type: x mandatory;
  scrollbar-width: thin;
  padding: 0 2px;
}
.kiwi-gallery-slide {
  flex: 0 0 min(78%, 420px);
  scroll-snap-align: center;
  overflow: hidden;
  border-radius: 9px;
  border: 1px solid rgb(226 232 240);
  background: #fff;
}
.kiwi-gallery-slide .kiwi-gallery-thumb img {
  height: 200px;
}
.kiwi-gallery-slide-caption {
  padding: 6px 9px;
  font-size: 11px;
  color: rgb(100 116 139);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.kiwi-gallery-arrow {
  display: grid;
  place-items: center;
  width: 26px;
  height: 26px;
  flex: 0 0 auto;
  border-radius: 999px;
  border: 1px solid rgb(226 232 240);
  background: #fff;
  color: rgb(100 116 139);
  box-shadow: 0 2px 6px rgb(15 23 42 / 0.06);
}
.kiwi-gallery-arrow:hover {
  color: rgb(var(--kiwi-600));
  border-color: rgb(var(--kiwi-200));
}
.kiwi-lightbox {
  position: fixed;
  inset: 0;
  z-index: 200;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgb(15 23 42 / 0.78);
  backdrop-filter: blur(3px);
  padding: 48px;
}
.kiwi-lightbox-figure {
  max-width: min(1100px, 90vw);
  max-height: 86vh;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
}
.kiwi-lightbox-figure img {
  max-width: 100%;
  max-height: 76vh;
  object-fit: contain;
  border-radius: 10px;
  box-shadow: 0 20px 60px rgb(0 0 0 / 0.45);
}
.kiwi-lightbox-figure figcaption {
  color: rgb(226 232 240);
  font-size: 12.5px;
  display: inline-flex;
  align-items: center;
  gap: 10px;
}
.kiwi-lightbox-count {
  color: rgb(148 163 184);
  font-size: 11px;
}
.kiwi-lightbox-close,
.kiwi-lightbox-nav {
  position: absolute;
  display: grid;
  place-items: center;
  width: 36px;
  height: 36px;
  border-radius: 999px;
  color: rgb(226 232 240);
  background: rgb(255 255 255 / 0.12);
  border: 1px solid rgb(255 255 255 / 0.16);
}
.kiwi-lightbox-close:hover,
.kiwi-lightbox-nav:hover {
  background: rgb(255 255 255 / 0.22);
}
.kiwi-lightbox-close {
  top: 18px;
  right: 18px;
}
.kiwi-lightbox-nav.left {
  left: 18px;
  top: 50%;
  transform: translateY(-50%);
}
.kiwi-lightbox-nav.right {
  right: 18px;
  top: 50%;
  transform: translateY(-50%);
}
</style>

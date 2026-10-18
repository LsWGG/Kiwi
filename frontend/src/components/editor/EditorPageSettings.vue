<script setup lang="ts">
/**
 * 页面设置抽屉：按编辑器模式给出不同的排版选项。
 * DOCX 模式对齐官网示例：纸张、方向、页边距、页脚/页眉；
 * 其他模式提供内容宽度、字号、行高与纸张背景。
 */
import { computed, ref, watch } from 'vue'
import KiwiIcon from '@/components/ui/KiwiIcon.vue'
import {
  DOCX_BACKGROUNDS,
  DOCX_PAPERS,
  PAGE_BACKGROUNDS,
  PAGE_FONT_SIZES,
  PAGE_LINE_HEIGHTS,
  PAGE_WIDTHS,
  docxPaperSize,
  type DocxPaper,
  type DocxPrefs,
  type EditorMode,
  type PagePrefs,
  type PageWidth,
} from './modes'

const props = defineProps<{
  mode: EditorMode
  docxPrefs: DocxPrefs
  pagePrefs: PagePrefs
  /** 作为布局中的固定侧栏（默认是覆盖式抽屉） */
  docked?: boolean
}>()

const emit = defineEmits<{
  (e: 'docx-prefs', prefs: DocxPrefs): void
  (e: 'page-prefs', prefs: PagePrefs): void
  (e: 'edit-header'): void
  (e: 'edit-footer'): void
  (e: 'close'): void
}>()

type Tab = 'document' | 'header-footer'
const tab = ref<Tab>('document')
const isDocx = computed(() => props.mode === 'docx')

watch(
  () => props.mode,
  () => {
    tab.value = 'document'
  },
)

const paperSize = computed(() =>
  docxPaperSize(props.docxPrefs.paper, props.docxPrefs.orientation),
)

function setDocx(patch: Partial<DocxPrefs>) {
  emit('docx-prefs', { ...props.docxPrefs, ...patch })
}

function setMargin(side: 'top' | 'right' | 'bottom' | 'left', e: Event) {
  const raw = Number((e.target as HTMLInputElement).value)
  const value = Number.isFinite(raw) ? Math.min(6, Math.max(0, Math.round(raw * 100) / 100)) : 2.54
  emit('docx-prefs', {
    ...props.docxPrefs,
    margins: { ...props.docxPrefs.margins, [side]: value },
  })
}

function onPaper(e: Event) {
  setDocx({ paper: (e.target as HTMLSelectElement).value as DocxPaper })
}

function onBackground(e: Event) {
  setDocx({ background: (e.target as HTMLSelectElement).value as DocxPrefs['background'] })
}

function setPage(patch: Partial<PagePrefs>) {
  emit('page-prefs', { ...props.pagePrefs, ...patch })
}

function onPageBackground(e: Event) {
  setPage({ background: (e.target as HTMLSelectElement).value as PagePrefs['background'] })
}

function setDistance(side: 'headerDistance' | 'footerDistance', e: Event) {
  const raw = Number((e.target as HTMLInputElement).value)
  const value = Number.isFinite(raw)
    ? Math.min(5, Math.max(0, Math.round(raw * 100) / 100))
    : 1.25
  setDocx({ [side]: value } as Partial<DocxPrefs>)
}

/** 当前纸张上展示的页眉 / 页脚字段（首页不同时使用 first*） */
const headerField = computed(() =>
  props.docxPrefs.differentFirstPage ? 'firstHeaderText' : 'headerText',
)
const footerField = computed(() =>
  props.docxPrefs.differentFirstPage ? 'firstFooterText' : 'footerText',
)
const headerTemplate = computed(() => props.docxPrefs[headerField.value])
const footerTemplate = computed(() => props.docxPrefs[footerField.value])

/** 把页码占位符插入页脚，导出时替换为真实页码。 */
function insertFooterToken(token: 'page' | 'pages') {
  const snippet = token === 'page' ? '第 {page} 页' : '共 {pages} 页'
  const prev = footerTemplate.value.trim()
  const separator = !prev ? '' : /[·|]\s*$/.test(prev) ? ' ' : ' · '
  setDocx({ [footerField.value]: `${prev}${separator}${snippet}`, showFooter: true } as Partial<DocxPrefs>)
}

const field = 'h-8 w-full rounded-lg border border-slate-200/90 bg-white px-2 text-[11.5px] text-slate-700 outline-none transition focus:border-kiwi-300 focus:ring-2 focus:ring-kiwi-100'
const label = 'text-[10.5px] font-medium text-slate-400'
const section = 'text-[10px] font-semibold uppercase tracking-[0.12em] text-slate-400'
</script>

<template>
  <aside
    class="flex w-[304px] flex-col border-l border-slate-200/80 bg-white/95 backdrop-blur-xl"
    :class="
      docked
        ? 'relative z-20 h-full shrink-0'
        : 'absolute inset-y-0 right-0 z-40 shadow-[-18px_0_45px_-30px_rgba(15,23,42,0.35)]'
    "
    aria-label="页面设置"
  >
    <div class="flex items-center justify-between border-b border-slate-200/70 px-4 py-3">
      <div>
        <p class="text-[12.5px] font-semibold text-slate-700">页面设置</p>
        <p class="mt-0.5 text-[10px] text-slate-400">仅影响当前笔记的显示与导出</p>
      </div>
      <button
        type="button"
        class="grid h-7 w-7 place-items-center rounded-lg text-slate-400 transition hover:bg-slate-100 hover:text-slate-600"
        title="关闭"
        @click="emit('close')"
      >
        <KiwiIcon name="close" :size="13" />
      </button>
    </div>

    <!-- DOCX：文档 / 页眉页脚 -->
    <div v-if="isDocx" class="mx-3 mt-3 flex rounded-lg bg-slate-100/80 p-0.5">
      <button
        type="button"
        class="flex-1 rounded-md py-1.5 text-[11px] transition"
        :class="tab === 'document' ? 'bg-white font-medium text-slate-700 shadow-sm' : 'text-slate-500'"
        @click="tab = 'document'"
      >
        页面
      </button>
      <button
        type="button"
        class="flex-1 rounded-md py-1.5 text-[11px] transition"
        :class="tab === 'header-footer' ? 'bg-white font-medium text-slate-700 shadow-sm' : 'text-slate-500'"
        @click="tab = 'header-footer'"
      >
        页眉页脚
      </button>
    </div>

    <div class="flex-1 overflow-y-auto px-4 py-4">
      <!-- ============ DOCX 页面 ============ -->
      <template v-if="isDocx && tab === 'document'">
        <section>
          <p :class="section">纸张格式</p>
          <div class="mt-2.5 grid grid-cols-2 gap-2">
            <label class="min-w-0">
              <span :class="label">纸张</span>
              <select :value="docxPrefs.paper" :class="[field, 'mt-1']" @change="onPaper">
                <option v-for="paper in DOCX_PAPERS" :key="paper.id" :value="paper.id">
                  {{ paper.label }}
                </option>
              </select>
            </label>
            <div class="min-w-0">
              <span :class="label">尺寸</span>
              <div
                class="mt-1 flex h-8 items-center rounded-lg border border-slate-200/80 bg-slate-50/80 px-2 text-[11px] tabular-nums text-slate-500"
              >
                {{ paperSize.width }} × {{ paperSize.height }} cm
              </div>
            </div>
          </div>
          <div class="mt-3">
            <span :class="label">方向</span>
            <div class="mt-1 flex gap-1.5">
              <button
                type="button"
                class="flex h-8 flex-1 items-center justify-center gap-1.5 rounded-lg border text-[11px] transition"
                :class="
                  docxPrefs.orientation === 'portrait'
                    ? 'border-kiwi-200 bg-kiwi-50/80 text-kiwi-700'
                    : 'border-slate-200/90 bg-white text-slate-500 hover:text-slate-700'
                "
                @click="setDocx({ orientation: 'portrait' })"
              >
                <KiwiIcon name="file" :size="12" />
                纵向
              </button>
              <button
                type="button"
                class="flex h-8 flex-1 items-center justify-center gap-1.5 rounded-lg border text-[11px] transition"
                :class="
                  docxPrefs.orientation === 'landscape'
                    ? 'border-kiwi-200 bg-kiwi-50/80 text-kiwi-700'
                    : 'border-slate-200/90 bg-white text-slate-500 hover:text-slate-700'
                "
                @click="setDocx({ orientation: 'landscape' })"
              >
                <KiwiIcon name="columns" :size="12" />
                横向
              </button>
            </div>
          </div>
        </section>

        <section class="mt-5 border-t border-slate-100 pt-4">
          <p :class="section">页边距（cm）</p>
          <div class="mt-2.5 grid grid-cols-2 gap-2">
            <label>
              <span :class="label">上</span>
              <input
                type="number"
                min="0"
                max="6"
                step="0.1"
                :value="docxPrefs.margins.top"
                :class="[field, 'mt-1 tabular-nums']"
                @change="setMargin('top', $event)"
              />
            </label>
            <label>
              <span :class="label">下</span>
              <input
                type="number"
                min="0"
                max="6"
                step="0.1"
                :value="docxPrefs.margins.bottom"
                :class="[field, 'mt-1 tabular-nums']"
                @change="setMargin('bottom', $event)"
              />
            </label>
            <label>
              <span :class="label">左</span>
              <input
                type="number"
                min="0"
                max="6"
                step="0.1"
                :value="docxPrefs.margins.left"
                :class="[field, 'mt-1 tabular-nums']"
                @change="setMargin('left', $event)"
              />
            </label>
            <label>
              <span :class="label">右</span>
              <input
                type="number"
                min="0"
                max="6"
                step="0.1"
                :value="docxPrefs.margins.right"
                :class="[field, 'mt-1 tabular-nums']"
                @change="setMargin('right', $event)"
              />
            </label>
          </div>
        </section>

        <section class="mt-5 border-t border-slate-100 pt-4">
          <p :class="section">页面样式</p>
          <div class="mt-2.5 grid grid-cols-2 gap-2">
            <label>
              <span :class="label">页间距（px）</span>
              <input
                type="number"
                min="0"
                max="64"
                step="2"
                :value="docxPrefs.pageGap"
                :class="[field, 'mt-1 tabular-nums']"
                @change="setDocx({ pageGap: Math.min(64, Math.max(0, Number(($event.target as HTMLInputElement).value) || 0)) })"
              />
            </label>
            <label>
              <span :class="label">背景</span>
              <select :value="docxPrefs.background" :class="[field, 'mt-1']" @change="onBackground">
                <option v-for="bg in DOCX_BACKGROUNDS" :key="bg.id" :value="bg.id">
                  {{ bg.label }}
                </option>
              </select>
            </label>
          </div>
        </section>
      </template>

      <!-- ============ DOCX 页眉页脚 ============ -->
      <template v-else-if="isDocx && tab === 'header-footer'">
        <section>
          <p :class="section">版式</p>
          <label class="mt-2.5 flex cursor-pointer items-start gap-2.5 rounded-lg border border-slate-100 bg-slate-50/50 px-2.5 py-2">
            <input
              type="checkbox"
              class="mt-0.5 h-3.5 w-3.5 shrink-0 accent-kiwi-500"
              :checked="docxPrefs.differentFirstPage"
              @change="setDocx({ differentFirstPage: ($event.target as HTMLInputElement).checked })"
            />
            <span class="min-w-0">
              <span class="block text-[11.5px] text-slate-600">首页不同</span>
              <span class="mt-0.5 block text-[10px] leading-relaxed text-slate-400">
                首页使用单独的页眉页脚，留空则首页不显示
              </span>
            </span>
          </label>
          <p
            v-if="docxPrefs.differentFirstPage"
            class="mt-2 rounded-lg border border-slate-100 bg-slate-50/60 px-2.5 py-2 text-[10.5px] leading-relaxed text-slate-400"
          >
            已切换为首页版式：直接在纸张的页眉 / 页脚处点击编辑即可。
          </p>
        </section>

        <section class="mt-5 border-t border-slate-100 pt-4">
          <div class="flex items-center justify-between">
            <p :class="section">页眉</p>
            <button
              type="button"
              class="relative h-4 w-7 rounded-full transition"
              :class="docxPrefs.showHeader ? 'bg-kiwi-500' : 'bg-slate-200'"
              :aria-pressed="docxPrefs.showHeader"
              @click="setDocx({ showHeader: !docxPrefs.showHeader })"
            >
              <span
                class="absolute top-0.5 h-3 w-3 rounded-full bg-white shadow-sm transition-all"
                :class="docxPrefs.showHeader ? 'left-3.5' : 'left-0.5'"
              />
            </button>
          </div>
          <div
            class="mt-2 rounded-lg border border-dashed border-slate-200 bg-slate-50/60 px-2.5 py-2.5"
          >
            <p class="text-[10.5px] leading-relaxed text-slate-400">
              点击纸张上的页眉即可直接输入；留空时自动显示文档标题。
            </p>
            <p
              v-if="headerTemplate"
              class="mt-1 truncate text-[10.5px] text-slate-500"
              :title="headerTemplate"
            >
              当前：{{ headerTemplate }}
            </p>
            <button
              type="button"
              class="mt-2 flex h-7 w-full items-center justify-center gap-1 rounded-lg border border-slate-200/90 bg-white text-[11px] text-slate-600 transition hover:border-kiwi-300 hover:text-kiwi-700 disabled:cursor-not-allowed disabled:opacity-50"
              :disabled="!docxPrefs.showHeader"
              @click="emit('edit-header')"
            >
              <KiwiIcon name="edit" :size="12" />
              在页面上编辑页眉
            </button>
          </div>
        </section>

        <section class="mt-5 border-t border-slate-100 pt-4">
          <div class="flex items-center justify-between">
            <p :class="section">页脚</p>
            <button
              type="button"
              class="relative h-4 w-7 rounded-full transition"
              :class="docxPrefs.showFooter ? 'bg-kiwi-500' : 'bg-slate-200'"
              :aria-pressed="docxPrefs.showFooter"
              @click="setDocx({ showFooter: !docxPrefs.showFooter })"
            >
              <span
                class="absolute top-0.5 h-3 w-3 rounded-full bg-white shadow-sm transition-all"
                :class="docxPrefs.showFooter ? 'left-3.5' : 'left-0.5'"
              />
            </button>
          </div>
          <div
            class="mt-2 rounded-lg border border-dashed border-slate-200 bg-slate-50/60 px-2.5 py-2.5"
          >
            <p class="text-[10.5px] leading-relaxed text-slate-400">
              点击纸张上的页脚即可直接输入，支持 <code class="rounded bg-white px-1 text-[10px] text-slate-500">{page}</code>
              / <code class="rounded bg-white px-1 text-[10px] text-slate-500">{pages}</code> 占位符。
            </p>
            <p
              v-if="footerTemplate"
              class="mt-1 truncate text-[10.5px] text-slate-500"
              :title="footerTemplate"
            >
              当前：{{ footerTemplate }}
            </p>
            <button
              type="button"
              class="mt-2 flex h-7 w-full items-center justify-center gap-1 rounded-lg border border-slate-200/90 bg-white text-[11px] text-slate-600 transition hover:border-kiwi-300 hover:text-kiwi-700 disabled:cursor-not-allowed disabled:opacity-50"
              :disabled="!docxPrefs.showFooter"
              @click="emit('edit-footer')"
            >
              <KiwiIcon name="edit" :size="12" />
              在页面上编辑页脚
            </button>
          </div>
        </section>

        <section class="mt-5 border-t border-slate-100 pt-4">
          <p :class="section">距页面边缘（cm）</p>
          <div class="mt-2.5 grid grid-cols-2 gap-2">
            <label>
              <span :class="label">页眉距顶端</span>
              <input
                type="number"
                min="0"
                max="5"
                step="0.05"
                :value="docxPrefs.headerDistance"
                :class="[field, 'mt-1 tabular-nums']"
                @change="setDistance('headerDistance', $event)"
              />
            </label>
            <label>
              <span :class="label">页脚距底端</span>
              <input
                type="number"
                min="0"
                max="5"
                step="0.05"
                :value="docxPrefs.footerDistance"
                :class="[field, 'mt-1 tabular-nums']"
                @change="setDistance('footerDistance', $event)"
              />
            </label>
          </div>
        </section>

        <section class="mt-5 border-t border-slate-100 pt-4">
          <p :class="section">页码</p>
          <p class="mt-1 text-[10px] leading-relaxed text-slate-400">
            插入到页脚，导出 Word 时自动替换为真实页码
          </p>
          <div class="mt-2 grid grid-cols-2 gap-2">
            <button
              type="button"
              class="flex h-8 items-center justify-center gap-1 rounded-lg border border-slate-200/90 bg-white text-[11px] text-slate-600 transition hover:border-kiwi-300 hover:text-kiwi-700"
              :disabled="!docxPrefs.showFooter"
              @click="insertFooterToken('page')"
            >
              <span class="font-mono text-[10px] text-slate-400">#</span>
              插入页码
            </button>
            <button
              type="button"
              class="flex h-8 items-center justify-center gap-1 rounded-lg border border-slate-200/90 bg-white text-[11px] text-slate-600 transition hover:border-kiwi-300 hover:text-kiwi-700"
              :disabled="!docxPrefs.showFooter"
              @click="insertFooterToken('pages')"
            >
              <span class="font-mono text-[10px] text-slate-400">###</span>
              插入总页数
            </button>
          </div>
          <p
            v-if="footerTemplate"
            class="mt-2 truncate rounded-lg bg-slate-50 px-2.5 py-1.5 text-[10.5px] text-slate-500"
            :title="footerTemplate"
          >
            页脚：{{ footerTemplate }}
          </p>
        </section>

        <p class="mt-4 rounded-lg bg-slate-50 px-2.5 py-2 text-[10.5px] leading-relaxed text-slate-400">
          页眉页脚直接在纸张顶部 / 底部点击即可编辑；这些内容只影响屏幕预览与 Word 导出页面信息，不会写入正文 Markdown。
        </p>
      </template>

      <!-- ============ 其他模式：统一页面设置 ============ -->
      <template v-else>
        <section>
          <p :class="section">内容宽度</p>
          <div class="mt-2 flex rounded-lg bg-slate-100/80 p-0.5">
            <button
              v-for="width in PAGE_WIDTHS"
              :key="width.id"
              type="button"
              class="flex-1 rounded-md py-1.5 text-[11px] transition"
              :class="
                pagePrefs.width === width.id
                  ? 'bg-white font-medium text-slate-700 shadow-sm'
                  : 'text-slate-500'
              "
              @click="setPage({ width: width.id as PageWidth })"
            >
              {{ width.label }}
            </button>
          </div>
        </section>

        <section class="mt-5 border-t border-slate-100 pt-4">
          <p :class="section">正文排版</p>
          <div class="mt-2.5 grid grid-cols-2 gap-2">
            <label>
              <span :class="label">字号（px）</span>
              <select
                :value="pagePrefs.fontSize"
                :class="[field, 'mt-1']"
                @change="setPage({ fontSize: Number(($event.target as HTMLSelectElement).value) })"
              >
                <option v-for="size in PAGE_FONT_SIZES" :key="size" :value="size">{{ size }}</option>
              </select>
            </label>
            <label>
              <span :class="label">行高</span>
              <select
                :value="pagePrefs.lineHeight"
                :class="[field, 'mt-1']"
                @change="setPage({ lineHeight: Number(($event.target as HTMLSelectElement).value) })"
              >
                <option v-for="line in PAGE_LINE_HEIGHTS" :key="line" :value="line">{{ line }}</option>
              </select>
            </label>
          </div>
        </section>

        <section class="mt-5 border-t border-slate-100 pt-4">
          <p :class="section">纸张背景</p>
          <select :value="pagePrefs.background" :class="[field, 'mt-2']" @change="onPageBackground">
            <option v-for="bg in PAGE_BACKGROUNDS" :key="bg.id" :value="bg.id">
              {{ bg.label }}
            </option>
          </select>
        </section>
      </template>
    </div>
  </aside>
</template>

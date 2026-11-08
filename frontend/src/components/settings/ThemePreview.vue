<script setup lang="ts">
/**
 * 主题缩略预览：用主题令牌画一个迷你工作区。
 *
 * 已安装主题通常自带 preview 图，画廊优先展示真实截图；
 * 自定义背景 / 透明度时用本组件实时反映令牌变化。
 */
import { computed } from 'vue'
import { colorToRgbTriplet } from '@/theme/apply'
import {
  DEFAULT_ACCENT,
  DEFAULT_THEME_COLORS,
  normalizeThemeSpec,
  type ThemeSpec,
} from '@/theme/types'

const props = withDefaults(
  defineProps<{
    theme: ThemeSpec
    /** 已解析为可访问 URL 的背景图；不传则使用主题声明。 */
    backgroundImage?: string
    /** 已解析为可访问 URL 的背景视频；存在时优先于背景图。 */
    backgroundVideo?: string
    surfaceOpacity?: number
    surfaceBlur?: number
    backgroundDim?: number
    backgroundBlur?: number
    accent?: string
  }>(),
  {
    backgroundImage: undefined,
    backgroundVideo: undefined,
    surfaceOpacity: undefined,
    surfaceBlur: undefined,
    backgroundDim: undefined,
    backgroundBlur: undefined,
    accent: undefined,
  },
)

const spec = computed(() => normalizeThemeSpec(props.theme))
const palette = computed(() => ({ ...DEFAULT_THEME_COLORS, ...spec.value.colors }))

const opacity = computed(() => props.surfaceOpacity ?? spec.value.surface.opacity)
const blur = computed(() => props.surfaceBlur ?? spec.value.surface.blur)
const dim = computed(() => props.backgroundDim ?? spec.value.background.dim)
const imageBlur = computed(() => props.backgroundBlur ?? spec.value.background.blur)
const image = computed(() => props.backgroundImage || '')
const accent = computed(
  () => props.accent || palette.value.accent || DEFAULT_ACCENT,
)

function rgba(color: string, alpha = 1): string {
  const triplet = colorToRgbTriplet(color)
  if (!triplet) return color
  return `rgb(${triplet} / ${alpha})`
}

const rootStyle = computed(() => ({
  backgroundColor: palette.value['app.background'],
  borderColor: rgba(palette.value['border.default'], 0.8),
}))

const imageStyle = computed(() => {
  if (!image.value) return {}
  return {
    backgroundImage: `url("${image.value.replace(/["\\]/g, encodeURIComponent)}")`,
    backgroundSize: spec.value.background.size,
    backgroundPosition: spec.value.background.position,
    backgroundRepeat: spec.value.background.repeat,
    filter: imageBlur.value > 0 ? `blur(${imageBlur.value}px)` : undefined,
    transform: imageBlur.value > 0 ? 'scale(1.06)' : undefined,
  }
})

const videoStyle = computed(() => ({
  filter: imageBlur.value > 0 ? `blur(${imageBlur.value}px)` : undefined,
  transform: imageBlur.value > 0 ? 'scale(1.06)' : undefined,
}))

const dimStyle = computed(() => ({
  backgroundColor: `rgb(0 0 0 / ${dim.value})`,
}))

const panelStyle = computed(() => ({
  backgroundColor: rgba(palette.value['surface.background'], opacity.value),
  borderColor: rgba(palette.value['border.default'], 0.8),
  backdropFilter: blur.value > 0 ? `blur(${blur.value}px)` : undefined,
  WebkitBackdropFilter: blur.value > 0 ? `blur(${blur.value}px)` : undefined,
}))

const mutedStyle = computed(() => ({
  backgroundColor: rgba(palette.value['surface.muted'], Math.max(opacity.value, 0.6)),
}))

const styles = computed(() => ({
  primary: palette.value['text.primary'],
  secondary: palette.value['text.muted'],
  faint: palette.value['text.faint'],
  border: palette.value['border.default'],
  muted: palette.value['surface.muted'],
  accent: accent.value,
  onAccent: palette.value['accent.foreground'],
}))
</script>

<template>
  <div
    class="relative aspect-[16/10] w-full overflow-hidden rounded-xl border"
    :style="rootStyle"
  >
    <video
      v-if="backgroundVideo"
      class="absolute inset-0 h-full w-full object-cover"
      :src="backgroundVideo"
      autoplay
      muted
      loop
      playsinline
      :style="videoStyle"
    />
    <div v-else-if="image" class="absolute inset-0" :style="imageStyle" />
    <div v-if="dim > 0" class="absolute inset-0" :style="dimStyle" />
    <div class="relative flex h-full gap-2 p-2.5">
      <aside
        class="hidden w-[27%] shrink-0 flex-col gap-2 rounded-lg border p-2 sm:flex"
        :style="panelStyle"
      >
        <span class="h-1.5 w-7 rounded-full" :style="{ backgroundColor: styles.accent }" />
        <span class="mt-1 h-1 w-full rounded-full" :style="{ backgroundColor: styles.secondary }" />
        <span class="h-1 w-3/4 rounded-full" :style="{ backgroundColor: styles.faint }" />
        <span class="h-1 w-5/6 rounded-full" :style="{ backgroundColor: styles.faint }" />
        <span class="h-1 w-2/3 rounded-full" :style="{ backgroundColor: styles.faint }" />
      </aside>
      <div class="flex min-w-0 flex-1 flex-col gap-2">
        <div class="flex items-center justify-between gap-2">
          <div class="flex min-w-0 items-center gap-1.5">
            <span class="h-2 w-14 rounded-full" :style="{ backgroundColor: styles.primary }" />
            <span class="h-1.5 w-7 rounded-full" :style="{ backgroundColor: styles.faint }" />
          </div>
          <span
            class="h-4 w-9 shrink-0 rounded-md"
            :style="{ backgroundColor: styles.accent }"
          />
        </div>
        <div
          class="flex min-h-0 flex-1 flex-col gap-2 rounded-lg border p-2.5"
          :style="panelStyle"
        >
          <span class="h-1.5 w-2/5 rounded-full" :style="{ backgroundColor: styles.primary }" />
          <span class="h-1 w-full rounded-full" :style="{ backgroundColor: styles.secondary }" />
          <span class="h-1 w-11/12 rounded-full" :style="{ backgroundColor: styles.secondary }" />
          <span class="h-1 w-4/5 rounded-full" :style="{ backgroundColor: styles.faint }" />
          <div class="mt-auto flex items-center gap-1.5">
            <span
              class="grid h-4 w-4 place-items-center rounded-md text-[6px] font-semibold"
              :style="{ backgroundColor: styles.accent, color: styles.onAccent }"
            >
              K
            </span>
            <span
              class="h-3.5 w-12 rounded-md"
              :style="{ backgroundColor: styles.muted }"
            />
            <span
              class="ml-auto h-1 w-6 rounded-full"
              :style="{ backgroundColor: styles.faint }"
            />
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

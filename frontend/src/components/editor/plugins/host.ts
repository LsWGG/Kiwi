/**
 * 组件插件宿主 API。
 *
 * 插件入口是一个单文件 ESM，导出 `setup(host)`：
 *
 *   export function setup(host) {
 *     const { h, defineComponent } = host.vue
 *     return { blocks: { counter: { component: MyCounter } } }
 *   }
 *
 * 浏览器端插件与应用同源执行，拥有页面权限；安装前必须确认来源可信。
 */
import * as Vue from 'vue'
import { computed, ref, type Component, type ComputedRef, type Ref } from 'vue'
import { toast } from '@/components/ui/toast'

export const PLUGIN_API_VERSION = 1

export interface PluginToast {
  success: (message: string) => void
  error: (message: string) => void
  info: (message: string) => void
}

/**
 * 主题色访问器。系统切换主题色 / 学习模式时 `version` 自增，
 * 基于 computed 的组件会自动重渲染；纯展示优先直接用 CSS 变量 `--kiwi-*`。
 */
export interface PluginTheme {
  /** 主题版本号；watch 它可在主题变化时重绘 canvas / SVG。 */
  version: Ref<number>
  /** 主色，如 `rgb(111 114 220)`。 */
  accent: ComputedRef<string>
  /** 600 档主色，适合文字 / 描边。 */
  accentStrong: ComputedRef<string>
  /** 12% 透明度的主色，适合背景 / 选中态。 */
  accentSoft: ComputedRef<string>
  /** 读取 50–900 任意色阶，alpha 可选（0–1）。 */
  shade: (step: number, alpha?: number) => string
}

export interface PluginHost {
  apiVersion: number
  vue: typeof Vue
  toast: PluginToast
  theme: PluginTheme
}

const DEFAULT_TRIPLET = '111 114 220'
const themeVersion = ref(0)
let themeObserver: MutationObserver | null = null

function bumpThemeVersion() {
  themeVersion.value += 1
}

function ensureThemeObserver() {
  if (typeof document === 'undefined' || themeObserver) return
  themeObserver = new MutationObserver(bumpThemeVersion)
  const options: MutationObserverInit = {
    attributes: true,
    attributeFilter: ['style', 'class'],
  }
  themeObserver.observe(document.documentElement, options)
  if (document.body) {
    themeObserver.observe(document.body, options)
  } else {
    document.addEventListener(
      'DOMContentLoaded',
      () => {
        if (document.body) themeObserver?.observe(document.body, options)
        bumpThemeVersion()
      },
      { once: true },
    )
  }
}

ensureThemeObserver()

/** 读取 CSS 自定义属性；兼容 var(--learn-*) 尚未解析的浏览器。 */
function readCustomProperty(name: string): string {
  if (typeof document === 'undefined') return ''
  const target = document.body || document.documentElement
  let raw = getComputedStyle(target).getPropertyValue(name).trim()
  if (!raw.includes('var(')) return raw
  const match = /^var\(\s*(--[\w-]+)/.exec(raw)
  if (!match) return ''
  raw = getComputedStyle(document.documentElement)
    .getPropertyValue(match[1])
    .trim()
  return raw.includes('var(') ? '' : raw
}

function readTriplet(step: number): string {
  const raw = readCustomProperty(`--kiwi-${step}`)
  const parts = raw.split(/[\s,]+/).filter(Boolean)
  if (
    parts.length >= 3 &&
    parts.slice(0, 3).every((part) => /^[\d.]+$/.test(part))
  ) {
    return `${parts[0]} ${parts[1]} ${parts[2]}`
  }
  return DEFAULT_TRIPLET
}

function shade(step: number, alpha = 1): string {
  // 读取 version 以建立响应式依赖：色阶变化后 computed / 渲染函数重新求值。
  void themeVersion.value
  const triplet = readTriplet(step)
  return alpha >= 1 ? `rgb(${triplet})` : `rgb(${triplet} / ${alpha})`
}

const theme: PluginTheme = {
  version: themeVersion,
  accent: computed(() => shade(500)),
  accentStrong: computed(() => shade(600)),
  accentSoft: computed(() => shade(500, 0.12)),
  shade,
}

export interface PluginBlockDefinition {
  component: Component
  defaultProps?: Record<string, unknown>
  label?: string
  icon?: string
  description?: string
}

export interface PluginSetupResult {
  blocks?: Record<string, PluginBlockDefinition>
}

export type PluginSetup = (
  host: PluginHost,
) => PluginSetupResult | Record<string, PluginBlockDefinition> | void | Promise<
  PluginSetupResult | Record<string, PluginBlockDefinition> | void
>

export const pluginHost: PluginHost = {
  apiVersion: PLUGIN_API_VERSION,
  vue: Vue,
  toast,
  theme,
}

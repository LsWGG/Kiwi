/**
 * jvs-draw 运行时懒加载。
 *
 * jvs-draw 的 JS / CSS 体积很大（压缩后仍有 20MB+），只在真正进入画布编辑时
 * 加载；阅读态、分享页、便签预览与导出都走静态 SVG，不触发这里。
 *
 * 画布挂载在独立 Vue 应用里，避免 Element Plus 的全局样式与组件注册影响
 * 主应用；同时每个画布实例拥有自己的 Pinia，互不串状态。
 */
import type { Component } from 'vue'

export interface DrawRuntime {
  JvsDraw: Component
  ElementPlus: any
}

let pending: Promise<DrawRuntime> | null = null

export function loadDrawRuntime(): Promise<DrawRuntime> {
  if (pending) return pending
  pending = Promise.all([
    import('jvs-draw'),
    import('element-plus'),
    import('element-plus/dist/index.css'),
    import('remixicon/fonts/remixicon.css'),
    import('jvs-picker-color-v3/lib/jvs-picker-color-v3.css'),
    import('jvs-draw/jvs-draw.css'),
    // 素材库/模板库预览图标不在主 sprite 里，由 iconfont.js 注入第二段 SVG sprite。
    import('jvs-draw/dist/jvs-ui-public/icon-fonts/iconfont.js'),
  ])
    .then(([draw, element]) => ({
      JvsDraw: ((draw as any).JvsDraw ?? (draw as any).default) as Component,
      ElementPlus: (element as any).default ?? element,
    }))
    .catch((error) => {
      pending = null
      throw error
    })
  return pending
}

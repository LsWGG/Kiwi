/**
 * 大屏整体放大比例：4K / 2K 屏幕上文字与控件不再偏小。
 *
 * body 应用 `zoom: var(--ui-scale)`，放在视口坐标系里的浮层（toast、菜单、
 * 便签）必须用同一套比例换算视觉尺寸；这里作为唯一来源，避免 App 与
 * 浮层各算一套后在 1920 及以上宽度出现坐标漂移。
 */
export function uiScaleForWidth(width: number): number {
  return width >= 4000 ? 1.75 : width >= 3200 ? 1.5 : width >= 2400 ? 1.3 : width >= 1800 ? 1.12 : 1
}

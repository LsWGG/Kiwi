/** 画布主题：画布底色、网格、节点配色与连线颜色统一由主题提供。 */
import type { CanvasThemeId, CanvasTone } from './types'

export interface ToneStyle {
  fill: string
  stroke: string
  text: string
}

export interface CanvasTheme {
  id: CanvasThemeId
  name: string
  desc: string
  /** 主题色块，用于下拉菜单预览 */
  swatches: string[]
  bg: string
  grid: string
  gridStrong: string
  edge: string
  edgeLabelBg: string
  accent: string
  selection: string
  guide: string
  handleFill: string
  node: ToneStyle
  tones: Record<CanvasTone, ToneStyle>
}

export const THEMES: Record<CanvasThemeId, CanvasTheme> = {
  blueprint: {
    id: 'blueprint',
    name: '工程蓝图',
    desc: '深蓝制图台 · 冷蓝发光（默认）',
    swatches: ['#0b1f3a', '#3b82f6', '#38bdf8', '#93c5fd'],
    bg: '#0b1f3a',
    grid: 'rgba(96, 165, 250, 0.12)',
    gridStrong: 'rgba(96, 165, 250, 0.24)',
    edge: '#60a5fa',
    edgeLabelBg: '#0b1f3a',
    accent: '#38bdf8',
    selection: '#38bdf8',
    guide: '#fb7185',
    handleFill: '#0b1f3a',
    node: { fill: '#102a4c', stroke: '#3b82f6', text: '#dbeafe' },
    tones: {
      neutral: { fill: '#102a4c', stroke: '#3b82f6', text: '#dbeafe' },
      accent: { fill: '#0c4a6e', stroke: '#38bdf8', text: '#e0f2fe' },
      green: { fill: '#064e3b', stroke: '#34d399', text: '#d1fae5' },
      amber: { fill: '#451a03', stroke: '#fbbf24', text: '#fef3c7' },
      rose: { fill: '#4c0519', stroke: '#fb7185', text: '#ffe4e6' },
      violet: { fill: '#2e1065', stroke: '#a78bfa', text: '#ede9fe' },
    },
  },
  engineering: {
    id: 'engineering',
    name: '浅色工作台',
    desc: '浅色网格 · 蓝色主线',
    swatches: ['#f8fafc', '#0ea5e9', '#38bdf8', '#94a3b8'],
    bg: '#f8fafc',
    grid: 'rgba(148, 163, 184, 0.18)',
    gridStrong: 'rgba(148, 163, 184, 0.3)',
    edge: '#64748b',
    edgeLabelBg: '#f8fafc',
    accent: '#0ea5e9',
    selection: '#0ea5e9',
    guide: '#f472b6',
    handleFill: '#ffffff',
    node: { fill: '#ffffff', stroke: '#cbd5e1', text: '#1e293b' },
    tones: {
      neutral: { fill: '#ffffff', stroke: '#cbd5e1', text: '#1e293b' },
      accent: { fill: '#e0f2fe', stroke: '#38bdf8', text: '#075985' },
      green: { fill: '#dcfce7', stroke: '#4ade80', text: '#166534' },
      amber: { fill: '#fef3c7', stroke: '#fbbf24', text: '#92400e' },
      rose: { fill: '#ffe4e6', stroke: '#fb7185', text: '#9f1239' },
      violet: { fill: '#ede9fe', stroke: '#a78bfa', text: '#5b21b6' },
    },
  },
  paper: {
    id: 'paper',
    name: '手绘纸感',
    desc: '暖白纸面 · 便签配色',
    swatches: ['#fbf7ef', '#d97706', '#f59e0b', '#a8a29e'],
    bg: '#fbf7ef',
    grid: 'rgba(120, 90, 50, 0.1)',
    gridStrong: 'rgba(120, 90, 50, 0.2)',
    edge: '#78716c',
    edgeLabelBg: '#fbf7ef',
    accent: '#d97706',
    selection: '#d97706',
    guide: '#e11d48',
    handleFill: '#fffdf7',
    node: { fill: '#fffdf7', stroke: '#d6d3d1', text: '#44403c' },
    tones: {
      neutral: { fill: '#fffdf7', stroke: '#d6d3d1', text: '#44403c' },
      accent: { fill: '#ffedd5', stroke: '#fb923c', text: '#9a3412' },
      green: { fill: '#ecfccb', stroke: '#a3e635', text: '#3f6212' },
      amber: { fill: '#fef9c3', stroke: '#facc15', text: '#854d0e' },
      rose: { fill: '#ffe4e6', stroke: '#fb7185', text: '#9f1239' },
      violet: { fill: '#f3e8ff', stroke: '#c084fc', text: '#6b21a8' },
    },
  },
  midnight: {
    id: 'midnight',
    name: '午夜暗色',
    desc: '深灰画布 · 柔和霓虹',
    swatches: ['#0f172a', '#a78bfa', '#22d3ee', '#64748b'],
    bg: '#0f172a',
    grid: 'rgba(148, 163, 184, 0.1)',
    gridStrong: 'rgba(148, 163, 184, 0.2)',
    edge: '#94a3b8',
    edgeLabelBg: '#0f172a',
    accent: '#a78bfa',
    selection: '#a78bfa',
    guide: '#f472b6',
    handleFill: '#0f172a',
    node: { fill: '#1e293b', stroke: '#475569', text: '#e2e8f0' },
    tones: {
      neutral: { fill: '#1e293b', stroke: '#475569', text: '#e2e8f0' },
      accent: { fill: '#164e63', stroke: '#22d3ee', text: '#cffafe' },
      green: { fill: '#064e3b', stroke: '#34d399', text: '#d1fae5' },
      amber: { fill: '#451a03', stroke: '#fbbf24', text: '#fef3c7' },
      rose: { fill: '#4c0519', stroke: '#fb7185', text: '#ffe4e6' },
      violet: { fill: '#2e1065', stroke: '#c4b5fd', text: '#ede9fe' },
    },
  },
}

export function themeOf(id: CanvasThemeId): CanvasTheme {
  return THEMES[id] ?? THEMES.engineering
}

export function toneStyle(theme: CanvasTheme, tone?: CanvasTone): ToneStyle {
  return theme.tones[tone ?? 'neutral']
}

/** 主题是否偏暗，供浮动工具条的明暗样式使用。 */
export function isDark(theme: CanvasTheme): boolean {
  return theme.id === 'blueprint' || theme.id === 'midnight'
}

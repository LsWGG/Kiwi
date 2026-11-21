/**
 * 左侧主导航（SideNav / LearnSideNav）的收起状态。
 *
 * 编辑模式与学习模式共用同一份偏好；聊天页的引用预览展开时，主导航需要
 * 临时收起给双栏阅读让位，关闭预览后恢复。用模块级 ref 共享，避免布局
 * 组件与页面组件之间靠事件或 props 传状态。
 */
import { readonly, ref } from 'vue'

const STORAGE_KEY = 'kiwi.sidenav.collapsed'

function readStored(): boolean {
  try {
    return localStorage.getItem(STORAGE_KEY) === '1'
  } catch {
    return false
  }
}

const collapsed = ref(readStored())
/** 当前收起是否由引用预览临时触发：只有这种收起会在预览关闭时自动恢复。 */
let autoCollapsed = false

function persist() {
  try {
    localStorage.setItem(STORAGE_KEY, collapsed.value ? '1' : '0')
  } catch {
    /* 隐私模式下 localStorage 不可用 */
  }
}

function setCollapsed(value: boolean) {
  collapsed.value = value
  persist()
}

export const navCollapsed = readonly(collapsed)

/** 用户手动收起 / 展开；手动操作后预览关闭时不再替用户改回去。 */
export function toggleNavCollapsed() {
  autoCollapsed = false
  setCollapsed(!collapsed.value)
}

/** 引用预览展开时收起导航；用户本来已收起时保持原样。 */
export function autoCollapseNav() {
  if (collapsed.value) return
  autoCollapsed = true
  setCollapsed(true)
}

/** 引用预览关闭时恢复导航；只撤销自动收起，不动用户手动收起的状态。 */
export function restoreNav() {
  if (!autoCollapsed) return
  autoCollapsed = false
  setCollapsed(false)
}

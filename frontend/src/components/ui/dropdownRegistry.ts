/**
 * 下拉面板归属登记表。
 *
 * 面板会 Teleport 到 <html> 下，嵌套下拉（筛选面板里的字段选择器）因此
 * 失去 DOM 嵌套关系；同时 slot 内容的组件父级是插槽拥有者，provide/inject
 * 也拿不到外层下拉。这里用模块级登记表记录「谁的面板」与「打开时所在的
 * 外层面板」，点击内层面板时外层据此判断命中的是自己的子级。
 */
export interface DropdownHandle {
  isOpen(): boolean
  owns(target: Node): boolean
  panelEl(): HTMLElement | null
  ancestorPanelEl(): HTMLElement | null
}

const OPEN_DROPDOWNS = new Set<DropdownHandle>()
const PANEL_OWNERS = new WeakMap<HTMLElement, DropdownHandle>()

export function registerDropdown(handle: DropdownHandle): void {
  OPEN_DROPDOWNS.add(handle)
}

export function unregisterDropdown(handle: DropdownHandle): void {
  OPEN_DROPDOWNS.delete(handle)
  const panel = handle.panelEl()
  if (panel) PANEL_OWNERS.delete(panel)
}

export function registerPanel(panel: HTMLElement, handle: DropdownHandle): void {
  PANEL_OWNERS.set(panel, handle)
}

/** descendant 是否是 candidate 的嵌套子级（沿打开时记录的父面板链上溯）。 */
function isNestedIn(candidate: DropdownHandle, descendant: DropdownHandle): boolean {
  if (descendant === candidate) return false
  const ownPanel = candidate.panelEl()
  let panel = descendant.ancestorPanelEl()
  if (ownPanel && panel === ownPanel) return true
  for (let depth = 0; panel && depth < 16; depth += 1) {
    const owner = PANEL_OWNERS.get(panel)
    if (owner === candidate) return true
    panel = owner?.ancestorPanelEl() ?? null
  }
  return false
}

/** 点击是否落在自己或自己的嵌套子级面板里。 */
export function ownsOrNested(handle: DropdownHandle, target: Node): boolean {
  if (handle.owns(target)) return true
  for (const other of OPEN_DROPDOWNS) {
    if (other !== handle && other.isOpen() && other.owns(target) && isNestedIn(handle, other)) {
      return true
    }
  }
  return false
}

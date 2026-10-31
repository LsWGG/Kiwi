/**
 * Kiwi 示例组件插件：计数器。
 *
 * 约束：
 * - 单文件 ESM，浏览器直接加载，不能 import 任何裸模块（包括 "vue"）。
 * - 所有 Vue API 从 setup(host) 的 host.vue 获取。
 * - 必须导出 setup(host)，并返回 { blocks: { [type]: { component } } }。
 * - 组件通过 props 与宿主交互：blockProps / readonly / selected /
 *   updateProps / deleteBlock。props 会随 Markdown 一起保存。
 */
export function setup(host) {
  const { defineComponent, h } = host.vue
  const toast = host.toast

  const CounterBlock = defineComponent({
    name: 'KiwiCounterBlock',
    props: {
      blockProps: { type: Object, default: () => ({}) },
      readonly: { type: Boolean, default: false },
      selected: { type: Boolean, default: false },
      updateProps: { type: Function, default: null },
      deleteBlock: { type: Function, default: null },
    },
    setup(props) {
      function currentCount() {
        const value = Number(props.blockProps && props.blockProps.count)
        return Number.isFinite(value) ? value : 0
      }

      function commit(next) {
        if (props.readonly || typeof props.updateProps !== 'function') return
        props.updateProps({ count: next })
      }

      function reset() {
        commit(0)
        if (toast && typeof toast.success === 'function') {
          toast.success('计数已重置')
        }
      }

      return function render() {
        const label = String(
          (props.blockProps && props.blockProps.label) || '计数',
        )
        const value = currentCount()

        if (props.readonly) {
          return h('div', { class: 'kiwi-counter is-readonly' }, [
            h('span', { class: 'kiwi-counter__label' }, label),
            h('span', { class: 'kiwi-counter__value' }, String(value)),
          ])
        }

        return h(
          'div',
          {
            class: ['kiwi-counter', props.selected ? 'is-selected' : ''],
          },
          [
            h('span', { class: 'kiwi-counter__label' }, label),
            h('button', {
              type: 'button',
              class: 'kiwi-counter__btn',
              title: '减一',
              onClick: () => commit(value - 1),
            }, '−'),
            h('span', { class: 'kiwi-counter__value' }, String(value)),
            h('button', {
              type: 'button',
              class: 'kiwi-counter__btn',
              title: '加一',
              onClick: () => commit(value + 1),
            }, '+'),
            h('button', {
              type: 'button',
              class: 'kiwi-counter__reset',
              onClick: reset,
            }, '重置'),
            props.selected && typeof props.deleteBlock === 'function'
              ? h('button', {
                  type: 'button',
                  class: 'kiwi-counter__remove',
                  title: '删除区块',
                  onClick: () => props.deleteBlock(),
                }, '删除')
              : null,
          ],
        )
      }
    },
  })

  return {
    blocks: {
      counter: {
        component: CounterBlock,
        defaultProps: { label: '计数', count: 0 },
      },
    },
  }
}

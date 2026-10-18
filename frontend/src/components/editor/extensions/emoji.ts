/**
 * 表情：输入 : 打开表情候选，选中后插入 emoji 节点（也可输入 :smile: 自动转换）。
 * Markdown 持久化为原生 emoji 字符，重新加载不会丢失。
 */
import Emoji, { emojis } from '@tiptap/extension-emoji'
import { createSuggestionPopup } from './suggestionPopup'

type EmojiItem = (typeof emojis)[number]

const emojiByName = new Map(emojis.map((item) => [item.name, item]))

const COMMON = [
  'smile',
  'joy',
  'heart',
  '+1',
  'tada',
  'rocket',
  'fire',
  'eyes',
  'clap',
  'pray',
  'bulb',
  'warning',
  'white_check_mark',
  'x',
  'star',
  'sparkles',
  'coffee',
  'book',
  'memo',
  'pushpin',
  'lock',
  'key',
  'bell',
  'calendar',
  'chart_with_upwards_trend',
  '100',
  'grinning',
  'sob',
  'thinking',
  '100',
]

/** 常用中文关键词，方便直接搜「笑」「赞」 */
const ZH_ALIASES: Record<string, string> = {
  微笑: 'smile',
  开心: 'grinning',
  笑: 'joy',
  哭: 'sob',
  思考: 'thinking',
  心: 'heart',
  点赞: '+1',
  赞: '+1',
  踩: '-1',
  庆祝: 'tada',
  火箭: 'rocket',
  火: 'fire',
  眼睛: 'eyes',
  鼓掌: 'clap',
  祈祷: 'pray',
  灯泡: 'bulb',
  注意: 'warning',
  警告: 'warning',
  完成: 'white_check_mark',
  对: 'white_check_mark',
  错: 'x',
  星: 'star',
  闪: 'sparkles',
  咖啡: 'coffee',
  书: 'book',
  笔记: 'memo',
  图钉: 'pushpin',
  锁: 'lock',
  钥匙: 'key',
  铃铛: 'bell',
  日历: 'calendar',
  上升: 'chart_with_upwards_trend',
  满分: '100',
}

function search(query: string): EmojiItem[] {
  const keyword = query.trim().toLowerCase()
  if (!keyword) {
    const seen = new Set<string>()
    return COMMON.map((name) => emojiByName.get(name))
      .filter((item): item is EmojiItem => {
        if (!item || seen.has(item.name)) return false
        seen.add(item.name)
        return true
      })
      .slice(0, 24)
  }
  const aliased = ZH_ALIASES[keyword]
  return emojis
    .filter((item) => {
      if (aliased && item.name === aliased) return true
      const haystack = `${item.name} ${(item.shortcodes || []).join(' ')} ${(item.tags || []).join(' ')}`
      return haystack.toLowerCase().includes(keyword)
    })
    .slice(0, 32)
}

export const KiwiEmoji = Emoji.extend({
  addStorage() {
    return {
      ...this.parent?.(),
      markdown: {
        serialize(state: any, node: any) {
          const item = emojiByName.get(node.attrs.name)
          state.write(item?.emoji || `:${node.attrs.name}:`)
        },
      },
    }
  },
}).configure({
  HTMLAttributes: { class: 'kiwi-emoji' },
  enableEmoticons: false,
  suggestion: {
    char: ':',
    allowSpaces: false,
    // 中英文正文中都可以用 : 触发
    allowedPrefixes: null,
    items: ({ query }: { query: string }) => search(String(query || '')),
    render: createSuggestionPopup<EmojiItem>({
      menuClass: 'emoji-suggest-menu',
      boxClass: 'emoji-suggest-box',
      render: (items, active) =>
        `<div class="kiwi-suggest-head">表情 <span class="kiwi-suggest-tip">继续输入可筛选</span></div>` +
        `<div class="emoji-suggest-grid">` +
        items
          .map(
            (item, i) =>
              `<button type="button" data-i="${i}" class="emoji-suggest-item${i === active ? ' is-active' : ''}"` +
              ` title=":${item.name}:" aria-label="${item.name}">${item.emoji || ':' + item.name + ':'}</button>`,
          )
          .join('') +
        `</div>`,
    }),
  },
})

# 极光（aurora）

Kiwi 主题插件最小示例：深色极光渐变、冷色玻璃面板与青绿强调色。

- `plugin.json`：manifest + `theme` 规格（颜色、背景、透明度、字体）
- `theme.css`：装饰性样式，全部限定在 `html[data-kiwi-theme="aurora"]`
- `assets/aurora.svg`：背景图
- `assets/preview.svg`：主题画廊占位缩略图

> 占位图只用于演示包结构。正式交付的主题必须按规范截取「欢迎使用 Kiwi」
> 笔记页面作为预览图，见 `docs/THEME_SPEC.md` 第 7.1 节。

需要动态背景时，把视频放进 `assets/`，在 `theme.background.video` 填写相对
路径，并让 `theme.background.image` 指向同画面的封面图即可。视频支持
mp4 / webm / ogv / ogg / mov，单个 ≤ 48MB，资源合计 ≤ 60MB。

打包后从「设置 → 主题 → 导入主题」安装。完整规范见
[`docs/THEME_SPEC.md`](../../../THEME_SPEC.md)。

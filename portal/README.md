# Kiwi 产品门户

静态产品页，无构建步骤、无外部依赖，可直接托管到 GitHub Pages。

## 本地预览

```bash
python3 -m http.server 18475 --directory portal
```

打开 <http://localhost:18475>。

前端开发服务器也会把仓库根目录的 `portal/` 挂载到 `/portal/`：访问 <http://localhost:5173> 会自动跳转门户首页，应用本身仍可通过 `/kbs`、`/notes` 等路径访问。

## 部署到 GitHub Pages

仓库已包含 `.github/workflows/pages.yml`。首次启用：

1. 进入 GitHub 仓库 **Settings → Pages**；
2. 在 **Build and deployment → Source** 选择 **GitHub Actions**；
3. 推送到 `main`，或在 **Actions** 中手动运行 **Deploy portal to GitHub Pages**。

站点会发布到 `https://<username>.github.io/Kiwi/`。所有资源均使用相对路径，无需修改配置即可在子路径下运行。

## 结构

```text
index.html                  页面结构
404.html                    GitHub Pages 404 页面（自包含样式）
robots.txt / sitemap.xml    搜索引擎入口
assets/portal.css           设计系统与响应式样式
assets/portal.js            星图背景、滚动动效、界面切换、复制命令、Notebook 演示
assets/favicon.svg          站点图标
assets/og-image.png         社交分享封面（1200 × 630）
assets/screenshots/*.webp   产品截图（最长边 1600px，按页面需要压缩）
```

## 修改约定

- 不引入外部字体、CDN 或追踪脚本，保证内网与离线环境可用。
- 新增截图时转换为 WebP，更新 `index.html` 中的 `width` / `height`；学习闭环需要各阶段保持 16:10，切换时高度不跳动。
- 动效必须尊重 `prefers-reduced-motion`；新增交互需保留键盘可达性。
- 学习闭环使用 `setupShowcase({ auto })` 自动轮播：悬停、键盘聚焦、页面不可见或区块离开视口时暂停，减少动态偏好下不启用。
- 更新首页标题或主视觉后，同步重新生成 `assets/og-image.png`，并更新 `sitemap.xml` 的 `lastmod`。

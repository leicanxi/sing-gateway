# AGENTS.md

## 前端：音色广场（`web/voice-plaza/`）

动这里的 UI 之前，先读这两份官方资料：

- [`web/voice-plaza/DESIGN.md`](web/voice-plaza/DESIGN.md) — HeroUI v3 官方设计契约：语义色板、排版、4px 间距节奏、圆角刻度（`rounded-3xl` = 24px）、阴影层级（卡片 `shadow-surface` / 浮层 `shadow-overlay`）、按钮 variant 语义，以及 Do / Don't。
- [`web/voice-plaza/AGENTS.md`](web/voice-plaza/AGENTS.md) — HeroUI 组件文档索引，指向 `web/voice-plaza/.heroui-docs/react/`（1692 个官方 mdx，含各组件 API 表与示例代码）。

`.heroui-docs/` 是本地下载的文档，已 gitignore。缺文件时在 `web/voice-plaza/` 下重新拉取：

```bash
npx heroui-cli@latest agents-md --react --output AGENTS.md
npx heroui-cli@latest design-md --react --output DESIGN.md
```

`heroui info <component>` / `heroui doc <component>` 走 `raw.githubusercontent.com`，本机 DNS 解析不了，用本地文档替代。

文档只覆盖「组件怎么用」和「设计该长什么样」。布局问题（窄屏溢出、吸顶高度、弹窗宽度）仍要在浏览器里量：`pnpm dev` 后看 `web/voice-plaza/README.md` 的说明。

## 后端

Python 包在 `src/sing_gateway/`，运行、环境变量与客户端接入见根 `README.md`。

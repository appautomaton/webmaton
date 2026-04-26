# Webmaton

[English](README.md) | 中文

> **致谢**
>
> 项目首发于 [linux.do](https://linux.do)。感谢社区的鼎力支持与宝贵反馈。

> [!IMPORTANT]
> 运行这些 Skill 需要 [**uv**](https://docs.astral.sh/uv/)。所有脚本均使用 [PEP 723](https://peps.python.org/pep-0723/) 内联元数据声明依赖，通过 `uv run` 自动解析。无需手动维护 `requirements.txt`。

**Webmaton** 是一套精心策划的高保真 Agent Skill 工具包，专注网页工作场景——深度研究、页面捕获与浏览器自动化。每个 Skill 自成一体、文档完备，可零摩擦接入任意 Agent 运行时（OpenCode、Claude、Codex 等）。

名称由 **web** 与 **automaton** 组合而成——让 AI Agent 像人类研究员一样阅读、观察并与网页交互。

---

## Skill 清单

| Skill | 功能 | 适用场景 |
|---|---|---|
| [`agentic-search`](skills/agentic-search/) | 以 Grok 为主的深度研究，含引证溯源、Tavily/Firecrawl 补充发现、原文摘录与可重排会话。 | 需要来源而非摘要的研究任务。 |
| [`html-to-markdown`](skills/html-to-markdown/) | 浏览器捕获 + 确定性 HTML→Markdown 转换，附带元数据、链接/图片清单与质量信号。 | 将 JS 渲染页面或静态文章转为整洁的结构化 Markdown。 |
| [`nodriver-browser`](skills/nodriver-browser/) | 基于 nodriver 的持久 Chrome/Chromium 自动化——点击、输入、截图、DOM 快照与多步流程。 | 需要像人类一样操作页面（登录、按钮、表单）。 |

---

## 设计原则

1. **脚本自包含** — 所有脚本使用 [PEP 723](https://peps.python.org/pep-0723/) 内联元数据，依赖通过 `uv run` 自动解析，无需 `requirements.txt`。
2. **可组合会话** — `agentic-search` 将研究会话持久化到磁盘，支持跨多次调用进行搜索、摘录、重排来源与组合发现。
3. **浏览器优先的保真度** — 遇到需要 JavaScript、登录态或 DOM 交互的页面时，直接启动真实浏览器（Chrome → Chromium → Playwright 兜底）；静态内容则直接抓取，不过度设计。
4. **默认可移植** — Skill 支持符号链接，与运行时无关。放入 `~/.codex/skills/`、`~/.claude/skills/` 或任意 Agent 工作区即可使用。

---

## 快速开始

克隆仓库，将需要的 Skill 软链接到 Agent 的 Skill 目录：

```bash
git clone <repo-url> webmaton
cd webmaton

# 示例：让 Claude 可用 agentic-search
ln -s "$(pwd)/skills/agentic-search" ~/.claude/skills/agentic-search
```

每个 Skill 的 `SKILL.md` 包含调用示例、参考文档与故障排查指南。

---

## 环境要求

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)（用于 `uv run` 执行脚本）
- 所用服务商的 API 密钥：
  - `GROK_API_KEY` / `GROK_API_URL` — Grok 搜索与抓取
  - `TAVILY_API_KEY` — Tavily 搜索与站点映射
  - `FIRECRAWL_API_KEY` — Firecrawl 兜底抓取

---

## 底层工具

`html-to-markdown` 使用 [`markmaton`](https://github.com/appautomaton/markmaton) 做确定性的 HTML 转 Markdown；需要 JavaScript 渲染时由 `nodriver` 负责浏览器页面捕获。

---

## 许可证

MIT

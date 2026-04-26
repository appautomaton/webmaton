# Webmaton

English | [中文](README_zh.md)

> **Acknowledgement**
>
> Special thanks to LINUX.DO — originally published on [linux.do](https://linux.do). Thank you to the community for the incredible support and feedback.

> [!IMPORTANT]
> These skills require [**uv**](https://docs.astral.sh/uv/) to run. All scripts use [PEP 723](https://peps.python.org/pep-0723/) inline metadata — dependencies resolve automatically via `uv run`. No `requirements.txt` needed.

**Webmaton** is a curated toolkit of portable, high-fidelity agent skills for web work — deep research, page capture, and browser automation. Each skill is self-contained, documented, and designed to drop into any agent runtime (OpenCode, Claude, Codex, and others) with minimal setup.

The name is a portmanteau of **web** and **automaton** — tools that let AI agents see, read, and interact with the web the way a human researcher would.

---

## Skills

| Skill | What it does | Best for |
|---|---|---|
| [`agentic-search`](skills/agentic-search/) | Grok-primary deep research with grounded citations, Tavily/Firecrawl source discovery, verbatim extraction, and rerankable sessions. | Research tasks that need sources, not summaries. |
| [`html-to-markdown`](skills/html-to-markdown/) | Browser capture + deterministic HTML→Markdown conversion with metadata, link/image inventory, and quality signals. | Converting JS-heavy pages or static articles into clean, structured Markdown. |
| [`nodriver-browser`](skills/nodriver-browser/) | Persistent Chrome/Chromium automation via nodriver — clicks, typing, screenshots, DOM snapshots, and multi-step flows. | Anything that requires interacting with a page like a human (logins, buttons, forms). |

---

## Design principles

1. **Self-contained scripts** — Every script uses [PEP 723](https://peps.python.org/pep-0723/) inline metadata, so dependencies resolve automatically via `uv run`. No `requirements.txt` ceremony.
2. **Composable sessions** — `agentic-search` persists research sessions to disk, letting you search, extract quotes, rerank sources, and compose findings across multiple invocations.
3. **Browser-first fidelity** — When a page needs JavaScript, login state, or DOM interaction, we reach for a real browser (Chrome → Chromium → Playwright fallback). For static content, we fetch directly. No overkill.
4. **Portable by default** — Skills are symlink-friendly and runtime-agnostic. Drop them into `~/.codex/skills/`, `~/.claude/skills/`, or your agent workspace and they just work.

---

## Quick start

Clone the repository and symlink the skills you need into your agent's skill directory:

```bash
git clone <repo-url> webmaton
cd webmaton

# Example: make agentic-search available to Claude
ln -s "$(pwd)/skills/agentic-search" ~/.claude/skills/agentic-search
```

Each skill's `SKILL.md` contains invocation examples, reference docs, and failure-mode guidance.

---

## Requirements

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) (for `uv run` script execution)
- API keys for providers you plan to use:
  - `GROK_API_KEY` / `GROK_API_URL` — for Grok-powered search and fetch
  - `TAVILY_API_KEY` — for Tavily search and site mapping
  - `FIRECRAWL_API_KEY` — for Firecrawl fallback fetching

---

## Underlying tools

`html-to-markdown` uses [`markmaton`](https://github.com/appautomaton/markmaton) for deterministic HTML-to-Markdown conversion, with `nodriver` handling browser-rendered capture when JavaScript is needed.

---

## License

MIT

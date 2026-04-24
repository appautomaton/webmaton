# Search discipline

The methodology that turns `agentic_search` from "string in, string out" into actual research. This file is loaded only when composing or interpreting a research-grade query — not on every fetch.

## The two-pass model

**Pass 1 — Breadth-first.** Brainstorm at least 5 angles on the question before issuing any query. The literal phrasing of a user request is rarely the full intent. Examples of "angles":

- Direct factual: what is X?
- Comparative: how does X relate to Y, Z?
- Temporal: how has X changed recently?
- Authoritative: what do primary sources / standards bodies / academic literature say?
- Adversarial: what are critics / failure modes / known limitations?

Issue parallel queries across these angles. Use `--extra-sources` to fan out to Tavily/Firecrawl in addition to Grok when breadth matters more than the AI-reasoned answer alone.

**Pass 2 — Depth-first.** From the breadth pass, pick the **2+ most relevant angles** and dig deeper on those. Follow citations. Read primary sources via `agentic_fetch`. Resist the temptation to synthesize too early.

Only after both passes have run should you compose the answer.

## Citation contract

Every non-trivial claim in the final answer must be traceable to a source. The Grok prompt (passed by `agentic_search.py`) instructs the model to output citations alongside its answer; the script parses them out and returns them in the `sources` array.

Rules when presenting results to the user:
1. **No uncited claims on contested or time-sensitive points.** If you can't cite it, say "I couldn't find a source for this" rather than asserting.
2. **Prefer primary sources** (the actual paper, RFC, standards doc, official changelog) over secondary commentary.
3. **Authority hierarchy** (high → low): peer-reviewed academic > standards bodies > primary docs / official blogs > reputable journalism > Wikipedia > random blogs > forum posts > LLM speculation.
4. **One citation per claim** is the minimum; more is stronger. Multiple independent sources agreeing on a number/fact is much stronger than one.
5. **Quote when precision matters.** For definitions, version numbers, dates, statistics — use verbatim quotes from sources, not paraphrase.

## Time-context heuristic

`agentic_search.py` automatically injects a `[Current Time Context]` block into Grok's prompt when the query contains time-sensitive keywords. Triggers (case-insensitive):

- English: `current`, `now`, `today`, `tomorrow`, `yesterday`, `this week`, `last week`, `next week`, `this month`, `last month`, `next month`, `this year`, `last year`, `next year`, `latest`, `recent`, `recently`, `just now`, `real-time`, `realtime`, `up-to-date`
- Chinese: 当前, 现在, 今天, 明天, 昨天, 本周, 上周, 下周, 这周, 本月, 上月, 下月, 这个月, 今年, 去年, 明年, 最新, 最近, 近期, 刚刚, 刚才, 实时, 即时, 目前

If the query is implicitly time-sensitive but doesn't contain a trigger word (e.g., "Kubernetes deprecations"), explicitly add a temporal qualifier ("Kubernetes deprecations as of 2026") so the heuristic fires.

## When to use `--platform`

The `--platform` arg appends a platform-focus instruction to Grok's prompt. Use it when:

- The user asks about discussion/sentiment on a specific site (Twitter, Reddit, HN, GitHub).
- The user wants source code or repos → `--platform GitHub`.
- The user wants academic context → `--platform "arxiv.org, scholar.google.com"`.

Do NOT use `--platform` for general research; it narrows the search and can hurt breadth.

## When to use `--extra-sources`

Default is 0 (Grok only). Reason to add extra sources:

- You want **raw URLs** Claude can then `agentic_fetch` for verbatim content. Grok's answer is reasoned-over; the extra sources are the underlying evidence.
- You want a **second opinion** — a non-LLM list of top-ranked results to sanity-check Grok's framing.
- You need **breadth** beyond what one model returns.

Recommended values:
- `--extra-sources 0` (default): fast, cheapest, Grok-reasoned answer with whatever citations Grok provides.
- `--extra-sources 4-6`: balanced; gives you a handful of supplementary URLs to inspect.
- `--extra-sources 10+`: research mode; lots of sources, slower, only when you really need breadth.

If both Tavily and Firecrawl keys are set, Firecrawl takes 100% of N (Tavily gets 0) — Firecrawl is prioritised because it returns more raw URLs per call. If only one key is set, all extras go to that provider.

## Output style for the final answer

When summarizing results back to the user (after running `agentic_search`):

1. **Lead with the probable answer.** Don't bury the conclusion in caveats.
2. **Define jargon** in plain language inline or in a short trailing glossary.
3. **Cite every sentence** that makes a factual claim. Inline `[1]`, `[2]` style with a sources list at the end works well.
4. **Distinguish what the sources say from your synthesis.** "Source X reports Y" vs. "Putting these together, it looks like Z."
5. **Use real-world analogies** for technical concepts after the precise definition.
6. **Be direct.** Skip "Hope this helps!" and "Let me know if you'd like more detail." If there's an obvious follow-up the user might want, just do it next time, don't ask.

## Anti-patterns

- **Issuing the literal user query unchanged** when a slight reformulation would be clearer. Always think "what would I actually search for?" before calling the script.
- **Trusting a single source on a contested claim.** Get corroboration.
- **Summarizing too early** — running one search, then writing the answer. The two-pass model exists for a reason.
- **Ignoring `sources_count: 0`** in the script output. If Grok returned no sources, either the query was malformed or the model fell back to its training data — flag this to the user, don't pretend the answer is grounded.
- **Asking for permission** to do follow-up searches when the user clearly wants the research done. If breadth needs more passes, do them.

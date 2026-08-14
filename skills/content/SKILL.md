---
name: content-pipeline
description: Multi-stage content generation (research → outline → compose) producing an enterprise-grade article that beats competitors on depth, structure, and voice. Use whenever content must be researched against real competitors and composed with a coherent, opinionated voice rather than flat single-shot output.
---

# Content Pipeline

Generate a competitor-backed article in three gated stages. Each stage is a
deterministic worker task type; nothing about the pipeline is improvised by a
human or a free-form agent. The output is a typed block structure composed
one block at a time so the article holds a single coherent voice.

## When to use
- A target keyword needs an article that genuinely outranks competitor pages.
- The brief demands information-dense, structured content (tables, charts,
  callouts, steps) rather than a wall of prose.
- You want a checkpoint where a human inspects the plan **before** paying for
  the expensive compose stage.

## The three stages (strictly gated)

```
content_research ──> content_outline ──> [human inspects] ──> content_compose
   (1 LLM call)      (1 LLM call)          /dev/tasks,...       (1 LLM call per block)
```

| Stage | Task type | LLM calls | Cost | Gate |
|-------|-----------|-----------|------|------|
| 1. Research | `content_research` | 1 (quality) | cheap | fetches + analysis |
| 2. Outline | `content_outline` | 1 (quality) | cheap | JSON block validator |
| 3. Compose | `content_compose` | 1 **per** content block | expensive | **human inspects outline first** |

- **Research → Outline** DO auto-chain (both cheap, always sequential).
- **Outline → Compose** DO NOT auto-chain. Compose runs on demand by
  `content_item_id`. This is the deliberate spend gate: a bad research or
  outline pass is re-run before funding the ~8-14 quality calls that compose
  needs.

## Stage 1 — content_research
Params: `{"target_keyword": str, "competitor_urls": [str], "keyword_id": ?int}`

Deterministic work (stdlib only), the LLM reads the markup:
1. For each URL: fetch, strip `<script>/<style>`, collapse whitespace, truncate
   to ~6000 chars, record a raw word count.
2. One `call_zen` (quality) reads all cleaned sources and returns:
   ```json
   {
     "elements": [{"url", "headings": [], "elements_used": [], "word_count", "freshness"}],
     "strongest": [{"element", "from_url", "why"}],
     "weaknesses": ["2-3 things competitors do badly"],
     "gaps": [{"gap", "opportunity"}],
     "element_strategy": "one short instr: which block types to lead with"
   }
   ```
Stored in `content_research`. `element_strategy` is the decisive field: it is
the "if they use a table, we use a chart" choice, made **once** with all
competitors in view, then handed to the outliner so it executes a strategy
rather than guesses structure from the keyword.

## Stage 2 — content_outline
Params: `{"research_id": int, "brand_id": ?int, "title": ?str}`

One `call_zen` (quality) translates the research into a typed block array. The
prompt instructs it to: act on `element_strategy` verbatim, cover the `gaps`
early, beat the `weaknesses`, open with an `intro` hook, include a
`key_takeaways` box near the top, size block count to the competitors' average
word count (more thorough — but no filler), and use `image_slot` at most 2-3.

Validated by the outline validator: any number/order of any block type (no
template, no minimum per type); unknown type / missing brief / bad `chart_type`
/ `image_slot` without `alt`+`prompt` / `faq` without `answer_pointer` are
rejected; `intro` is auto-forced `keyword_target: true` and at least one block
must target the keyword. Stored as `content_items(structured={"blocks":[...]},
status='outline')`, returning `content_item_id`.

## Stage 3 — content_compose
Params: `{"content_item_id": int, "target_keyword": str, "model": ?str}`

- Runs **on demand**, only after the human approves the outline.
- One `call_zen` (quality) **per content block**. `heading` and `image_slot`
  are pure carries (already fully specified by the outline) and skip the LLM.
- Every block call receives: the full outline + its position + a **running
  2-3 sentence summary of prior blocks** (each call returns a `summary` key
  consumed by the next call), so the article is one coherent piece.
- Each block type has its own required return contract (a table asks for
  columns + rows, a chart for a titled data series, a callout for one stat +
  label) — never a generic "write this section".
- The **Voice rules are injected into every intro/prose/faq call**.
- Validator rejects: placeholders, meta-language, uniform paragraph lengths,
  keyword-stuffing.
- Assembled into `content_items.content_blocks` (jsonb), status → `draft`,
  plus a plain markdown `body`.

### Keyword contract
- Blocks flagged `keyword_target: true` MUST contain the target keyword verbatim,
  placed naturally (no stuffing).
- Blocks not flagged read naturally without forcing it.
- Validator enforces: keyword appears in the **intro** AND at least one other
  flagged block, and appears no more than ~**once per 150 words** overall
  (density ceiling). Natural placement, not saturation.

## Block schema
The outliner emits typed blocks; compose fills them. Ordering and count are
fully dynamic — any number of any type, freely repeated and interleaved.

| type | outliner payload | composer returns |
|------|------------------|------------------|
| `intro` | `brief` (hook intent; auto `keyword_target:true`) | `heading` |
| `heading` | `brief` (the H2/H3 text) | `heading` (carried) |
| `prose` | `brief`, `keyword_target?` | `markdown` |
| `key_takeaways` | `brief` | `points[]` |
| `steps` | `brief` | `steps[]` |
| `table` | `brief` (columns/compare) | `columns[]`, `rows[][]` (first row = header) |
| `chart` | `brief`, `chart_type` (`bar\|line\|pie`) | `data_series{labels[],values[]}`, `chart_type`, `title` |
| `callout` | `brief` | `stat`, `label` |
| `image_slot` | `brief`, `alt`, `prompt` | `alt`, `prompt` (carried) |
| `faq` | `brief`, `answer_pointer` | `answer` |

## Data model
- `content_research`: `id, task_id, keyword_id, target_keyword, competitors
  jsonb, elements jsonb, strongest jsonb, weaknesses jsonb, gaps jsonb,
  element_strategy text, created_at`
- `content_items`: `structured jsonb` holds the outline (`{"blocks":[...]}`);
  `content_blocks jsonb` holds the composed blocks; `body` is the plain render;
  `status` = `outline` → `draft` → (`approved` via the normal content gate).
- No other schema. Outline and composed output reuse `content_items`.

## Voice — the reusable soul
*Injected into every `intro`/`prose`/`faq` call. This is the difference between
generic filler and an article worth ranking. Recycle it verbatim everywhere you
generate marketing prose.*

### The rules
1. **Write like an expert to a knowledgeable peer.** Confident, direct,
   opinionated. Not a textbook, not a sales pitch.
2. **Vary sentence length sharply.** Mix short, punchy sentences (4-8 words)
   with longer multi-clause ones (20-30). No two consecutive sentences with the
   same shape.
3. **One idea per paragraph.** If a paragraph carries two ideas, split it.
4. **Prefer concrete specifics over abstractions.** Real numbers, named things,
   tangible steps. Replace vague phrasing with specifics.
5. **Banned connectors & filler:** never open a sentence with *in conclusion,
   moreover, furthermore, it's worth noting, however, in today's world, in
   today's digital age, as we all know*. Delete, don't substitute.
6. **Never mention AI.** No "as an AI", model self-reference, training data, or
   knowledge limits. You are the author, period.
7. **Take a real point of view.** Assert a stance, make a recommendation, call
   out what's overrated. Neutral Wikipedia tone is forbidden.

### Worked before/after (concrete beats abstract)
Weak — generic, abstract, no stakes:
> There are many factors to consider when choosing a clinic.

Strong — specific, opinionated, names the stakes:
> Three things decide whether a clinic keeps a patient: wait time, follow-up,
> and whether the front desk remembers their name.

Weak — hedged, filler-opened:
> In today's fast-paced world, businesses need to ensure they have the right
> tools in place to succeed.

Strong — direct, concrete:
> A clinic that books your next visit before you leave the exam room keeps 23%
> more patients. Ours does both in one thread.

Weak — uniform, passive:
> It is important to consider quality and cost when evaluating a provider.
> Reliability is also a key factor. Communication matters as well.

Strong — varied rhythm, one idea per paragraph, opinionated:
> Quality is table stakes. The real metric is whether they pick up the phone.
> We did the math: returning same-day answer time alone added nine reviews last
> quarter.

Weak — vague "we help you":
> We help businesses improve their customer experience and grow their revenue.

Strong — specific mechanism + payoff:
> Our referral loop turns a one-time patient into a repeat visitor: automated
> follow-up, a recall reminder, and a thank-you that mentions their name.

### Pattern to teach
- **Replace "many / several / various" with the actual count.** If you can't
  say "three", you haven't thought about it yet.
- **Put the payoff in the headline of the sentence.** The takeaway first, the
  mechanism after.
- **One implication per sentence** — then connect them, don't stack synonyms.
- **Delete every sentence that starts with "It is important / We need to / It's
  worth noting".** Start where the reader's decision is, not where your throat
  clearing ends.

## Running the pipeline (reproducible)
1. Insert a task row `type='content_research'` with research params, or use the
   dashboard's "Research + Outline" form.
2. Worker runs research → stores `content_research` → returns `research_id`.
3. `content_outline` runs next (auto-chained) → stores outline → returns
   `content_item_id`.
4. **Human inspects the outline** (blocks + briefs) on the dashboard.
5. On approval, insert `type='content_compose'` with `content_item_id` and
   `target_keyword` — or click "Compose this outline".
6. Worker composes block-by-block → validates → `content_blocks` + `body`,
   status `draft`.
7. The draft proceeds through the normal content gate: `orch approval request
   --type content` before anything public.

Each LLM call is token/cost-tracked via the existing `call_zen` path.

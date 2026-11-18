---
name: amazon-case-study-builder
description: Build a full WaitHowMuch-style case study of any Amazon brand or ASIN - a profit headline, revenue/profit/ad-spend chart over time with a timeline, sales breakdown with product photos, margin waterfall, selling methods, advertising and keywords, outside traffic, listing and reviews, brand owner, valuation and a written analysis, every figure labelled given/derived/assumed with its source - delivered as one self-contained HTML page shown to the user (an artifact in Claude apps, a local file in CLI agents), never published. Orchestrates the other WaitHowMuch skills. Use when the user asks for a case study, teardown, profile, deep dive or full breakdown of an Amazon brand or competitor, "everything about brand X", or "make me a WaitHowMuch page for X". Amazon US.
---

# Amazon case-study builder (WaitHowMuch)

A case study is one brand **at one month**, read from public data: what it sells, what it keeps,
where its demand comes from and what it might be worth. This skill runs the sibling WaitHowMuch skills
in a fixed order, assembles one JSON (`scripts/schema.md`) and renders it with `scripts/render.py`, so
every case study looks the same. Each figure says whether it is **given** (the user's number),
**derived** (computed from a named source) or **assumed** (a default to replace), plus **inferred** for
answers only the owner can confirm. **Never invent a figure.** A section the keys can't fill is left out
with a one-line "not available without X" note.

## Keys and mode

Helper: `scripts/whm.py` (Python 3, no dependencies). It never prints keys; don't echo, log or paste one.
Start every run with:

```bash
python3 scripts/whm.py mode     # keys present, and section by section what they make possible
```

| mode | used when | gives |
|---|---|---|
| WaitHowMuch | `WHM_API_KEY` set | researched brands in full (series, profit, ads, valuation, traffic); others need Option A until the general routes ship |
| Own keys | `KEEPA_API_KEY` (required for revenue), + `JUNGLESCOUT_API_KEY` or `DATAFORSEO_LOGIN`/`DATAFORSEO_PASSWORD`, optional `SIMILARWEB_API_KEY`, `KALODATA_API_KEY` | every section the keys cover |
| none | neither | `no_keys`: tell the user briefly to set `WHM_API_KEY` **or** `KEEPA_API_KEY` (+ the others), then stop |

Claude Code: `/plugin` > waithowmuch > Configure options. Setup: https://github.com/ggballas/waithowmuch-skills#data-providers

**Sibling skills.** The commands below live in the sibling folders: `S=<this skill's folder>/..`, so
`python3 $S/amazon-revenue-sales/scripts/whm.py …`. They ship together in the plugin. If one isn't
installed, that section is "not available without the `<skill>` skill"; don't reimplement it.

**Cost first.** Tell the user the expected spend before running (from `mode` and the README): about
40-90 Keepa tokens, ~29 Jungle Scout requests, ~$0.05 DataForSEO, ~1.5 Kalodata credits. Pass
`--max`, `--keywords`, `--max-requests` to keep inside what they allow.

Usage count: each `whm.py` command sends one anonymous GET to `api.waithowmuch.com/health` with only the skill, version, command name and key mode (whm/own/none), never arguments, inputs or keys. `WHM_USAGE=0` turns it off.

## 0. Inputs - ask once, in one message, only for what's missing

- The brand (as spelled on Amazon), or an ASIN / amazon.com link of its best seller.
- **Cost of goods.** A factory price per unit, a supplier's quote, or Alibaba listing price ranges.
  Public data cannot supply this. If the user has none, say the margin, profit, headline profit and
  valuation need it; offer to continue without them (revenue headline, waterfall stops at "before cost
  of goods") or with a number they pick (then `given`).
- Optional: their own ad spend or margin if it's their brand (`given`), the brand's website.

WHM mode: `python3 scripts/whm.py lookup "<brand or ASIN>"`. A researched brand → read
`python3 scripts/whm.py api "/v1/businesses/<slug>"` and build from it (series, profit, ads, valuation are
its stamped figures, `derived`, source "WaitHowMuch case study"), and link `caseStudy`.

## 1. Run order - one section at a time, each command once

| # | for | skill · command | needs |
|---|---|---|---|
| 1 | catalogue, series, chart, breakdown, cards | `amazon-revenue-sales` · `brand "<brand>" --max 25` (or `store <ASIN>` when the brand string is split) | Keepa ~11+N |
| 2 | listing, launch, price/BSR/rating history, buy box, images, coupons | `amazon-listing-teardown` · `listing <best-seller ASIN>`; `page <ASIN>` for badges, premium A+ | Keepa 5; page free |
| 3 | product photos for the breakdown | `scripts/whm.py photos <ASIN>,<ASIN>,…` (top 3-6 sellers) | Keepa 1/ASIN |
| 4 | reviews | `amazon-review-insights` · `page <ASIN>` (+ `ratings <ASIN>` for the trend) | free; Keepa 2 |
| 5 | top keywords | `amazon-top-organic-keywords` · `keywords <ASIN> --pages 1` | JS 1 / DFS ~$0.02 |
| 6 | ad spend band, strategy, paid keywords | `amazon-adspend-estimator` · `adspend <ASIN> --asins <top ASINs> --brand "<as JS spells it>" --revenue <snapshot revenue>` | JS ~3+keywords |
| 7 | landed cost of goods | `amazon-cogs-estimator` · `quotes …` (if ranges), `duty "<words>"` → pick the line, `landed --unit-cost X --qty 500 --asin <ASIN> --hts <code>` | free (+1 Keepa) |
| 8 | fees + waterfall | `amazon-profit-calculator` · `pnl <best seller> --landed <7> --landed-tier derived` for the FBA fee and referral %, then the brand month: `pnl --price P --units <snapshot units> --fba-fee F --referral-pct R --landed L --landed-tier derived --ads-band low,central,high` | Keepa 1; then no key |
| 9 | outside traffic | `brand-outside-traffic` · `site <domain>`, `traffic <domain>`, `brand-search "<brand>" --also "<product>,<parent brand>"`, `youtube <@handle>`, `spikes <best seller>` | free; DFS ~$0.012 each; Similarweb; Keepa 1 |
| 10 | TikTok Shop | `tiktok-shop-research` · `shops "<brand>"`, then `shop <id> --months 12` if found | Kalodata ~1.5 credits |
| 11 | valuation | `amazon-brand-valuation` · `value --profit-ttm <low> --profit-ttm-high <high> --profit-tier derived --selling-since … --reviews … --rating … --peak-month-pct … --feedback-pct … --us-only` + answers `--method --catalog --diff-* --brand-registry --answers-tier inferred` | no key |
| 12 | similar case studies | `amazon-case-studies` · `api "/v1/businesses/<slug>/similar?limit=6"` or a `/v1/businesses?niche=…` filter | WHM only (Keepa `niche` scan is revenue-only: label it so) |

Rules while running:

- **One model.** The snapshot month is the last whole month of the series. Margin and ad rate come from
  that month's waterfall (step 8). Profit and ad-spend series = each month's revenue × that margin / ad
  rate, the research's convention; say so in `series.note`. Trailing-twelve profit = Σ revenue × margin
  (low and high ends) → step 11. Under 12 months of series: no valuation, say why.
- The ad band is for the **brand** (all top ASINs in `--asins`), so pass it to the brand-month `pnl`,
  not the single-ASIN one. Report the estimator's `strategy.label` as is, and read its `gaps`: a brand
  term that also matches someone else's product (e.g. "songbird ocarina") goes in the Advertising prose.
- On an error, follow that skill's Errors section once (`page_blocked`: read the page in a browser tool
  if you have one, else leave those fields "not read"; `keepa_tokens_low`: give `waitSec`). Never loop.
- Keep each command's JSON in the working dir: the HTML is built from those files, not from memory.

## 2. What goes where (and when a section is left out)

| section | from | leave out with a note when |
|---|---|---|
| Headline + cards | 1, 8 | no series → no case study (needs `KEEPA_API_KEY` or a researched brand): stop |
| Overview photos + chart | 1, 3 | photos: no Keepa/WHM → main image from step 2/`page` only |
| Timeline (≥4 dated events) | 2 `launch`, `historySummary.coupons`, 9 `spikes`, series highs | fewer than 4 events |
| Revenue + sales breakdown | 1 `history`, `products` + 3 | — |
| How it sells | 2 `offers`, 9 `site`, 10 | each method `yes`/`no`/`unchecked`; "unchecked" is never "no" |
| Margin breakdown | 7, 8 | no cost of goods → "not available without a factory price or supplier quote"; no ad band → profit stays empty |
| Advertising | 5, 6 | no JS/DFS → "not available without JUNGLESCOUT_API_KEY or DATAFORSEO_LOGIN + DATAFORSEO_PASSWORD"; DFS only → footprint, no dollar figure |
| Socials and traffic | 9 | Similarweb missing → its row says "not available without SIMILARWEB_API_KEY" |
| TikTok Shop | 10 | "not available without KALODATA_API_KEY"; a shop missing from the top-10 rank is not zero |
| Listing + reviews | 2, 4 | — |
| Brand owner | 2 `offers.buyBoxSeller`, `amazon-revenue-sales store` | — |
| Valuation | 11 | under 12 months, or no profit |
| What it adds up to | everything above | never |
| Similar case studies | 12 | "not available without WHM_API_KEY" |

## 3. Copy rules (from WaitHowMuch's research)

- **Headline = profit**, in an **observational voice**: "How A $29.99 Singing Bird Wine Pourer Clears
  $19K/Month In Profit", never "I/We built…". Nobody at the business spoke to us. Title 6-12 words, title
  case, no colon, a specific noun with the price it usually sells at, and the figure **exactly as the
  profit card renders it** (`render.py` prints `$19K` for 18,984; it warns on a mismatch). No cost model
  at all → revenue headline, `figureBasis: "revenue"`.
- **Subtitle** 25-45 words: the constraint, what they did about it, what it produced. Its subject is the
  business, not Amazon or the category: if it would stay true pasted onto a competitor, rewrite it. Never
  open with the brand name; never quote an `assumed` figure (a profit resting on one may headline, the
  plug stays labelled on the margin table).
- One freeze date: say "Read <month>" once (the renderer does); dates in prose only when the date is the
  fact. Revenue is a floor (badge low end, unbadged = 0), profit a ceiling (returns, storage, overhead
  not counted): once, in the Revenue callout and the figures table.
- Prose reports what the data shows; no "smartly", no guesses about the owner's intent. Valuation
  answers are inferences, named as the first things to put to the owner. Close the valuation with "An
  estimate from public data, not an appraisal or financial advice."
- Freight from Freightos is credited: set `margin.cogs.freightos: true`.
- `figures`: one row per figure on the page that matters (revenue, each cost line, ad band, profit,
  valuation, traffic, reviews), with tier and source. `sources`: each provider with date and cost;
  `spend`: what this run cost.
- Links: Amazon listings, the seller, the brand's site and socials. Link waithowmuch.com only for a
  researched brand or similar case studies; the renderer adds the UTM tags itself.

## 4. Output - one HTML file, shown, never published

```bash
python3 scripts/render.py case-study-<brand-slug>.json -o case-study-<brand-slug>.html
```

It prints `written`, `sections` and `warnings`. Fix every warning (tier, source, headline parity, voice)
and re-render. The file is self-contained: inline CSS, inline SVG charts, no scripts; product photos load
from Amazon's image CDN; footer "Built with WaitHowMuch skills" links the repo.

- **Claude apps (claude.ai, desktop, Cowork):** show the HTML to the user as an artifact (the file's
  content as an HTML artifact, or attach the file). Do not publish, share or upload it anywhere.
- **CLI agents (Claude Code, Codex, Cursor…):** save both files in the working directory and print the
  absolute path of the HTML. Don't open a browser or host it unless asked.

Then, in chat, five lines at most: the headline, revenue and profit for the month, the sections left out
and why, what this run spent, and the assumed lines that would move profit most.

## Errors

- `no_keys`: see Keys. A sibling's `whm_route_not_live`: re-run it with own keys if `mode` lists them,
  else leave its section out with the note. `keepa_tokens_low`, `js_forbidden` (Jungle Scout overage
  cap), `dataforseo_balance_low`, `kalodata_credits_low`: say which, skip that section, carry on.
- `under_12_months` (valuation): no valuation section; the note says when the twelfth month closes.
- `render.py` exit 4 `bad_input`: the JSON is malformed or lacks `brand` / `snapshotMonth`.

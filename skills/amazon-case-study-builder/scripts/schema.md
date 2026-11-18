# Case-study JSON (schema version 1)

`render.py` reads one JSON object and writes one self-contained HTML file. Every field is optional
except `brand` and `snapshotMonth`. Leave a section out when there is nothing to put in it, and say why in
`notAvailable`; never pad one. Money is plain US dollars (numbers, not strings), percentages are numbers
(`52.75`, not `0.5275`), months are `YYYY-MM`, dates `YYYY-MM-DD`.

**Tiers.** Every figure the page shows carries `tier`, one of:

| tier | meaning |
|---|---|
| `given` | a number the user supplied (their factory price, a supplier quote they pasted, their own profit) |
| `derived` | computed from a named source (Keepa badge × price, Amazon's fee, a Freightos rate, the Jungle Scout ad model) |
| `assumed` | a default put in so a sum completes (20% China duty add-on, $0 returns). Never quoted in the headline |
| `inferred` | read from the public record as an answer only the owner can confirm (valuation answers, private label) |

`render.py` warns on any other tier, on a `given`/`derived` row in `figures` without a `source`, on a
headline whose figure differs from its card, and on first person in the headline.

## Top level

```jsonc
{
  "schemaVersion": 1,
  "brand": "Songbird Specialties",                 // required
  "tagline": "A wine pourer that sings",           // 2-6 words, no figures
  "eyebrow": "Home & Kitchen · Wine pourers · Amazon US",
  "snapshotMonth": "2026-10",                      // required: the ONE month the cards and the title read
  "builtAt": "2026-11-17",
  "headline": {
    "title": "How A $29.99 Singing Bird Wine Pourer Clears $19K/Month In Profit",
    "subtitle": "25-45 words, observational: constraint, what they did, what it produced.",
    "figureBasis": "profit"                        // or "revenue" when there is no cost model at all
  },
  "intro": "One or two sentences on what the business is. No figures.",
  "photos": [{ "src": "https://m.media-amazon.com/images/I/….jpg", "alt": "…", "asin": "B0…", "caption": "Red · B0…" }],
  "cards": [                                       // the top row, all for snapshotMonth
    { "key": "revenue", "label": "Monthly revenue", "value": 35988, "high": 47864, "tier": "derived", "basis": "…" },
    { "key": "profit",  "label": "Monthly profit",  "value": 18984.2, "tier": "derived", "basis": "…" },
    { "key": "margin",  "label": "Margin", "value": 52.75, "format": "pct", "tier": "derived", "basis": "…" },
    { "key": "adSpend", "label": "Ad spend", "value": 190, "tier": "derived", "basis": "…" }
  ],                                               // format: usd (default, renders $25.2K) | pct | text
  "facts": [{ "label": "Product rating", "value": "4.6 from 187 ratings", "tier": "derived" }],
  "series": {                                      // the overview chart; one entry per month, null = no reading
    "months": ["2025-11", "…"], "revenue": [4498.5, …], "revenueHigh": [8907.03, …],
    "profit": [2373, …], "adSpend": [23.7, …], "note": "how the series was built"
  },
  "events": [                                      // the Timeline section AND the dots on the chart
    { "date": "2025-02-21", "tag": "Amazon", "what": "Four colours listed", "detail": "…", "tier": "derived" }
  ],                                               // tag: Amazon (filled dot) | Brand | Web | Advertising
  "sections": { … see below … },
  "notAvailable": [{ "section": "tiktok", "why": "not available without KALODATA_API_KEY" }],
  "figures": [{ "figure": "Make cost per unit", "value": "$2.87", "tier": "given", "source": "…", "note": "…" }],
  "links":   [{ "label": "totallybamboo.com", "href": "https://totallybamboo.com/" }],
  "sources": [{ "label": "Keepa: brand catalogue", "url": "https://keepa.com", "retrievedAt": "2026-11-17", "cost": "15 tokens" }],
  "spend":   { "Keepa": "27 tokens", "Jungle Scout": "9 requests", "DataForSEO": "$0.024" }
}
```

The card's rendering is the headline's: `usd_k` renders 18984.2 as `$19K` and 25197 as `$25.2K`, so the
title says `$19K/Month`. `notAvailable` keys that match a section print a one-line note where the section
would be; other keys print at the end.

## Sections, in page order

Each section may carry `title` (overrides the default heading), `lede` (one sentence), `prose` (list of
paragraphs) and `callout` (one boxed sentence), plus its own blocks:

| key | default heading | blocks |
|---|---|---|
| `timeline` | Timeline | uses top-level `events` |
| `revenue` | Revenue | `breakdown`: `{ items: [{ asin, title, image, units, unitsHigh, price, revenue }], month, partialOf, note }`. `partialOf` names what the rows are the largest of when they don't cover the whole series; `month` labels the reading when it isn't `snapshotMonth` |
| `selling` | How it sells | `methods`: `[{ group, label, status: "yes"\|"no"\|"unchecked", note }]`. Groups: Channels, Fulfilment, Supply, Programmes. Unchecked is not "no" |
| `margin` | Margin breakdown | `cogs`: `{ rows: [{ line, perUnit, tier, note }], total, note, freightos: true }` (the Freightos credit renders when `freightos` is true); `revenue`: `{ monthly, perUnit, tier, basis }`; `lines`: `[{ label, monthly, pct, perUnit, tier, basis, links: [{label, href}] }]` with costs NEGATIVE; `result`: `{ label, monthly, pct, perUnit, tier, note }` |
| `advertising` | Advertising | `strategy`: `{ label, points[] }` (label = the estimator's `strategy.label`, never your own); `band`: `{ low, central, high, ratePct, tier, basis }`; `topKeywords.rows`: `[{ keyword, searches, organicRank, sponsoredRank, bid }]`; `paidKeywords.rows`: `[{ keyword, searches, share (0-1), bid, spend }]`; `channels` |
| `traffic` | Socials and traffic | `channels`: `[{ label, value, tier, source, note, counted, href }]`; `brandSearch`: `{ keyword, months[], values[], note }` |
| `tiktok` | TikTok Shop | `channels` |
| `listing` | The listing | `rows`: `[{ label, value }]`; `strengths[]`, `weaknesses[]` |
| `reviews` | What buyers say | `histogram`: `{ "5": 81, … }` (%); `customersSay`; `aspects`: `[{ aspect, mentions, positive, negative, quote }]`; `sampleNote` |
| `owner` | Brand owner | `facts`: `[{ label, value, tier }]` |
| `valuation` | Valuation | `value`, `valueHigh`, `multiple`, `base`, `profitTtm`, `profitTtmHigh`, `profitTier`, `adjustments`: `[{ label, delta, tier }]`, `missingSignals[]`, `worst`, `best`, `disclaimer` |
| `analysis` | What it adds up to | `paragraphs[]`: the textual analysis |
| `similar` | Similar case studies | `items`: `[{ name, tagline, revenue, profit, marginPct, href }]` (waithowmuch.com links get UTM tags automatically) |

After the sections the page always renders "How each figure was built" (from `figures`), "Links and
sources", the spend line and the footer ("Built with WaitHowMuch skills", linking the repo).

## Safety

All text is HTML-escaped. Links must be `http(s)://` or `#anchor`; anything else is dropped with a
warning. Images must be `https://`. No scripts are emitted. Only links whose host is `waithowmuch.com`
get `utm_source=whm-skills&utm_medium=skill&utm_campaign=whm-skills&utm_content=amazon-case-study-builder`.

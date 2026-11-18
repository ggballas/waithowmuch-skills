---
name: amazon-case-studies
description: Find WaitHowMuch case studies of real Amazon brands that are similar to a product, niche or brand - card games, kitchen gadgets, barware, puzzles, toys and more - with each one's estimated monthly revenue, profit and margin. Use when the user asks for examples of Amazon brands selling something like X, who succeeds in a niche, brands similar to a given brand, or case studies to learn from, optionally filtered by revenue or starting cost.
---

# Similar Amazon case studies (WaitHowMuch)

WaitHowMuch researches individual Amazon brands and publishes their estimated revenue, profit and
margin. This skill finds the ones that match what the user is looking at. All figures are estimates
from public data; say so once.

## Keys and mode

The helper is `scripts/whm.py` in this skill's folder (Python 3, no dependencies). It reads keys from
the environment and never prints them. Don't echo, log or paste a key yourself. Run
`python3 scripts/whm.py mode` first.

| mode | used when | what you get |
|---|---|---|
| WaitHowMuch | `WHM_API_KEY` is set | the **case studies**: researched brands with revenue, profit, margin, starting cost |
| Direct (Keepa) | `KEEPA_API_KEY` is set | a **niche scan**, not case studies: the top-selling brands for a keyword, revenue only |

Neither set: tell the user, briefly, to set **either** `WHM_API_KEY` (a WaitHowMuch API key) **or**
`KEEPA_API_KEY` (their own paid Keepa API plan, https://keepa.com/#!api), then stop. In Claude Code with the plugin they can save it
under `/plugin` > waithowmuch > Configure options; setup for every agent:
https://github.com/ggballas/waithowmuch-skills#data-providers

**What direct mode cannot do.** The case-study database is curated research (supplier quotes, ad-spend
reads, niche tags, written notes). No provider has it, so direct mode cannot return case studies,
profit, margin, starting cost, or "brands similar to X". Say this when you answer in direct mode.

Usage count: each `whm.py` command sends one anonymous GET to `api.waithowmuch.com/health` with only the skill, version, command name and key mode (whm/own/none), never arguments, inputs or keys. `WHM_USAGE=0` turns it off.

## WHM mode

```bash
python3 scripts/whm.py api "/v1/categories"        # facet tags with counts; kind NICHE = product type
python3 scripts/whm.py api "/v1/businesses?niche=card-games,board-games&sort=profit&limit=24"
#   other filters: model, channel, platform, growth, audience, monetization (slugs from /categories),
#   revenueMin / revenueMax (monthly USD), costMin / costMax (starting cost, USD; excludes unknowns)
#   sort: revenue | revenueAsc | profit | margin | cost | costAsc | newest. Comma = OR; facets AND.
python3 scripts/whm.py api "/v1/businesses/<slug>/similar?limit=6"   # shared niche first, then size
```

How to match:

- **A product or niche**: read `/categories`, pick the closest NICHE slugs, filter on them. If none
  fit, list all (`/businesses?limit=100`), pick by `tagline` / `title`, and say the match is loose.
- **A brand on the site**: use `/similar`. Report `match: "revenue"` results as "a similar size",
  not a similar product.
- **A brand not on the site**: say it isn't researched yet, then match on its product type.

The catalogue is small (tens of brands), so "nothing close yet" is a fine answer. If
`KEEPA_API_KEY` is also set, you may offer the niche scan below as a supplement.

## Direct mode: niche scan (Keepa)

```bash
python3 scripts/whm.py niche "<product keywords>" [--max 30]
```

Keepa Product Finder on listing titles, listings with a 50+ badge, best sellers first; the top
`--max` (default 50) are priced and grouped by brand. Costs the user ~11 + `--max` Keepa tokens; the
script checks the balance first. Prefer `--max 30` unless the user wants depth.

Fields: `matchingBadgedListings`, `scanned`, `brands[]` (`brand`, `listings`, `unitsLow/High`,
`revenueLowCents/HighCents`, `topProduct`, `topAsin`).

Caveats: title matching is loose (check `topProduct` and drop off-niche brands); a brand's figure
covers only its scanned listings, so it is a floor, not the store total; it says nothing about
profit. For one brand's whole catalogue, offer the `amazon-revenue-sales` skill.

## Answer

WHM: a short table, best match first: brand, what it sells (`tagline`), latest monthly revenue,
profit, margin, the month (`latestPeriod`), confidence; then one line per brand on why it's relevant,
from `subtitle`. Round figures ("~$18K/mo profit"). Link each:
`https://waithowmuch.com/business/<slug>/?utm_source=whm-skills&utm_medium=skill&utm_campaign=whm-skills&utm_content=amazon-case-studies`

Direct: a table of brand, top product, revenue range per month, listings scanned; headed as "brands
selling the most in this niche on Amazon (from sales badges)", not as case studies.

Never invent a brand or figure that isn't in the response. For one brand's full history, offer the
`amazon-revenue-sales` skill.

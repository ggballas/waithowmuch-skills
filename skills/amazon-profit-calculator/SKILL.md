---
name: amazon-profit-calculator
description: Monthly profit and loss and margin for an Amazon product (ASIN or amazon.com URL), a brand, or the user's own product idea - revenue from Amazon's sales badge, Amazon referral and FBA fees, landed cost of goods, ad spend, returns and storage - laid out as a margin waterfall with every line marked given, derived or assumed, plus a trailing-twelve-month profit. Use when the user asks how much a listing or brand really makes after fees, its profit or margin, whether a product idea is profitable, "if I sell X at $Y with a $Z unit cost, what's left", or for an FBA profit calculation. Amazon US only.
---

# Amazon profit calculator (WaitHowMuch)

A monthly P&L laid out like a WaitHowMuch case study's margin breakdown: revenue first, then each
cost line, then what's left. **It's an estimate, not the seller's books.** Every line is labelled
**given** (the user's number), **derived** (from a named source) or **assumed** (a default to
replace). Say that once in the answer.

- **Revenue** is Amazon's "N+ bought in past month" badge × today's price. It uses the badge's low
  end, so it's a **floor**. Listings without a badge (under ~50 a month) count as zero.
- **Returns and storage** are $0 unless the user gives a figure, the same as in the research, so
  **profit is a ceiling**. Overhead, staff and software aren't counted either.

## Keys and mode

The helper is `scripts/whm.py` (Python 3, no dependencies). It reads keys from the environment and
never prints them, so never echo, log or paste a key. `python3 scripts/whm.py mode` shows which keys
are set.

| mode | used when | what it serves |
|---|---|---|
| WaitHowMuch | `WHM_API_KEY` set | ASIN: this month's price, units and fees. A brand WaitHowMuch has researched: its profit, ad spend and trailing-twelve profit |
| Direct | `KEEPA_API_KEY` set | an ASIN with its monthly series (1 token), or any brand (~11 + N tokens) |
| none | your own numbers | `pnl --price --units --fba-fee` needs no key |

If both keys are set, WHM answers researched brands and Keepa covers the rest. If neither is set and
the user named an ASIN or a brand, you get `no_keys`. Tell them briefly to set **either**
`WHM_API_KEY` **or** `KEEPA_API_KEY` (their own paid Keepa plan, https://keepa.com/#!api), then stop.
In Claude Code they can set it under `/plugin` > waithowmuch > Configure options. Setup for every
agent: https://github.com/ggballas/waithowmuch-skills#data-providers

Usage count: each `whm.py` command sends one anonymous GET to `api.waithowmuch.com/health` with only the skill, version, command name and key mode (whm/own/none), never arguments, inputs or keys. `WHM_USAGE=0` turns it off.

## 1. Gather the cost inputs first, without guessing

- **Cost of goods.** Pass `--landed X --landed-tier derived` with the landed cost from the
  `amazon-cogs-estimator` skill (run it if it's available), or `--landed` with the user's own
  figure. You can also pass `--unit-cost X` (the factory price): the helper then builds a quick
  landed cost from freight (the listing's package volume × a stored Freightos LCL rate), duty (20%,
  assumed for China) and $0.30 inbound placement. For a brand, use `--cogs-pct` or a blended
  `--landed`. With no cost of goods at all, the helper doesn't invent one: the line is listed in
  `missing`.
- **Advertising.** Run the **`amazon-adspend-estimator`** skill on the same ASIN or brand and pass its
  monthly band as `--ads-band low,central,high`. Don't model ads yourself. If that skill isn't
  available, use the user's figure (`--ads-monthly`, `--ads-pct`). For a new launch you can pass
  `--ads-pct 10 --ads-tier assumed`, but say it's assumed (established brands often run 3-8%). With
  no ad figure, the line is listed in `missing` and profit stays empty.
- **Optional:** `--returns-pct`, `--storage-monthly` or `--storage-per-unit`. Overrides:
  `--price`, `--units`, `--fba-fee`, `--referral-pct`.

Ask for all of these in one message, and only for what's missing.

## 2. Run it

```bash
python3 scripts/whm.py pnl <ASIN or amazon.com URL> --landed 3.40 --landed-tier derived --ads-band 400,700,1100
python3 scripts/whm.py pnl --brand "<brand as on Amazon>" [--max 50] --cogs-pct 18 --ads-band 2000,3500,5000
python3 scripts/whm.py pnl --price 24.99 --units 300 --fba-fee 5.20 --unit-cost 3 --ads-pct 10 --ads-tier assumed
```

- **A product idea with no ASIN:** take the FBA fee from a similar listing (`pnl <its ASIN>`, read
  `FBA fulfilment`). Otherwise the user can get it from Amazon's revenue calculator. Rough FBA fees:
  small standard ~$3.50, large standard up to 1 lb ~$4.75, 1-2 lb ~$5.75, 2-3 lb ~$6.75. Never guess
  for heavier or oversize items.
- **Brands:** before a large `--max`, tell the user the token cost. `capped: true` means more badged
  listings exist than were priced, so revenue is a floor.

**Output.** `floor` is the waterfall at the badge's low end. `high` is the same at the high end.
Each entry in `lines` has `monthly` (costs are negative), `pctOfRevenue`, `perUnit`, `tier` and
`basis`. `floor` also carries `profit`, `marginPct` and `marginBeforeAdsPct` (you can pass this to
amazon-adspend-estimator's `--margin-pct`). With an ad band, `profitAcrossAdsBand` gives profit at
the band's low and high. The rest:

- `missing` and `next` list what to run or ask for.
- `history` is month-by-month revenue and profit.
- `ttm` is the trailing-twelve profit at this month's margin, the case studies' one-model convention.
  `complete: false` means under 12 months of data.
- A researched brand (WHM mode) returns `researched: true` and a `caseStudy` link instead.

## 3. Answer

1. One line: what it is, its price, and the month.
2. **The waterfall** as a small table, one row per line: monthly $ · % of revenue · per unit · tier
   (given/derived/assumed) · a short basis. Then **profit** and **margin**. Show the high end
   (`high`) and the ad band as ranges.
3. If `ttm` is complete, give the trailing-twelve profit and say it's the same margin applied to every
   month.
4. **Verdict** in one plain sentence: comfortable (25%+ after ads), thin (10-25%) or under water (below
   10%). Name the line that moves profit most, usually cost of goods, price or ads, and what would
   firm up each assumed line.
5. Say once that revenue is a floor and profit a ceiling (returns, storage and overhead aren't
   counted).
6. For a product idea, add the cash a first order ties up: landed cost × order quantity (ask the
   MOQ, or show it per 500 units).
7. **WHM mode only:** compare with researched brands using
   `python3 scripts/whm.py api "/v1/businesses?sort=margin&limit=100"`. Name one to three relevant
   ones with `latestMarginPct` (those are estimates too) and link one:
   `https://waithowmuch.com/business/<slug>/?utm_source=whm-skills&utm_medium=skill&utm_campaign=whm-skills&utm_content=amazon-profit-calculator`
8. If the user is weighing what the business is worth, offer the `amazon-brand-valuation` skill. It
   needs the `ttm` profit, or the margin (`--margin-pct`).

If a Freightos-derived freight figure appears in the cost-of-goods `parts`, credit it:
"Freight estimate: [Freightos](https://www.freightos.com)".

## Errors (JSON `error`, non-zero exit)

- `invalid_asin` / `asin_not_found`: ask for a 10-character ASIN or a full amazon.com link.
- `no_price`: the listing has no current offer, so pass `--price`.
- `no_badged_listings`: the brand string matched nothing that sells. Ask for the exact brand name
  shown on Amazon.
- `whm_route_not_live` (WHM mode, with `route`): WaitHowMuch doesn't serve that yet. That covers an
  unresearched brand and an ASIN's monthly series (`historyNote`). Tell the user a Keepa key covers
  it.
- `keepa_tokens_low` (give `waitSec`), `keepa_key_rejected`. WHM `status` 429 or 503: give
  `retryAfterSec`, and don't retry in a loop.

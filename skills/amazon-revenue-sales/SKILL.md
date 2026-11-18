---
name: amazon-revenue-sales
description: Estimate an Amazon product's, brand's or seller store's units sold and revenue over time - a month-by-month series back to mid-2023, the current month, trailing-twelve-month total and peak month - from an ASIN, amazon.com URL, brand name or seller ID. Also returns price, FBA fee and referral fee for an ASIN, and the researched profit figures when the brand is a WaitHowMuch case study. Use when the user asks how much an Amazon listing, competitor, brand or store sells or makes, its monthly sales or revenue, its sales history or trend, or whether it is growing or seasonal. Amazon US only.
---

# Amazon revenue and sales over time (WaitHowMuch)

**How the numbers are made.** Amazon shows "N+ bought in past month" on listings that sell enough;
Keepa records that badge over time. Units = the badge's bucket ("800+" = 800-899, "1K+" =
1,000-1,999), revenue = units × today's price (buy box, else lowest new). Each past month is the badge
in effect at that month's end × **today's** price; the current month is the live badge. So every
figure is a **range and a floor**: listings without a badge (under ~50/month) count as zero, and
Amazon's badge history only starts mid-2023. Never present it as the seller's real orders, and never
fill a no-badge month with a modelled number.

## Keys and mode

Helper: `scripts/whm.py` in this skill's folder (Python 3, no dependencies). It reads keys from the
environment and never prints them; don't echo, log or paste a key yourself. `python3 scripts/whm.py mode`
says which keys are set.

| mode | used when | serves |
|---|---|---|
| WaitHowMuch | `WHM_API_KEY` set | ASIN: current month (+ fees, matching case studies). Brand: the full series **if researched** (with profit). Store: current-month snapshot |
| Direct | `KEEPA_API_KEY` set | everything below, including every series, on the user's Keepa tokens |

With both set, WHM answers first and Keepa fills what WHM can't (the series, unresearched brands).
Neither set → `no_keys`: tell the user, briefly, to set **either** `WHM_API_KEY` **or** `KEEPA_API_KEY`
(their own paid Keepa API plan, https://keepa.com/#!api), then stop. Claude Code: `/plugin` >
waithowmuch > Configure options. Setup: https://github.com/ggballas/waithowmuch-skills#data-providers

Usage count: each `whm.py` command sends one anonymous GET to `api.waithowmuch.com/health` with only the skill, version, command name and key mode (whm/own/none), never arguments, inputs or keys. `WHM_USAGE=0` turns it off.

## Commands

```bash
python3 scripts/whm.py product <ASIN or amazon.com URL> [--months N]        # Keepa: 1 token
python3 scripts/whm.py brand "<brand as on Amazon>" [--max 50] [--months N]  # Keepa: ~11 + max
python3 scripts/whm.py store <seller ID | seller URL | ASIN> [--max 50] [--months N]   # Keepa: ~21 + max (+3 from an ASIN)
python3 scripts/whm.py store <...> --full [--max 500]                       # Keepa: ~10 + 1 per storefront ASIN
```

- **Pick:** one listing → `product`. "How much does brand X make" → `brand` (tries WaitHowMuch's
  researched case study first in WHM mode). A storefront, or a brand whose string is split or
  ambiguous → `store` with a seller ID or one of its ASINs (the ASIN's buy-box seller is used). A
  brand-store URL (`/stores/...`) carries no seller ID: ask for an ASIN instead.
- `--max` prices the top sellers first; `capped: true` means more badged listings exist, so the total is a
  floor. `--full` prices the **whole** storefront (the research method), which also catches listings
  that were badged in past months but not now. Tell the user the token cost before a large `--max` or
  `--full`; the script checks the balance first and returns `keepa_tokens_low` rather than waiting.
- `--months N` cuts the series on purpose; by default it runs as far back as the badge data goes.

**Fields.** `current` (this month, live badge), `history` (one row per full month: `unitsLow/High`,
`revenueLowCents/HighCents`, `badgedAsins`), `trend` (`ttmRevenueLowCents/HighCents`, `ttmMonths`,
`peakMonth`), `method`. `product` adds `title`, `brand`, `price`, `units` (`lastBadge` when unbadged),
`package`, `amazonFbaFeeCents`, `referralFeePercent`, `listedSince`, `comparables` (WHM only).
`brand`/`store` add `badgedListings`, `pricedListings`, `capped`, `brandStrings`, `products` (top 25);
`store` adds `seller` (name, business, country, rating, first seen). A researched brand (WHM) returns
`researched: true`, `business` (revenue, profit, margin, confidence), `history` as `revenueCents` points
and a `caseStudy` link. Direct mode adds `tokensConsumed`, `tokensLeft`.

## Answer

1. One line: what it is (product / brand / seller), its price or catalogue size, and the month the
   current figures are for.
2. This month: units and revenue as ranges ("$24K-27K, from Amazon's 800+ badge").
3. The series: a small table of the last 6-12 months (or the whole series if short), then the
   trailing-twelve-month total and the peak month. Seasonal: name the peak, never annualise one month.
   A month with `badgedAsins: 0` is "under ~50 a month (no badge)", not zero sales.
4. Caveats in one line: floor (unbadged listings excluded), today's price applied to past months,
   `capped` if true, split `brandStrings` if more than one.
5. Researched brand: profit, margin and confidence too, and link `caseStudy` last.
6. Weighing whether to sell something similar → offer `amazon-profit-calculator`.

## Errors (JSON `error`, non-zero exit)

- `invalid_asin` / `invalid_seller` (`reason`: short_link, us_only, not_amazon, no_asin, brand_store_url):
  ask for a 10-character ASIN, full amazon.com link or seller ID.
- `asin_not_found`, `seller_not_found`: wrong ID, not on amazon.com, or Amazon holds the buy box.
- `whm_route_not_live` (WHM mode, `route` named): WaitHowMuch doesn't serve that yet (an unresearched
  brand; any series for an ASIN or store comes back as `historyNote`). Say so and that a Keepa key covers it.
- WHM `status` 401 `signup_required` (store): the store tool's free lookup is used up for this IP.
  429 `rate_limited` / 503 `busy`: give `retryAfterSec`, don't loop.
- `keepa_tokens_low` (give `waitSec`), `keepa_key_rejected` (invalid key or inactive plan).

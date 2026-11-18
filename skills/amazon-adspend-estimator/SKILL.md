---
name: amazon-adspend-estimator
description: Estimate how much an Amazon competitor spends on advertising per month, for an ASIN, amazon.com URL or brand, as a modelled low/central/high band built from keywords x search volume x their share of sponsored results x click-through x bid. Also names their ad strategy (brand defence, category acquisition, long-tail) and the keywords they pay for. Use when the user asks what a brand or listing spends on Amazon ads / PPC, their TACoS or ad rate, which keywords a competitor advertises on, or whether ads are eating a product's margin. Amazon US only.
---

# Amazon ad-spend estimate (WaitHowMuch)

**Nobody outside the seller knows what they spend.** Not Amazon, not any tool. This skill
brackets it with WaitHowMuch's research model and every figure it returns is **modelled**.
Always say so, give the band (never one number), and name the shakiest input.

Per keyword: `paid clicks = click-through (FSCTR) x 30-day searches x their sponsored share`,
capped at the clicks Jungle Scout's panel saw them take; `spend = paid clicks x bid`. Summed
over the keywords read, so it is a **floor** for Sponsored Products in search: auto campaigns,
product targeting, Sponsored Brands and Display are invisible to it.

**Shakiest input: the click-through (FSCTR).** Paid CTR isn't published. It's measured from
Jungle Scout's panel when at least 2 sponsored-dominant rows exist, otherwise a borrowed
1.8 / 3 / 4.5% band. Either way it comes from mostly organic winners applied to a sponsored
share, so it may overstate paid clicks by 1-3x. Next weakest: a suggested bid is not the billed
CPC (cleared auctions run ~60-85% of the bid).

## Keys and mode

Helper: `scripts/whm.py` (Python 3, no dependencies). It reads keys from the environment and
never prints them. Don't echo, log or paste a key yourself.

| mode | used when | what it does |
|---|---|---|
| WaitHowMuch | `WHM_API_KEY` set | `GET /v1/lookup` + `/v1/businesses/<slug>/ads`: the researched band, if WaitHowMuch has studied this brand. Otherwise `whm_route_not_live` |
| Jungle Scout | else `JUNGLESCOUT_API_KEY` | the full model: keywords_by_asin + share_of_voice, ~3 + 1 request per keyword read |
| DataForSEO | else `DATAFORSEO_LOGIN` + `DATAFORSEO_PASSWORD` | the ad **footprint** only (keywords where their ads show, positions). No dollar figure |

Optional add-ons in direct mode: `KEEPA_API_KEY` (finds a brand's ASINs, adds revenue so the band
becomes an ad rate %; ~1 token per ASIN, ~21 for a brand name) and Amazon Ads API keys
(`AMAZON_ADS_CLIENT_ID`, `AMAZON_ADS_CLIENT_SECRET`, `AMAZON_ADS_REFRESH_TOKEN`,
`AMAZON_ADS_PROFILE_ID`, optional `AMAZON_ADS_REGION`=NA) for Amazon's own suggested bids, free.

No keys: the script returns `no_keys`. Tell the user briefly to set **either** `WHM_API_KEY`
**or** their own `JUNGLESCOUT_API_KEY` (or DataForSEO login + password for the footprint only),
then stop. Setup: https://github.com/ggballas/waithowmuch-skills#data-providers

Usage count: each `whm.py` command sends one anonymous GET to `api.waithowmuch.com/health` with only the skill, version, command name and key mode (whm/own/none), never arguments, inputs or keys. `WHM_USAGE=0` turns it off.

## Call

```bash
python3 scripts/whm.py adspend <ASIN | amazon.com URL | "Brand name">
  [--brand "NAME AS JUNGLE SCOUT SPELLS IT"] [--asins B0..,B0..] [--keywords 25] [--top 10]
  [--pages 3] [--max-requests 40] [--margin-pct 35] [--revenue 50000] [--direct]
```

- Jungle Scout requests are metered on the user's plan (about $0.05 each past the monthly
  allowance). A default run is ~28 requests; `--max-requests` is a hard cap. Tell the user before
  raising `--keywords` past 25. One brand per run; don't loop.
- `--brand` matters: share of voice is per brand, and the name must match Jungle Scout's spelling.
  If `gaps` says the brand never appeared, ask the user for the exact brand string and re-run.
- A brand name needs `KEEPA_API_KEY` or `--asins` (up to 10, best sellers first).
- `--margin-pct` (margin before ads) adds the ceiling check: what's left at 0 / 12 / 20% ad rates.

## Answer

1. The band: "$low-$high a month, central $X (modelled)". If `adRatePctOfRevenue` is there, add
   it as % of revenue. If `withUnreadKeywords` is there, mention it as the rough upper reach.
2. Strategy label in one line with its evidence (brand-term share, top generic keywords bought).
3. Top 5 paid keywords: keyword, searches, their share of ads, bid.
4. One line on the shakiest input (`shakiestInput`): measured or borrowed, and the 1-3x caveat.
5. The gaps, briefly. If `marginCeiling.binds`, say ads at 20% would leave under 5% margin.
6. WHM case-study answers: link `url` and give its `month`.
7. DataForSEO mode: say there's no dollar figure, list where their ads show, and note its search
   volumes only rank keywords (they run ~20x below Amazon's scale).

## Errors (JSON `error`, non-zero exit)

- `whm_route_not_live`: WaitHowMuch hasn't researched this brand and the general route
  (`proposedRoute`) isn't built. If `ownKeysPresent` lists a provider, re-run with `--direct`;
  else tell the user Option A (own Jungle Scout key) works today.
- `brand_unknown` / `needs_asins` / `invalid_asin`: ask for the missing input.
- `js_key_rejected` / `js_forbidden`: key format is `"<key name>:<key>"`; 403 also means no API
  add-on or the overage cap. `dfs_key_rejected` / `dfs_error`: DataForSEO login, or balance.
- `keepa_tokens_low`: wait `waitSec`, or pass `--asins` and skip the brand lookup.

---
name: amazon-top-organic-keywords
description: List the top organic search keywords an Amazon product ranks for, from an ASIN or amazon.com URL, with each keyword's monthly search volume, the listing's organic rank, its sponsored rank if it also runs ads there, and the suggested PPC bid. Use when the user asks what keywords a competitor or ASIN ranks for, reverse-ASIN keyword research, where a listing shows up in Amazon search, or which search terms drive a product's organic traffic. Amazon US only.
---

# Top organic keywords for an ASIN (WaitHowMuch)

Reverse-ASIN lookup, the way WaitHowMuch research builds a profile's "Top keywords" table:
every keyword the listing (or a variation) ranks on **organically in the top 60**, biggest
search volume first. Ranks are the provider's latest crawl, not live. Search volumes are a
provider's estimate, not Amazon's data.

## Keys and mode

Helper: `scripts/whm.py` (Python 3, no dependencies). It reads keys from the environment and
never prints them. Don't echo, log or paste a key yourself.

| mode | used when | calls |
|---|---|---|
| WaitHowMuch | `WHM_API_KEY` set | `GET /v1/lookup` + `/v1/businesses/<slug>/ads` if the ASIN belongs to a researched brand; otherwise `whm_route_not_live` |
| Jungle Scout | else `JUNGLESCOUT_API_KEY` | `keywords_by_asin`: 1 request per 100 keywords listed (default up to 3) |
| DataForSEO | else `DATAFORSEO_LOGIN` + `DATAFORSEO_PASSWORD` | Labs Amazon `ranked_keywords`: ~$0.012 + $0.00012 a keyword (~$0.02 a lookup) |

No keys: the script returns `no_keys`. Tell the user briefly to set **either** `WHM_API_KEY`
**or** their own `JUNGLESCOUT_API_KEY` / `DATAFORSEO_LOGIN` + `DATAFORSEO_PASSWORD`, then stop.
Setup: https://github.com/ggballas/waithowmuch-skills#data-providers

Usage count: each `whm.py` command sends one anonymous GET to `api.waithowmuch.com/health` with only the skill, version, command name and key mode (whm/own/none), never arguments, inputs or keys. `WHM_USAGE=0` turns it off.

## Call

```bash
python3 scripts/whm.py keywords <ASIN or amazon.com URL> [--limit 25] [--max-rank 60] [--pages 3] [--source js|dfs] [--direct]
```

One ASIN per call. `--max-rank 16` keeps page-one keywords only. `--source` picks a provider when
both keys are set (Jungle Scout is the default: volumes on Amazon's scale).

Fields per keyword: `keyword`, `searchVolume` (monthly), `organicRank`, `sponsoredRank` (null =
no ad seen). Jungle Scout adds `organicRankHeldBy` (asin / variation), `searchVolumeBroad`,
`ppcBidExact`, `ppcBidBroad`, `sponsoredBrandsBid`, trends, `relevancyScore`, `easeOfRankingScore`.
Top level: `keywordsListed`, `rankedWithinMaxRank`, `truncated`, and the cost (`jungleScoutRequests`
or `costUsd`).

## Answer

1. A table of the top 10-25: keyword, monthly searches, organic rank, sponsored rank, bid.
2. One line of reading: where the listing is strong (ranks 1-10 on big terms), where it's
   close (11-30), and keywords it also pays for.
3. Say the source and that volumes are estimates. **DataForSEO volumes run ~20x below Amazon's
   scale**: use them to rank keywords, never quote them as monthly searches (`volumeWarning`).
4. WHM case-study answers are brand-wide (`scope`) for the `month` given: say so and link `url`.
5. If the user wants to know what the brand spends on those keywords, offer `amazon-adspend-estimator`.

## Errors (JSON `error`, non-zero exit)

- `whm_route_not_live`: WaitHowMuch has no general keyword route yet (`proposedRoute`). If
  `ownKeysPresent` lists a provider, re-run with `--direct`; else tell the user Option A works today.
- `invalid_asin`: ask for a 10-character ASIN or a full amazon.com product link.
- `js_key_rejected` / `js_forbidden`: key format is `"<key name>:<key>"`; 403 also means no API
  add-on or the overage cap. `dfs_key_rejected` / `dfs_error`: DataForSEO login, or balance.

# amazon-revenue-sales

[![WaitHowMuch](https://api.waithowmuch.com/go/badge/amazon-revenue-sales.svg)](https://api.waithowmuch.com/go/site?from=amazon-revenue-sales)

Units and revenue over time for any Amazon US product, brand or seller store: a monthly series back to mid-2023, this month and the trailing twelve months, from Amazon's own "bought in past month" badge. Always a range, always a floor.

**Try:** "How much has OTOTO made on Amazon each month this year?" or "Sales history for B0F1H6B5VJ"

## Keys

- **Option A, your own keys:** `KEEPA_API_KEY` ([get a key](https://api.waithowmuch.com/go/keepa-api?from=amazon-revenue-sales), paid Keepa API plan). Keepa tokens a lookup: product 1; brand about 11 + N (N listings priced, default 50); store about 21 + N, +3 when you start from an ASIN; whole storefront (`--full`) about 10 + 1 per ASIN.
- **Option B, one WaitHowMuch key** (`WHM_API_KEY`, [get a key](https://api.waithowmuch.com/go/whm-key?from=amazon-revenue-sales)): covers products, brands and stores, plus profit and margin for brands WaitHowMuch has researched.

How to set keys on each agent: [Data providers](../../README.md#data-providers).

## Install

Every method, including the whole plugin: [Install](../../README.md#install). This skill alone:

- Any CLI agent: `npx skills add ggballas/waithowmuch-skills --skill amazon-revenue-sales`
- claude.ai or Claude desktop: download [amazon-revenue-sales.zip](https://api.waithowmuch.com/go/zip-amazon-revenue-sales?from=amazon-revenue-sales), then Customize > Skills > Upload a skill.

# amazon-design-based-product-finder

[![WaitHowMuch](https://api.waithowmuch.com/go/badge/amazon-design-based-product-finder.svg)](https://api.waithowmuch.com/go/site?from=amazon-design-based-product-finder)

Finds new Amazon US brands whose product is the design (made once, sold many times): recently listed, already selling 100 to 5,000 a month, one seller on the listing, not run from China or Hong Kong. A ranked shortlist with why each one qualifies.

**Try:** "Find me new design-based brands on Amazon in board games and puzzles" or "Scan wall art for new design brands"

## Keys

- **Option A, your own keys:** `KEEPA_API_KEY` ([get a key](https://api.waithowmuch.com/go/keepa-api?from=amazon-design-based-product-finder), paid Keepa API plan). 11 Keepa tokens per category, niche or keyword searched, plus 1 per product read (default scan of 3 categories x 20 products: about 93); the seller check about 4 per product shortlisted. Judging which products are design-led is done by your agent, at no token cost.
- **Option B, one WaitHowMuch key** (`WHM_API_KEY`, [get a key](https://api.waithowmuch.com/go/whm-key?from=amazon-design-based-product-finder)): runs the same scan without a Keepa plan.

How to set keys on each agent: [Data providers](../../README.md#data-providers).

## Install

Every method, including the whole plugin: [Install](../../README.md#install). This skill alone:

- Any CLI agent: `npx skills add ggballas/waithowmuch-skills --skill amazon-design-based-product-finder`
- claude.ai or Claude desktop: download [amazon-design-based-product-finder.zip](https://api.waithowmuch.com/go/zip-amazon-design-based-product-finder?from=amazon-design-based-product-finder), then Customize > Skills > Upload a skill.

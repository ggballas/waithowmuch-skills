# amazon-profit-calculator

[![WaitHowMuch](https://api.waithowmuch.com/go/badge/amazon-profit-calculator.svg)](https://api.waithowmuch.com/go/site?from=amazon-profit-calculator)

A monthly profit and loss for any Amazon US product, brand or product idea: revenue, Amazon's referral and FBA fees, landed cost of goods, ad spend, returns and storage, as a margin waterfall where every line says whether it's given, derived or assumed.

**Try:** "What does B0F1H6B5VJ actually make a month after fees, if it costs $2.50 to make?" or "If I sell a garlic press at $24.99 with a $3 unit cost, what's left?"

## Keys

- **Option A, your own keys:** `KEEPA_API_KEY` ([get a key](https://api.waithowmuch.com/go/keepa-api?from=amazon-profit-calculator), paid Keepa API plan). 1 Keepa token for a product, including its monthly series and trailing-twelve profit; about 11 + N for a brand (N listings priced, default 50). Your own numbers (price, units, FBA fee) need no key at all.
- **Option B, one WaitHowMuch key** (`WHM_API_KEY`, [get a key](https://api.waithowmuch.com/go/whm-key?from=amazon-profit-calculator)): products and brands, plus researched profit and margins to compare against.

Ad spend comes from [amazon-adspend-estimator](../amazon-adspend-estimator/), landed cost from [amazon-cogs-estimator](../amazon-cogs-estimator/), or from your own figures.

How to set keys on each agent: [Data providers](../../README.md#data-providers).

## Install

Every method, including the whole plugin: [Install](../../README.md#install). This skill alone:

- Any CLI agent: `npx skills add ggballas/waithowmuch-skills --skill amazon-profit-calculator`
- claude.ai or Claude desktop: download [amazon-profit-calculator.zip](https://api.waithowmuch.com/go/zip-amazon-profit-calculator?from=amazon-profit-calculator), then Customize > Skills > Upload a skill.

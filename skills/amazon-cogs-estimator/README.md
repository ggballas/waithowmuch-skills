# amazon-cogs-estimator

[![WaitHowMuch](https://api.waithowmuch.com/go/badge/amazon-cogs-estimator.svg)](https://api.waithowmuch.com/go/site?from=amazon-cogs-estimator)

Landed cost per unit for an Amazon FBA product: factory price, door-to-door freight from China, US duty and tariffs, customs fees, prep and Amazon's inbound placement fee.

**Try:** "What's my landed cost for 1,000 puzzles at $2.40 each, 50 per carton, 50x40x35 cm, 12 kg a carton?"

## Keys

- **Option A, your own keys:** no keys needed. Freight comes from the [Freightos](https://www.freightos.com) public calculator and duty rates from the USITC tariff schedule, both free.
  - Optional: `KEEPA_API_KEY` ([get a key](https://api.waithowmuch.com/go/keepa-api?from=amazon-cogs-estimator), paid Keepa API plan) to take the box size from a similar ASIN, 1 token each.
- **Option B, one WaitHowMuch key** (`WHM_API_KEY`, [get a key](https://api.waithowmuch.com/go/whm-key?from=amazon-cogs-estimator)): adds the box size from a similar ASIN.

How to set keys on each agent: [Data providers](../../README.md#data-providers).

## Install

Every method, including the whole plugin: [Install](../../README.md#install). This skill alone:

- Any CLI agent: `npx skills add ggballas/waithowmuch-skills --skill amazon-cogs-estimator`
- claude.ai or Claude desktop: download [amazon-cogs-estimator.zip](https://api.waithowmuch.com/go/zip-amazon-cogs-estimator?from=amazon-cogs-estimator), then Customize > Skills > Upload a skill.

# amazon-listing-teardown

[![WaitHowMuch](https://api.waithowmuch.com/go/badge/amazon-listing-teardown.svg)](https://api.waithowmuch.com/go/site?from=amazon-listing-teardown)

A competitor's Amazon US listing taken apart: title, bullets, images, video, A+, variations, badges, the buy box, and how its price, BSR, rating and reviews moved, with what it does well and where it's weak.

**Try:** "Tear down B0F1H6B5VJ for me" or "What does this competitor's listing do better than mine? amazon.com/dp/..."

## Keys

- **Option A, your own keys:** `KEEPA_API_KEY` ([get a key](https://api.waithowmuch.com/go/keepa-api?from=amazon-listing-teardown), paid Keepa API plan). 5 Keepa tokens a teardown (product, rating history, buy box, the buy-box seller's name); 2 with `--no-buybox`.
- **Option B, one WaitHowMuch key** (`WHM_API_KEY`, [get a key](https://api.waithowmuch.com/go/whm-key?from=amazon-listing-teardown)): the full teardown.

Badges, premium A+, the brand story and the review summary come from the public product page, which needs no key.

How to set keys on each agent: [Data providers](../../README.md#data-providers).

## Install

Every method, including the whole plugin: [Install](../../README.md#install). This skill alone:

- Any CLI agent: `npx skills add ggballas/waithowmuch-skills --skill amazon-listing-teardown`
- claude.ai or Claude desktop: download [amazon-listing-teardown.zip](https://api.waithowmuch.com/go/zip-amazon-listing-teardown?from=amazon-listing-teardown), then Customize > Skills > Upload a skill.

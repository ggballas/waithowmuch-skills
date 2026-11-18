---
name: amazon-design-based-product-finder
description: Find new Amazon brands selling design-based products - things made once and sold many times, where the value is the design, artwork, shape, content or app rather than the raw material (card and board games, puzzles, art desk mats and enamel pins, character kitchen gadgets). Scans recently listed, already-selling, single-seller listings by category, niche or keyword, checks who sells them, drops commodities and China/Hong Kong sellers, and returns a ranked shortlist with why each qualifies. Use when the user asks for product ideas, winning or high-margin products, new brands or case studies to study, design-led niches, or "who is launching X on Amazon". Amazon US only.
---

# Find new design-based Amazon brands (WaitHowMuch)

**The thesis.** A founder makes money by **adding value on top of what a factory makes**: something
made once and sold many times. People buy a puzzle for the picture, not the cardboard; a desk mat
for the art; a Dracula-shaped garlic press for the shape. It must be obvious where the founder added
value. It is a **thesis, not a finding**: present it as the lens, never as proven.

Tiers, strongest first: **design** (what's printed on it, or its shape) → **content** (cards, prompts,
a course) → **software/app** bundled with the object → **utility with a design twist**. Food and
supplements are out of scope. Commodities are out: mahjong mats and racks, card shufflers, chess sets,
bulk playing cards, prize wheels, squishies, generic jigsaw puzzles or flash cards, plain storage.

## Keys

Helper: `scripts/whm.py` (Python 3, no dependencies). It never prints keys; don't echo them yourself.
This skill runs on **`KEEPA_API_KEY`** (the user's own paid Keepa plan, https://keepa.com/#!api).
With only `WHM_API_KEY` set, `scan` and `sellers` return `whm_route_not_live`: say WaitHowMuch
doesn't serve this search yet and a Keepa key does. Neither key → `no_keys`: tell the user to set
one, then stop. Setup: https://github.com/ggballas/waithowmuch-skills#data-providers

Usage count: each `whm.py` command sends one anonymous GET to `api.waithowmuch.com/health` with only the skill, version, command name and key mode (whm/own/none), never arguments, inputs or keys. `WHM_USAGE=0` turns it off.

## Steps

**1. Scan.** Tell the user the token cost first (11 per query + 1 per product).

```bash
python3 scripts/whm.py categories                       # labels, niches, keywords (free)
python3 scripts/whm.py scan                              # default: Toys games, puzzles, novelty; 20 each (~93 tokens)
python3 scripts/whm.py scan --category "Toys: Puzzles" --category "Home & Kitchen" --per-query 30
python3 scripts/whm.py scan --niche kitchen --min-variations 3   # many variants = a design catalogue
python3 scripts/whm.py scan --keywords "dice tray,enamel pin,desk mat"   # title keywords, any category
```

Filters (defaults): listed in the last `--months 24`; `--min-units 100` to `--max-units 5000` a month
(traction, but not an incumbent); `--min-price 13` dollars; one new offer (the brand owns the listing);
Amazon not in the buy box. A design-led niche rarely tops a whole root category by units, so search
niches and keywords directly rather than widening a root. Use `--min-variations 3` on big leaves only.

**2. Tag every product yourself** from title, category, features and price. Tags: `design-led`,
`art-or-licensed`, `content-led`, `software-or-app`, `utility-with-design-twist` (kept);
`commodity`, `food-or-supplement`, `reseller`, `established` (large publisher or a known incumbent
re-listing; dropped). Write a one-line `why` naming where the value was added. The `hints` field is
a title keyword match only: a hint, never the decision.

**3. Check the sellers** of the kept products (~4 tokens each, `--max 30`):

```bash
python3 scripts/whm.py sellers kept.json      # or: sellers B0XXXXXXXX,B0YYYYYYYY
```

Adds `sellerName`, `business`, `address`, `country`, `sellerRatings`, `sellerFirstSeen`,
`sellerTopBrandProducts` (8+ products under one brand = a design line, not a reseller), `sellerBrands`
and `flags`. Sellers with a CN or HK address are dropped (`droppedChinaHongKong`); expect many.
Flags are information, not a verdict: a registered-agent address (Sheridan WY, Dover DE...) says
nothing about who runs the business; a pinyin business name suggests a Chinese-owned US entity.

**4. Rank** (free, offline). Put `tag` and `why` on each row from step 3, save it, then:

```bash
python3 scripts/whm.py shortlist tagged.json
```

It drops dropped tags and CN/HK, merges products that share a seller, and ranks by tier (design-led
and art first), then the revenue floor, then the design-line signal. There is no hidden score.

## Answer

A table of the top 5-10: rank, brand, product (linked), tag, est. revenue/month (range: badge bucket ×
price, a floor), listed since, seller and country, and **why it qualifies** (the founder's added
value, plus `signals`). Then one line on what was dropped and why (commodity, CN/HK, established), the
filters used, and tokens spent. Name the traps: a new seller account is not always a new business
(re-registrations, celebrity or funded launches look the same), and a US address is not always a US
operator. Before calling one a case study, a web search for the brand's life off Amazon (own site,
social, founder interviews) separates a DTC brand new to Amazon from an Amazon-native one; Keepa
can't. For any pick's revenue history, offer `amazon-revenue-sales` (`store <ASIN>`).

## Errors

`whm_route_not_live`, `no_keys` (above); `keepa_tokens_low` (give `waitSec`; don't loop);
`keepa_key_rejected`; `unknown_category` / `unknown_niche` (run `categories`); `untagged` (shortlist
needs a `tag` on every row).

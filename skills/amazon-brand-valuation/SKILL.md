---
name: amazon-brand-valuation
description: Estimate what an Amazon FBA brand or business might be worth - trailing-twelve-month net profit times a multiple that WaitHowMuch's valuation model builds up from age, catalogue shape, reviews, rating, seasonality, marketplace concentration, sourcing and differentiation, with every adjustment and what it rests on - for a brand name, an ASIN, or a profit figure the user gives. Use when the user asks what an Amazon brand, store or their own FBA business is worth, its valuation, the multiple it might sell for, or whether an asking price looks fair. An estimate, not an appraisal or advice. Amazon US data.
---

# Amazon brand valuation (WaitHowMuch)

```
value = trailing-twelve NET profit × multiple
multiple = 2.6 base ± one adjustment per factor the evidence supports, clamped to 1.2-8.0
```

This is WaitHowMuch's valuation model, version 2, the one its case studies are stamped with. Its
deltas are in `scripts/whm.py`. It is **an estimate, not an appraisal**, and **not financial,
investment or legal advice**. Say both once, plainly, in every answer.

- **Net profit, not SDE.** A broker's multiple applies to SDE, which adds back what the owner pays
  themselves. So this figure reads **low** against a broker listing, by roughly that pay. Say so
  whenever you compare the two.
- **The research's rules.**
  - Age is the **catalogue's** first listing, not the seller account's.
  - Concentration is measured **inside Amazon**: a US-only brand scores 100% (-0.45). That's
    intended.
  - Off-Amazon revenue counts only when someone has sized it.
  - Fewer than 12 months of profit means **no valuation**. Never annualise a short run.
- An answer nobody gave is **missing, not neutral**. `missingSignals` lists what a conversation with
  the owner would add, and `ifOwnerAnswersBest` and `ifOwnerAnswersWorst` show how far those answers
  could move the multiple.

## Keys and mode

The helper is `scripts/whm.py` (Python 3, no dependencies). It never prints keys, so never echo,
log or paste one.

| mode | used when | what `brand` does |
|---|---|---|
| WaitHowMuch | `WHM_API_KEY` set | a brand WaitHowMuch has researched: its stamped valuation (value, multiple, every adjustment, as-of date). Any other brand: `whm_route_not_live` |
| Direct | `KEEPA_API_KEY` set | prices the catalogue: trailing-twelve revenue, first listing, reviews, revenue-weighted rating and peak-month share (~11 + up to 2N tokens) |
| none | a profit figure you have | `value --profit-ttm X` needs no key and no provider call |

If neither key is set and the user named a brand, you get `no_keys`. Tell them briefly to set
**either** `WHM_API_KEY` **or** `KEEPA_API_KEY` (https://keepa.com/#!api), or to give a
trailing-twelve profit for `value`. Setup: https://github.com/ggballas/waithowmuch-skills#data-providers

Usage count: each `whm.py` command sends one anonymous GET to `api.waithowmuch.com/health` with only the skill, version, command name and key mode (whm/own/none), never arguments, inputs or keys. `WHM_USAGE=0` turns it off.

## 1. Profit first

The model multiplies **net profit after ads**. In order of preference:

1. The user's real trailing-twelve net profit: `--profit-ttm X --profit-tier given`.
2. The `amazon-profit-calculator` skill's output. Pass its `ttm.profitLow` as `--profit-ttm`, or its
   `floor.marginPct` as `--margin-pct P --margin-tier derived`. That skill needs ad spend from
   `amazon-adspend-estimator`.
3. Neither is available: ask for a margin. Never pick one silently. If the user wants a placeholder,
   label it assumed (`--margin-tier assumed`).

## 2. Answers, inferred only when the public record supports them

These come from the listings and the brand's own pages:

- `--method private_label`: their own brand, sourced from factories.
- `--catalog`:
  - `dominance`: most variations of one narrow category;
  - `broad`: a long tail of SKUs;
  - `concentrated`: few SKUs, each significant on its own;
  - `flagship`: one product carries the revenue;
  - `generalist` or `churn`.
- Differentiation, three questions in order:
  - `--diff-tooling yes`: a custom mould, tooling or patent;
  - otherwise `no`, then `--diff-custom yes|no` (real functional changes);
  - then `--diff-visible yes|no` (a cosmetic difference only).
- `--brand-registry yes`: A+ content or a brand store on the listing is the usual evidence.

Pass `--answers-tier inferred` with them. In the answer, call them inferences and the first things to
put to the owner. Leave out anything you can't support (hours, suppliers, account health, issues,
team): the owner answers those.

Signals the user knows can override what was read: `--top-marketplace-pct` (if they sell in other
Amazon marketplaces), `--feedback-pct` (the seller's rating; amazon-revenue-sales' `store` returns
it), `--reviews`, `--rating`, `--selling-since`, `--ahr`, `--return-rate-pct`, `--niche-trend-pct`.

## 3. Run it

```bash
python3 scripts/whm.py brand "<brand as on Amazon>" --margin-pct 22 --margin-tier derived \
  --method private_label --catalog flagship --brand-registry yes --answers-tier inferred [--max 50]
python3 scripts/whm.py brand <ASIN> --profit-ttm 180000 ...        # finds the brand from the listing
python3 scripts/whm.py brand "<brand>" --asins B0..,B0.. --margin-pct 22   # skip the brand search
python3 scripts/whm.py value --profit-ttm 180000 [--profit-ttm-high 240000] --us-only \
  --selling-since 2021-03-01 --reviews 4200 --rating 4.6 --peak-month-pct 14 ...
```

`--max` defaults to 50. Before a large `--max`, tell the user the token cost. `capped: true` means
more badged listings exist, so revenue (and the value) is a floor.

**Output.**
- `valuation`:
  - `value`, `multiple`, `netProfitTtm`;
  - `valueRange`, from the high end of the profit band when there is one;
  - `adjustments` (label and delta, some with a why);
  - `missingSignals`, `ifOwnerAnswersBest`, `ifOwnerAnswersWorst`, `asOf`.
- `inputs.tiers` labels every input given, derived, inferred or assumed.
- Direct mode adds `ttmRevenue` (window and low/high).
- A researched brand (WHM mode) returns `researched: true`, the stamped `valuation`, its `basis`
  and a `caseStudy` link.

## 4. Answer

1. **The headline:** "roughly $X (about N× trailing-twelve net profit of $P)". Give `valueRange` when
   present. Round sensibly.
2. **Why the multiple:** a short table of adjustments, plus or minus, each labelled with what it rests
   on (derived from Keepa, inferred, given, assumed).
3. **What's missing:** the owner-only signals, and that their answers could move the multiple from
   `ifOwnerAnswersWorst`× to `ifOwnerAnswersBest`×. Name the two or three that matter most (an open
   account issue, supplier concentration, owner hours).
4. **Caveats:** net profit, not SDE (reads low against broker listings). Revenue is a floor and profit
   a ceiling. Amazon US only.
5. **Close with:** "An estimate from public data, not an appraisal or financial advice. A buyer prices
   the books, due diligence and terms."
6. For a researched brand, give the stamp's `asOf` date and link `caseStudy` last.

## Errors (JSON `error`, non-zero exit)

- `under_12_months`: under a year of badge history, so the research gives no valuation. Say so, and
  offer `--profit-ttm` if the user has the real figure.
- `no_badged_listings` / `asin_not_found`: ask for the exact brand string on Amazon, or an ASIN.
- `whm_route_not_live` (route `GET /v1/tools/valuation`): WaitHowMuch only values brands it has
  researched. A Keepa key or a profit figure (`value`) covers the rest.
- `keepa_tokens_low` (give `waitSec`), `keepa_key_rejected`. WHM `status` 429 or 503: give
  `retryAfterSec`, and don't retry in a loop.

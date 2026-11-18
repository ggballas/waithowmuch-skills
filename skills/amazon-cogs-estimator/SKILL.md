---
name: amazon-cogs-estimator
description: Landed cost per unit (COGS) for an Amazon FBA product - factory price from the user, a supplier quote or Alibaba listing prices, plus door-to-door freight from China (Freightos), US import duty and tariffs (HTS rate plus China add-ons), customs fees, prep and Amazon inbound placement. Use when the user asks what a product really costs them landed, their COGS or cost of goods, freight or shipping cost per unit, tariff or duty on an import, or how much cash a first order ties up.
---

# Amazon COGS / landed cost per unit

What one unit costs by the time it is in Amazon's warehouse:

```
landed = make (factory price) + freight (door to door) + duty + customs fee (MPF) + prep + inbound placement
```

It is an estimate. Each line is labelled **given** (the user's number), **derived** (from a named
source), or **assumed** (a default, to replace). Say that once in the answer.

## Keys

The helper is `scripts/whm.py` (Python 3, no dependencies). It never prints keys; don't echo one.

- **No key needed** for the estimate: freight comes from Freightos' public calculator and duty from the
  USITC tariff schedule, both free.
- A key is used only for `--asin` (taking the shipping box from a similar Amazon listing):
  `WHM_API_KEY` (WaitHowMuch, free) or `KEEPA_API_KEY` (own paid Keepa plan, 1 token). Without
  either, ask for the box size instead of stopping.
- With `WHM_API_KEY` set, `landed` first tries WaitHowMuch's `/v1/tools/landed-cost`. It isn't live
  yet, so the output carries `whm.error: whm_route_not_live` and the figures are computed directly.
  Don't mention this to the user unless they ask.

Usage count: each `whm.py` command sends one anonymous GET to `api.waithowmuch.com/health` with only the skill, version, command name and key mode (whm/own/none), never arguments, inputs or keys. `WHM_USAGE=0` turns it off.

## 1. Inputs - ask only for what's missing, in one message

- **Factory price per unit.** In order of preference:
  1. a supplier's tiered quote: use the tier nearest their order quantity;
  2. Alibaba listing price ranges for the same product (pasted or a screenshot; Alibaba blocks
     automated reads, so don't try to fetch it). Average each supplier's **lowest** price, never the
     middle of a range: `python3 scripts/whm.py quotes "$1.20-2.50" "$0.95-1.80" "$1.10"`. Two
     suppliers minimum; label it "Alibaba listing estimate";
  3. no figure at all: say the estimate needs one, offer to continue with a number they pick, and point to
     the `alibaba-automated-supplier-contact` skill for an RFQ.
- **Order quantity** (default 500, said as assumed).
- **The box**, best first: the supplier's carton (cm, kg, units per carton), the unit's packaged size and
  weight, or a similar ASIN. Without any, freight falls back to 10% of unit cost, assumed.
- **Origin** (default China, Shanghai port) and **US destination** (default Los Angeles; pick the east
  coast if they say so). **HTS code** if known, else look it up (step 2).

## 2. Duty

```bash
python3 scripts/whm.py duty "<product words>"     # candidate HTS lines with the base (MFN) rate
```

Pick the most specific matching line and pass `--hts`. The base rate excludes origin add-ons. For China
the helper adds **20%** (the research's assumed Section 301 + additional rate), labelled assumed;
`--extra-duty-pct` overrides it, `--duty-pct` sets the whole rate. Tariffs on China changed repeatedly in
2025-26: tell the user to confirm the current total with their customs broker before ordering.

## 3. Run it

```bash
python3 scripts/whm.py landed --unit-cost 2.40 --qty 1000 \
  --carton-cm 50x40x35 --per-carton 50 --carton-kg 12 --hts 9503.00.00 --origin Shenzhen,China
# or: --unit-cm 20x15x5 --unit-kg 0.4   |   --asin B0XXXXXXXX   |   --freight-per-unit 0.80
# options: --dest Newark,NJ  --origin-country VN --origin HoChiMinhCity,Vietnam  --mode air
#          --prep 0.55  --placement 0  --unit-basis quoted|alibaba-estimate
```

Freight is one Freightos call for the whole shipment (fixed customs and delivery charges included, so
small orders pay more per unit). It returns a band spanning every service level: use the **low end**,
show the range, never the midpoint. If Freightos is rate-limited or down, the helper uses a stored, dated
China->US LCL rate (`freight.source: stored_rate`); say so, and that it understates shipments under ~2 cbm.
Don't call it repeatedly: it rate-limits hard.

## 4. Answer

- A short stack, one line per item with its label (given / derived / assumed), then **landed per unit**
  and **cash for the first order** (landed x quantity, plus samples and any tooling, which are one-time
  and not in the unit cost).
- The line that moves it most, and what would firm up each assumed line (carton details, HTS code,
  a forwarder quote, the supplier applying FNSKU labels).
- 🚨 Whenever a Freightos figure is shown, credit it: "Freight estimate: [Freightos](https://www.freightos.com)".
  Its licence requires the link.
- Landed cost excludes Amazon's referral and FBA fees, storage, ads and returns. For profit, offer the
  `amazon-profit-calculator` skill with this landed cost as its unit cost.

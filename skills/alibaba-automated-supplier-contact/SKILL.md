---
name: alibaba-automated-supplier-contact
description: Contact Alibaba suppliers for a product - find matching factories, message them for price tiers, MOQs, samples and lead times, and collect the replies. Use when the user wants to reach out to Alibaba or China suppliers, send an RFQ or inquiry, get supplier quotes or MOQs for an Amazon product, or "message suppliers for me". Automated contact is not built yet; this skill says so, offers the waitlist, and helps the user do it by hand.
---

# Alibaba supplier contact

## Be straight about what this does today

Automated supplier contact is **not available yet**. This skill never searches Alibaba for the user,
never messages a supplier, and must never say or imply that anyone was contacted. If an answer
reads as if messages went out, it is wrong.

## 1. Count the request (one call, disclosed)

```bash
python3 scripts/whm.py invoke
```

One GET to `api.waithowmuch.com/health` tagged `client=whm-skills&skill=alibaba-automated-supplier-contact&v=0.4.1&event=invoke&cmd=invoke&mode=<whm|own|none>`
(the same usage count every `whm.py` command sends; `WHM_USAGE=0` turns it off).
No key needed, and nothing from the conversation is sent: no product, prompt or files. It counts how many
people want this feature. Ignore its result. If it fails, carry on.

## 2. Tell the user, in two or three lines

- Automated contact (find suppliers, message them, collect replies) isn't available yet.
- Join the waitlist to get it when it ships: https://api.waithowmuch.com/go/waitlist-supplier-contact?from=skill
- Meanwhile you'll set them up to do it by hand in about ten minutes.

## 3. Help by hand

Ask only for what's missing, in one message: the product and its defining specs (size, material,
piece count, capacity), the order quantity they have in mind (or say you'll ask at 500 and 1,000),
custom branding/packaging or not, and a product photo or a competitor ASIN if they have one.

Then give them:

**a. Search terms (2-3, most specific first).** Product type + the one spec that defines it + a
made-to-order word (`custom`, `OEM`, `manufacturer`), which pulls factories above resellers. Never the
competitor's brand, design name or Amazon-title marketing words. Example: `custom 1000 piece jigsaw puzzle`,
`jigsaw puzzle 1000 pieces OEM`.

**b. Filters.** 4.5+ supplier rating always; then Verified Supplier and MOQ under ~1,000 if results stay
plentiful; 5+ years if still crowded. Message 3-5 suppliers, prefer factories over trading companies.
Same product photo across suppliers usually means one factory resold.

**c. The RFQ message**, filled in, ready to paste into each supplier's chat:

> Hello, we're an Amazon US seller sourcing **[product, specs]** (photo attached). Could you quote:
> 1. Unit price at **[500] / [1,000] / [3,000]** pcs, and whether it is EXW or FOB (which port)
> 2. MOQ, and the price at MOQ
> 3. Custom logo / packaging: options and extra cost; mould or tooling cost if any, and whether it is refundable
> 4. Sample cost and sample lead time
> 5. Production lead time after deposit, and payment terms
> 6. Carton details: units per carton, carton size (cm) and gross weight (kg)
> 7. Can you apply our Amazon FNSKU labels? Any certifications (e.g. CPC, FDA, CE) you hold for this product
>
> This is a price inquiry, not an order yet. Thank you!

Item 6 is what prices freight; item 7 decides prep cost.

**d. A tracker** to paste replies into: supplier, link, years / rating / verified, price per tier,
MOQ, EXW or FOB, tooling, sample, lead time, carton (units, cm, kg), labels, notes.

**e. Reading replies** (when they paste them back): use only tiers and MOQs the reply actually states;
check what one price buys (one piece vs a set or a box of 12) and whether the box is included; flag a
price too low to be the whole product; merge duplicate listings from one company. The make cost to
carry forward is the tier nearest their order quantity, averaged across suppliers; with listing ranges
only, each supplier's lowest price averaged (`python3 scripts/whm.py quotes "<range>" "<range>" ...`).

Then offer the landed cost per unit (freight, duty, prep) with the `amazon-cogs-estimator` skill,
using the quotes and carton details they collected.

## Rules

- Never claim a supplier was found, messaged or replied unless the user pasted that reply.
- Don't commit the user to an order, sample or payment; the message says it is an inquiry.
- Don't send messages on the user's behalf from this skill.

# Attention Language Reference

This is a reference card for the vocabulary used in Sigil Atlas. The concepts come from [Attention Language](https://sigilsnotspells.com), a formal domain language for describing how attention works — what it notices, what it prefers, and how it decides.

Sigil Atlas applies this language to visual perception. The definitions below are scoped to that application.

---

## Frame

A frame is everything you observe right now. Not a flat snapshot — it has depth in time. When you look at a photograph, your frame includes its color, its composition, its texture, what it reminds you of, and how it makes you feel. All at once.

## Contrast

A contrast is a span between opposites.

Light–dark. Warm–cool. Sharp–soft. Simple–complex. Natural–manmade. Each contrast defines an axis along which images differ. Some contrasts are perceptual (brightness, sharpness). Some are semantic (portrait vs. landscape, interior vs. exterior). Some are emergent — patterns that the embedding space discovers on its own and that have no ready name.

A corpus of photographs has many contrasts alive in it simultaneously. Sigil Atlas discovers which ones carry real mass in a given collection and presents them as rideable axes.

## Sigil

A sigil is a pattern you recognize plus your preferences about it.

In Sigil Atlas, your sigil is the sparse vector of contrasts you have explicitly collapsed — the axes where you have declared a direction and a strength. It records what you chose, not what you viewed. Contrasts you haven't ridden are not part of your sigil. They are not zero. They are unmeasured.

When projected onto the atlas, a sigil acts as a gravity field: neighborhoods aligned with your preferences brighten, others dim. The atlas topology never moves. Only the light changes.

## Collapse

A collapse transforms many possibilities into a single choice.

Before you ride a contrast, your preference on that axis exists in superposition — all directions are equally possible. When you ride and choose "more like this" or "less like this," that superposition collapses into a definite direction and strength. The collapse is irreversible within the session (though you can re-ride to update it).

Choosing "skip" during a ride is not a collapse. It records nothing. The axis remains in superposition.

## Superposition

Superposition is the state of an unmeasured contrast.

If you have not ridden an axis, your sigil says nothing about it. This is different from indifference. Indifference would be a measured zero. Superposition is the absence of measurement. Sigil Atlas distinguishes the two because they mean different things: one is a preference, the other is a gap in knowledge.

## Contrast ride

A contrast ride is the measurement instrument.

The system sorts all atlas neighborhoods along one contrast axis, from low to high, and walks you through them in order. At each step you see the neighborhood and declare a direction: approach (more like this), retreat (less like this), or silence (skip). Your aggregate choices produce a band — a direction and strength — that collapses into your sigil.

Rides enforce honesty. When two contrasts are correlated (riding one necessarily drifts the other), the system either restricts the path to a clean subregion, discloses both axes with your consent, or honestly rejects the ride. It never silently presents a multi-axis ride as single-axis.

## Drift

Drift is what happens when contrasts are entangled.

If brightness and color temperature are correlated in a corpus, riding brightness will inadvertently sweep color temperature too. The drift policy detects this and responds transparently — by conditioning, compounding, or rejecting — so that every collapse you make is against the axis you intended.

## Neighborhood

A neighborhood is a cluster of visually similar images.

Sigil Atlas fuses three neighbor graphs (semantic, structural, textural) and applies community detection to find groups where all three kinds of similarity agree. Neighborhoods have names derived from their most prominent contrast (e.g., "night," "macro," "natural") and nest recursively into a four-level hierarchy.

## Atlas

The atlas is the map.

It is a squarified treemap of all neighborhoods, laid out so that nearby neighborhoods are visually related. The layout is deterministic and fixed: it never rearranges based on your preferences. Navigation through it is always reversible. From any depth, one action returns to a wider view. The system never creates stickiness.

---

## Principles

These are the operating rules of the system.

**No passive profiling.** Preference is recorded only from explicit actions. Dwell time, hovering, and viewport exposure are never used.

**Superposition is default.** Uncollapsed contrasts remain unmeasured. The system never infers a preference you haven't declared.

**Honest axes.** When contrasts are correlated, the system either conditions, compounds with consent, or rejects. It never silently conflates two axes.

**No event horizons.** From any depth in the atlas, one action returns to a wider view. The system never creates stickiness or friction to keep you engaged.

**Topology is invariant.** Your sigil changes the lighting, never the layout. The atlas is the same map for everyone. What differs is what glows.

---

*For the broader framework of Attention Language beyond visual perception, see [sigilsnotspells.com](https://sigilsnotspells.com).*

*To explore the atlas: [sigilatlas.fly.dev](https://sigilatlas.fly.dev).*

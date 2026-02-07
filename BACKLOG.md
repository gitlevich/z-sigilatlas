# Sigil Tree - Backlog

Prioritized work items.

1. ~~**Calibration walk polish**~~ DONE (Phase 17) — (a) replaced live radar with progress pie chart (donut ring, one slice per contrast, amber=right, blue=left, gray=skipped), (b) display contrast name label during walk, (c) taste profile toggle on atlas.

2. **Materialize the emergent taste contrast** — the calibration walk discovers coefficients of a personal good-bad axis in contrast space. Currently computed transiently as a dot product during scoring. Make it a first-class contrast: own z-summary per node, own exemplars (top-N / bottom-N images), own name. The individual contrasts are scaffolding; the emergent one is the signal. This is dimensionality reduction from N contrasts to one personally meaningful axis.

3. **README / landing page** — explain the "neighborhood is a sigil" vision

4. **Calibration onboarding text** — add a paragraph in the calibration view explaining what it does and how to use it.

5. **Rename walk to calibration** — rename the concept from "walk" to "calibration" throughout; remap `/walk` path to `/calibration`.

6. **Make category selection visible in atlas** — category radar preferences should visibly affect the atlas display. Currently unclear whether they are reflected.

7. **Evolve the spec** — refine the specification to match what has been built. The spec should evolve as the product does, becoming a sigil of this application: a sigil that, when worn by an LLM, will get it to design an app to this spec within the resolution of the spec. Our secondary deliverable is the evolved spec: the sigil of sigilatlas.

# Changelog

Supersession record for the specification vault. Each entry states what changed, what it replaces, and the reason. Latest wins.

---

**2026-02-08 — Initial vault creation (this commit)**

Created the /spec/ vault as the Markov blanket of Sigil Atlas. All pages derived from repository evidence as of commit e1dfbfb (Phase 20, 244 tests passing).

Supersedes: agents.md as the authoritative specification for observable behavior. agents.md remains valuable as the original design intent and for phases not yet built, but where the implementation diverges from agents.md, the vault pages are authoritative.

Does not supersede: agents.md global invariants (§1.1–§1.4, §2.1–§2.4) which remain in force unless explicitly contradicted by a vault page.

Key divergences from agents.md documented in this vault:
- agents.md §7 (continuous driving) → not implemented; click-to-enter navigation is authoritative (see atlas/navigation.md).
- agents.md §4 (three-door arcade) → supplemented by binary taste walk as primary calibration (see calibration/taste-walk.md).
- agents.md §9 (contrast rides with drift policy) → ride engine is dead code; drift policy not integrated into serving path (see OPEN-QUESTIONS.md).
- agents.md §2.4 (session persistence with build_id rebase) → walk progress persistence implemented with library version check; atlas navigation rebase status unclear (see OPEN-QUESTIONS.md).

Bug fixes incorporated:
- BUG-001 (commit 24b0ab0): taste radar magnitude-only rendering.
- BUG-002 (commit 24b0ab0): Cache-Control: no-store on scoring endpoints.
- BUG-003 (commit 24b0ab0): neutral default initialization for category radar.
- BUG-004 (commit 24b0ab0): sharp category filtering with 0.5 exclusion threshold.

Process rule adopted: any future change to behavior is a spec delta in the appropriate sigil page, plus a CHANGELOG entry here. Code changes are downstream projections.

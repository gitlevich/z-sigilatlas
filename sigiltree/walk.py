"""Calibration Walk: two-tile binary preference elicitation.

A focused, full-screen calibration experience. Two image mosaics shown
side by side (extreme low vs extreme high exemplars). User picks left,
right, or skip. No contrast names shown. Only bipolar contrasts, with
PCA as a conditional extension.

Reuses arcade.py's Choice dataclass and build_sigil() for sigil collapse.
"""

import logging
import time
from dataclasses import dataclass, field

import numpy as np

from sigiltree.arcade import Choice, build_sigil, save_sigil, load_sigil

log = logging.getLogger(__name__)

EXEMPLARS_PER_SIDE = 6
MIN_COLLAPSED_TO_SKIP_PCA = 8


# ---------------------------------------------------------------------------
# Contrast classification
# ---------------------------------------------------------------------------

def classify_contrast(name: str) -> str:
    """Classify a contrast as 'bipolar', 'unipolar', or 'pca'.

    Rules:
      - pca_*         → 'pca'
      - sem_* without '_vs_' → 'unipolar' (no meaningful opposite)
      - everything else       → 'bipolar'
    """
    if name.startswith("pca_"):
        return "pca"
    if name.startswith("sem_") and "_vs_" not in name:
        return "unipolar"
    return "bipolar"


def filter_walk_contrasts(library: dict) -> tuple[list[dict], list[dict]]:
    """Filter and partition contrasts into bipolars and PCA.

    Unipolar semantic categories are excluded entirely.

    Returns:
        (bipolars, pcas) — each sorted by mass descending.
    """
    bipolars = []
    pcas = []
    for c in library["contrasts"]:
        kind = classify_contrast(c["name"])
        if kind == "bipolar":
            bipolars.append(c)
        elif kind == "pca":
            pcas.append(c)
    bipolars.sort(key=lambda c: -c["mass"])
    pcas.sort(key=lambda c: -c["mass"])
    return bipolars, pcas


# ---------------------------------------------------------------------------
# Walk step
# ---------------------------------------------------------------------------

@dataclass
class WalkStep:
    """A single binary comparison step."""
    contrast_id: str
    left_ids: list[str]      # exemplar image IDs shown on left
    right_ids: list[str]     # exemplar image IDs shown on right
    flipped: bool = False    # if True, left shows HIGH and right shows LOW
    is_repeat: bool = False
    step_index: int = 0


# ---------------------------------------------------------------------------
# Walk session
# ---------------------------------------------------------------------------

class WalkSession:
    """Manages the calibration walk flow.

    Phases:
      1. Bipolar contrasts (sorted by mass) — always shown.
      2. Repeats for directional choices — inserted after bipolars.
      3. PCA contrasts — conditional on how many bipolars collapsed.
    """

    MAX_REPEATS_PER_CONTRAST = 1
    REPEAT_PROBABILITY = 0.5

    def __init__(self, contrast_library: dict, user_id: str = "default"):
        self.library = contrast_library
        self.user_id = user_id
        self.library_version = contrast_library["version"]
        self.rng = np.random.RandomState(int(time.time()) % 2**31)

        self.bipolars, self.pcas = filter_walk_contrasts(contrast_library)

        # State
        self.steps: list[WalkStep] = []
        self.choices: list[Choice] = []
        self.current_index: int = 0
        self._used_exemplars: dict[str, dict[str, set]] = {}
        self._bipolar_count: int = 0
        self._repeats_scheduled: bool = False
        self._pca_decided: bool = False

        self._build_bipolar_schedule()

    def _build_bipolar_schedule(self):
        """Build initial schedule from bipolar contrasts only."""
        for c in self.bipolars:
            step = self._make_step(c, is_repeat=False)
            self.steps.append(step)
        self._bipolar_count = len(self.steps)

    def _make_step(self, contrast: dict, is_repeat: bool) -> WalkStep:
        """Create a WalkStep with fresh exemplar images."""
        exemplars = contrast["exemplars"]
        cid = contrast["contrast_id"]

        used = self._used_exemplars.get(cid, {"low": set(), "high": set()})
        low_ids = self._pick_exemplars(exemplars["low"], used.get("low", set()))
        high_ids = self._pick_exemplars(exemplars["high"], used.get("high", set()))

        # Track used exemplars
        self._used_exemplars.setdefault(cid, {"low": set(), "high": set()})
        self._used_exemplars[cid]["low"].update(low_ids)
        self._used_exemplars[cid]["high"].update(high_ids)

        # Randomly flip left/right to prevent positional bias
        flipped = bool(self.rng.random() < 0.5)
        if flipped:
            left_ids, right_ids = high_ids, low_ids
        else:
            left_ids, right_ids = low_ids, high_ids

        return WalkStep(
            contrast_id=cid,
            left_ids=left_ids,
            right_ids=right_ids,
            flipped=flipped,
            is_repeat=is_repeat,
            step_index=len(self.steps),
        )

    def _pick_exemplars(self, pool: list[str], used: set) -> list[str]:
        """Pick EXEMPLARS_PER_SIDE images from pool, preferring unused."""
        k = EXEMPLARS_PER_SIDE
        unused = [eid for eid in pool if eid not in used]
        if len(unused) >= k:
            return list(self.rng.choice(unused, size=k, replace=False))
        if len(pool) >= k:
            return list(self.rng.choice(pool, size=k, replace=False))
        return list(pool)

    # -- Properties ----------------------------------------------------------

    @property
    def is_complete(self) -> bool:
        return self.current_index >= len(self.steps)

    @property
    def current_step(self) -> WalkStep | None:
        if self.is_complete:
            return None
        return self.steps[self.current_index]

    @property
    def progress(self) -> dict:
        return {
            "current": self.current_index,
            "total": len(self.steps),
            "choices_made": len(self.choices),
        }

    # -- Choice recording ----------------------------------------------------

    def record_choice(self, direction: str) -> dict:
        """Record a binary choice and advance.

        Args:
            direction: "left", "right", or "skip"

        Returns:
            dict with "status" ("continue" or "complete") and next step or sigil.
        """
        if self.is_complete:
            return {"status": "complete"}

        step = self.steps[self.current_index]

        # De-flip direction: if the step was flipped, left→right and right→left
        effective_direction = direction
        if direction in ("left", "right") and step.flipped:
            effective_direction = "right" if direction == "left" else "left"

        # Map "skip" to "center" for build_sigil() compatibility
        sigil_direction = "center" if effective_direction == "skip" else effective_direction

        contrast_name = self._contrast_name(step.contrast_id)
        choice = Choice(
            contrast_id=step.contrast_id,
            contrast_name=contrast_name,
            direction=sigil_direction,
            is_repeat=step.is_repeat,
            timestamp=time.time(),
            presentation_index=step.step_index,
        )
        self.choices.append(choice)
        self.current_index += 1

        # Phase transitions
        if self.current_index == self._bipolar_count and not self._repeats_scheduled:
            self._schedule_bipolar_repeats()
            self._repeats_scheduled = True

        if (self.current_index >= len(self.steps)
                and self._repeats_scheduled
                and not self._pca_decided):
            self._maybe_extend_with_pca()
            self._pca_decided = True

        if self.is_complete:
            sigil = build_sigil(
                self.choices, self.library_version, self.user_id
            )
            return {"status": "complete", "sigil": sigil}

        return {
            "status": "continue",
            "step": self.step_to_dict(self.steps[self.current_index]),
            "progress": self.progress,
        }

    def _schedule_bipolar_repeats(self):
        """After all bipolars shown, insert repeats for directional choices."""
        directional_cids = set()
        for c in self.choices:
            if c.direction in ("left", "right"):
                directional_cids.add(c.contrast_id)

        repeats = []
        for cid in directional_cids:
            if self.rng.random() < self.REPEAT_PROBABILITY:
                contrast_data = self._find_contrast(cid)
                if contrast_data:
                    step = self._make_step(contrast_data, is_repeat=True)
                    repeats.append(step)

        self.rng.shuffle(repeats)
        for r in repeats:
            r.step_index = len(self.steps)
            self.steps.append(r)

    def _maybe_extend_with_pca(self):
        """Decide whether to add PCA steps based on bipolar collapse count."""
        sigil = build_sigil(self.choices, self.library_version, self.user_id)
        collapsed = sigil["collapsed_count"]

        if collapsed >= MIN_COLLAPSED_TO_SKIP_PCA:
            log.info(
                "Walk: %d bipolars collapsed (>= %d), skipping PCA",
                collapsed, MIN_COLLAPSED_TO_SKIP_PCA,
            )
            return

        log.info(
            "Walk: only %d bipolars collapsed (< %d), extending with PCA",
            collapsed, MIN_COLLAPSED_TO_SKIP_PCA,
        )
        for c in self.pcas:
            step = self._make_step(c, is_repeat=False)
            self.steps.append(step)

    # -- Helpers -------------------------------------------------------------

    def _contrast_name(self, contrast_id: str) -> str:
        """Look up contrast name by ID."""
        c = self._find_contrast(contrast_id)
        return c["name"] if c else contrast_id

    def _find_contrast(self, contrast_id: str) -> dict | None:
        """Find contrast dict by ID in the full library."""
        for c in self.library["contrasts"]:
            if c["contrast_id"] == contrast_id:
                return c
        return None

    def step_to_dict(self, step: WalkStep) -> dict:
        """Serialize step for JSON response. No contrast names exposed."""
        return {
            "left_ids": step.left_ids,
            "right_ids": step.right_ids,
            "is_repeat": step.is_repeat,
            "step_index": step.step_index,
        }

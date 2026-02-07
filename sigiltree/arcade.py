"""Calibration arcade: three-door collapse for contrast calibration.

Each prompt is a DoorTriplet(contrast_id, left, center, right).
Left/right are extreme quantile exemplar mosaics; center is median band mosaic.
Controls: LEFT chooses left, RIGHT chooses right, FORWARD chooses center.
Center explicitly records nothing. Dwell time is never used.
"""

import json
import hashlib
import logging
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path

import numpy as np

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class DoorTriplet:
    """A single calibration prompt."""
    contrast_id: str
    contrast_name: str
    left_ids: list[str]     # extreme low exemplar image IDs
    center_ids: list[str]   # median band exemplar image IDs
    right_ids: list[str]    # extreme high exemplar image IDs
    is_repeat: bool = False
    presentation_index: int = 0


@dataclass
class Choice:
    """Record of a single user choice."""
    contrast_id: str
    contrast_name: str
    direction: str          # "left", "right", "center"
    is_repeat: bool
    timestamp: float
    presentation_index: int


@dataclass
class SigilEntry:
    """A single collapsed contrast in the sigil."""
    contrast_id: str
    contrast_name: str
    direction: str          # "left" or "right"
    strength: float         # 1.0 for consistent, decayed for partial agreement
    n_presentations: int
    n_agreements: int


@dataclass
class Sigil:
    """User preference sigil from calibration."""
    version: str
    contrast_library_version: str
    user_id: str
    created_at: float
    entries: dict[str, SigilEntry] = field(default_factory=dict)
    choices: list[Choice] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Arcade session builder
# ---------------------------------------------------------------------------

class ArcadeSession:
    """Manages the calibration arcade flow with repeat scheduling."""

    MAX_PROMPTS = 80
    MAX_REPEAT_FRACTION = 0.20
    MIN_REPEAT_GAP = 5
    MAX_REPEATS_PER_CONTRAST = 2
    EXEMPLARS_PER_DOOR = 6  # images shown per door

    def __init__(self, contrast_library: dict, user_id: str = "default"):
        self.library = contrast_library
        self.user_id = user_id
        self.contrasts = contrast_library["contrasts"]
        self.library_version = contrast_library["version"]

        self.rng = np.random.RandomState(int(time.time()) % 2**31)

        # State
        self.prompts: list[DoorTriplet] = []
        self.choices: list[Choice] = []
        self.current_index: int = 0

        # Tracking per contrast
        self._presentation_count: dict[str, int] = {}
        self._repeat_count: dict[str, int] = {}
        self._last_shown: dict[str, int] = {}
        self._directions: dict[str, list[str]] = {}
        self._used_exemplars: dict[str, dict[str, set]] = {}

        self._build_schedule()

    def _build_schedule(self):
        """Build the prompt schedule with interleaved repeats."""
        n_contrasts = len(self.contrasts)

        # Sort by mass descending for initial presentation order
        sorted_contrasts = sorted(self.contrasts, key=lambda c: -c["mass"])

        # First pass: one prompt per contrast (up to budget minus repeat room)
        # Ensure repeats / total <= MAX_REPEAT_FRACTION:
        #   R / (F + R) <= frac => R <= frac * F / (1 - frac)
        max_first_pass = min(n_contrasts, self.MAX_PROMPTS)
        max_repeats_for_first = int(self.MAX_REPEAT_FRACTION * max_first_pass / (1 - self.MAX_REPEAT_FRACTION))
        # Also ensure total fits in budget
        if max_first_pass + max_repeats_for_first > self.MAX_PROMPTS:
            max_repeats_for_first = self.MAX_PROMPTS - max_first_pass
        max_repeats = max(0, max_repeats_for_first)

        first_pass = sorted_contrasts[:max_first_pass]

        schedule = []
        for c in first_pass:
            triplet = self._make_triplet(c, is_repeat=False, index=len(schedule))
            schedule.append(triplet)
            self._presentation_count[c["contrast_id"]] = 1
            self._last_shown[c["contrast_id"]] = len(schedule) - 1
            self._used_exemplars.setdefault(c["contrast_id"], {"low": set(), "median": set(), "high": set()})
            for eid in triplet.left_ids:
                self._used_exemplars[c["contrast_id"]]["low"].add(eid)
            for eid in triplet.center_ids:
                self._used_exemplars[c["contrast_id"]]["median"].add(eid)
            for eid in triplet.right_ids:
                self._used_exemplars[c["contrast_id"]]["high"].add(eid)

        # Repeat slots will be inserted dynamically as choices come in
        self.prompts = schedule
        self._repeat_budget = max_repeats
        self._pending_repeats: list[dict] = []

    def _make_triplet(self, contrast: dict, is_repeat: bool, index: int) -> DoorTriplet:
        """Create a DoorTriplet with fresh exemplar images."""
        exemplars = contrast["exemplars"]
        used = self._used_exemplars.get(contrast["contrast_id"], {"low": set(), "median": set(), "high": set()})

        left_ids = self._pick_exemplars(exemplars["low"], used["low"], self.EXEMPLARS_PER_DOOR)
        center_ids = self._pick_exemplars(exemplars["median"], used["median"], self.EXEMPLARS_PER_DOOR)
        right_ids = self._pick_exemplars(exemplars["high"], used["high"], self.EXEMPLARS_PER_DOOR)

        return DoorTriplet(
            contrast_id=contrast["contrast_id"],
            contrast_name=contrast["name"],
            left_ids=left_ids,
            center_ids=center_ids,
            right_ids=right_ids,
            is_repeat=is_repeat,
            presentation_index=index,
        )

    def _pick_exemplars(self, pool: list[str], used: set, k: int) -> list[str]:
        """Pick k exemplars from pool, preferring unused ones."""
        unused = [eid for eid in pool if eid not in used]
        if len(unused) >= k:
            chosen = list(self.rng.choice(unused, size=k, replace=False))
        elif len(pool) >= k:
            # Fall back to random from full pool
            chosen = list(self.rng.choice(pool, size=k, replace=False))
        else:
            chosen = list(pool)
        return chosen

    @property
    def is_complete(self) -> bool:
        return self.current_index >= len(self.prompts)

    @property
    def current_prompt(self) -> DoorTriplet | None:
        if self.is_complete:
            return None
        return self.prompts[self.current_index]

    @property
    def progress(self) -> dict:
        return {
            "current": self.current_index,
            "total": len(self.prompts),
            "choices_made": len(self.choices),
            "repeats_remaining": self._repeat_budget,
        }

    def record_choice(self, direction: str) -> dict:
        """Record a choice and advance. Returns the next prompt or completion info."""
        if self.is_complete:
            return {"status": "complete"}

        prompt = self.prompts[self.current_index]
        choice = Choice(
            contrast_id=prompt.contrast_id,
            contrast_name=prompt.contrast_name,
            direction=direction,
            is_repeat=prompt.is_repeat,
            timestamp=time.time(),
            presentation_index=prompt.presentation_index,
        )
        self.choices.append(choice)

        # Track directions
        self._directions.setdefault(prompt.contrast_id, [])
        self._directions[prompt.contrast_id].append(direction)

        # Schedule repeat if applicable
        self._maybe_schedule_repeat(prompt, direction)

        self.current_index += 1

        # Insert any pending repeats that are now eligible
        self._insert_eligible_repeats()

        if self.is_complete:
            return {"status": "complete", "sigil": self._build_sigil_data()}

        return {
            "status": "continue",
            "prompt": asdict(self.prompts[self.current_index]),
            "progress": self.progress,
        }

    def _maybe_schedule_repeat(self, prompt: DoorTriplet, direction: str):
        """Decide whether to schedule a repeat for this contrast."""
        cid = prompt.contrast_id
        repeat_count = self._repeat_count.get(cid, 0)

        if repeat_count >= self.MAX_REPEATS_PER_CONTRAST:
            return
        if self._repeat_budget <= 0:
            return

        # Bias: turned contrasts get repeated more; centered get at most 1
        if direction == "center":
            if repeat_count >= 1:
                return
            repeat_prob = 0.3
        else:
            # Find mass for this contrast
            mass = next((c["mass"] for c in self.contrasts if c["contrast_id"] == cid), 0)
            repeat_prob = min(0.8, 0.4 + mass * 0.5)

        if self.rng.random() < repeat_prob:
            # Find the contrast data
            contrast_data = next((c for c in self.contrasts if c["contrast_id"] == cid), None)
            if contrast_data is None:
                return
            self._pending_repeats.append({
                "contrast": contrast_data,
                "earliest": self.current_index + self.MIN_REPEAT_GAP + 1,
                "cid": cid,
            })

    def _insert_eligible_repeats(self):
        """Insert pending repeats that have passed the minimum gap."""
        still_pending = []
        for rep in self._pending_repeats:
            if self.current_index >= rep["earliest"] and self._repeat_budget > 0:
                cid = rep["cid"]
                if self._repeat_count.get(cid, 0) >= self.MAX_REPEATS_PER_CONTRAST:
                    continue

                triplet = self._make_triplet(rep["contrast"], is_repeat=True, index=len(self.prompts))
                self.prompts.insert(self.current_index, triplet)
                self._repeat_count[cid] = self._repeat_count.get(cid, 0) + 1
                self._repeat_budget -= 1

                # Track used exemplars
                self._used_exemplars.setdefault(cid, {"low": set(), "median": set(), "high": set()})
                for eid in triplet.left_ids:
                    self._used_exemplars[cid]["low"].add(eid)
                for eid in triplet.center_ids:
                    self._used_exemplars[cid]["median"].add(eid)
                for eid in triplet.right_ids:
                    self._used_exemplars[cid]["high"].add(eid)
            else:
                still_pending.append(rep)
        self._pending_repeats = still_pending

    def _build_sigil_data(self) -> dict:
        """Compute the sigil from all recorded choices."""
        return build_sigil(self.choices, self.library_version, self.user_id)

    def get_state(self) -> dict:
        """Serialize session state for persistence."""
        return {
            "user_id": self.user_id,
            "library_version": self.library_version,
            "prompts": [asdict(p) for p in self.prompts],
            "choices": [asdict(c) for c in self.choices],
            "current_index": self.current_index,
        }


# ---------------------------------------------------------------------------
# Sigil construction
# ---------------------------------------------------------------------------

def build_sigil(choices: list[Choice], library_version: str, user_id: str) -> dict:
    """Build a sigil from a sequence of choices.

    Only left/right choices produce entries. Center produces nothing.
    Inconsistent repeats (direction disagreement) decay or drop the contrast.
    """
    # Group choices by contrast
    by_contrast: dict[str, list[Choice]] = {}
    for c in choices:
        by_contrast.setdefault(c.contrast_id, [])
        by_contrast[c.contrast_id].append(c)

    entries = {}
    for cid, contrast_choices in by_contrast.items():
        # Filter out center choices - they record nothing
        directional = [c for c in contrast_choices if c.direction != "center"]
        if not directional:
            continue

        # Check consistency
        directions = [c.direction for c in directional]
        unique_dirs = set(directions)

        if len(unique_dirs) == 1:
            # Consistent: full strength
            direction = directions[0]
            strength = 1.0
            n_agreements = len(directions)
        else:
            # Inconsistent: check majority
            left_count = directions.count("left")
            right_count = directions.count("right")

            if left_count == right_count:
                # Perfect disagreement: drop this contrast (cooled)
                log.info("Contrast %s cooled: equal left/right disagreement", cid)
                continue

            # Majority wins but with decayed strength
            if left_count > right_count:
                direction = "left"
                n_agreements = left_count
            else:
                direction = "right"
                n_agreements = right_count

            total = len(directions)
            agreement_ratio = n_agreements / total
            if agreement_ratio < 0.5:
                # Below majority: drop
                log.info("Contrast %s cooled: agreement ratio %.2f < 0.5", cid, agreement_ratio)
                continue

            strength = agreement_ratio  # Decay proportional to disagreement

        contrast_name = directional[0].contrast_name

        entries[cid] = asdict(SigilEntry(
            contrast_id=cid,
            contrast_name=contrast_name,
            direction=direction,
            strength=strength,
            n_presentations=len(contrast_choices),
            n_agreements=n_agreements,
        ))

    sigil = {
        "version": f"sigil_v1_{hashlib.md5(json.dumps(entries, sort_keys=True).encode()).hexdigest()[:8]}",
        "contrast_library_version": library_version,
        "user_id": user_id,
        "created_at": time.time(),
        "entries": entries,
        "total_choices": len(choices),
        "collapsed_count": len(entries),
        "superposed_count": len(set(c.contrast_id for c in choices)) - len(entries),
    }

    return sigil


def save_sigil(sigil: dict, artifact_dir: Path) -> Path:
    """Save sigil to artifact directory."""
    sigil_dir = artifact_dir / "sigils"
    sigil_dir.mkdir(exist_ok=True)
    path = sigil_dir / f"sigil_{sigil['user_id']}.json"
    path.write_text(json.dumps(sigil, indent=2))
    log.info("Saved sigil: %s (%d collapsed, %d superposed)",
             path, sigil["collapsed_count"], sigil["superposed_count"])
    return path


def load_sigil(artifact_dir: Path, user_id: str = "default") -> dict | None:
    """Load sigil from artifact directory."""
    path = artifact_dir / "sigils" / f"sigil_{user_id}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text())


# ---------------------------------------------------------------------------
# Category preferences (radar-based filter)
# ---------------------------------------------------------------------------

def save_category_prefs(prefs: dict, artifact_dir: Path) -> Path:
    """Save category filter preferences to artifact directory.

    Args:
        prefs: {user_id, weights: {contrast_id: float}, ...}
        artifact_dir: Root artifact directory.

    Returns:
        Path to saved file.
    """
    sigil_dir = artifact_dir / "sigils"
    sigil_dir.mkdir(exist_ok=True)
    user_id = prefs.get("user_id", "default")
    path = sigil_dir / f"categories_{user_id}.json"
    path.write_text(json.dumps(prefs, indent=2))
    active = sum(1 for v in prefs.get("weights", {}).values() if v > 0.01)
    log.info("Saved category prefs: %s (%d active categories)", path, active)
    return path


def load_category_prefs(artifact_dir: Path, user_id: str = "default") -> dict | None:
    """Load category filter preferences from artifact directory."""
    path = artifact_dir / "sigils" / f"categories_{user_id}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text())

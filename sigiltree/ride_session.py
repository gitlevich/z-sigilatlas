"""Ride session state tracking and band construction.

Tracks user choices during a contrast ride and builds a sigil band entry
from approach/retreat/silence decisions. Mirrors ArcadeSession semantics:
approach = right, retreat = left, silence = no collapse.
"""

import copy
import logging
import time
from dataclasses import dataclass, asdict

from sigiltree.ride_engine import RidePlan

log = logging.getLogger(__name__)


@dataclass
class RideChoice:
    """Record of a single user choice during a ride."""
    contrast_id: str
    contrast_name: str
    node_id: str
    direction: str          # "approach" | "retreat" | "silence"
    position: int
    timestamp: float


class RideSession:
    """Manages a single ride through sorted atlas nodes."""

    def __init__(self, plan: RidePlan, contrast_id: str):
        self.plan = plan
        self.contrast_id = contrast_id
        self.contrast_name = plan.ride_contrast
        self.path = list(plan.path)
        self.position: int = 0
        self.choices: list[RideChoice] = []

    @property
    def is_complete(self) -> bool:
        return self.position >= len(self.path)

    @property
    def current_node_id(self) -> str | None:
        if self.is_complete:
            return None
        return self.path[self.position]

    @property
    def progress(self) -> dict:
        return {
            "position": self.position,
            "total": len(self.path),
            "choices_made": len(self.choices),
        }

    def record_choice(self, direction: str) -> dict:
        """Record approach/retreat/silence and advance position.

        Args:
            direction: "approach" | "retreat" | "silence"

        Returns:
            {"status": "continue"|"complete", ...}
        """
        if direction not in ("approach", "retreat", "silence"):
            raise ValueError(f"Invalid direction: {direction}")

        if self.is_complete:
            return {"status": "complete", "band": self.build_band()}

        choice = RideChoice(
            contrast_id=self.contrast_id,
            contrast_name=self.contrast_name,
            node_id=self.path[self.position],
            direction=direction,
            position=self.position,
            timestamp=time.time(),
        )
        self.choices.append(choice)
        self.position += 1

        if self.is_complete:
            return {"status": "complete", "band": self.build_band()}

        return {
            "status": "continue",
            "current_node_id": self.current_node_id,
            "progress": self.progress,
        }

    def build_band(self) -> dict | None:
        """Build a sigil band from ride choices.

        Semantics identical to arcade:
        - "approach" maps to "right" (high direction of sweep)
        - "retreat" maps to "left" (low direction)
        - "silence" not counted (keeps superposed)

        Returns sigil entry dict or None if all silence/tied.
        """
        directional = [c for c in self.choices if c.direction != "silence"]
        if not directional:
            return None

        approach_count = sum(1 for c in directional if c.direction == "approach")
        retreat_count = sum(1 for c in directional if c.direction == "retreat")

        if approach_count == retreat_count:
            return None  # tied -> no collapse

        if approach_count > retreat_count:
            direction = "right"
            n_agreements = approach_count
        else:
            direction = "left"
            n_agreements = retreat_count

        total = len(directional)
        strength = n_agreements / total

        if strength < 0.5:
            return None  # below majority threshold

        return {
            "contrast_id": self.contrast_id,
            "contrast_name": self.contrast_name,
            "direction": direction,
            "strength": round(strength, 6),
            "n_presentations": len(self.choices),
            "n_agreements": n_agreements,
        }

    def get_state(self) -> dict:
        """Serialize session state."""
        return {
            "contrast_id": self.contrast_id,
            "contrast_name": self.contrast_name,
            "resolution": self.plan.resolution,
            "path": self.path,
            "position": self.position,
            "is_complete": self.is_complete,
            "choices": [asdict(c) for c in self.choices],
            "progress": self.progress,
        }


def merge_band_into_sigil(sigil: dict, band: dict) -> dict:
    """Merge a ride band into an existing sigil.

    If the contrast already has an entry, combine presentation counts and
    recompute direction/strength. Returns a new sigil dict (no mutation).

    Args:
        sigil: existing sigil dict
        band: ride band entry from build_band()

    Returns:
        Updated sigil dict (new object).
    """
    result = copy.deepcopy(sigil)
    entries = result.get("entries", {})
    cid = band["contrast_id"]

    if cid in entries:
        existing = entries[cid]
        # Combine presentations
        total_n = existing["n_presentations"] + band["n_presentations"]

        # Count agreements per direction
        if existing["direction"] == band["direction"]:
            # Same direction: sum agreements
            total_agree = existing["n_agreements"] + band["n_agreements"]
            direction = existing["direction"]
        else:
            # Opposing directions: larger wins
            if existing["n_agreements"] >= band["n_agreements"]:
                direction = existing["direction"]
                total_agree = existing["n_agreements"]
            else:
                direction = band["direction"]
                total_agree = band["n_agreements"]

        strength = total_agree / total_n if total_n > 0 else 0.0
        if strength < 0.5:
            # Below majority -> remove entry
            del entries[cid]
        else:
            entries[cid] = {
                "contrast_id": cid,
                "contrast_name": band["contrast_name"],
                "direction": direction,
                "strength": round(strength, 6),
                "n_presentations": total_n,
                "n_agreements": total_agree,
            }
    else:
        entries[cid] = {
            "contrast_id": cid,
            "contrast_name": band["contrast_name"],
            "direction": band["direction"],
            "strength": band["strength"],
            "n_presentations": band["n_presentations"],
            "n_agreements": band["n_agreements"],
        }

    result["entries"] = entries
    return result

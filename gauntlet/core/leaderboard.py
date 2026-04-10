"""Persistent leaderboard tracking model rankings over time."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from gauntlet.core.config import LEADERBOARD_FILE, ensure_gauntlet_dir
from gauntlet.core.metrics import ComparisonResult

logger = logging.getLogger("gauntlet.leaderboard")


# Rating constants
K_FACTOR = 32
DEFAULT_RATING = 1500


@dataclass
class ModelRating:
    """Persistent rating for a single model."""

    name: str
    rating: float = DEFAULT_RATING
    wins: int = 0
    losses: int = 0
    draws: int = 0
    avg_tokens_sec: Optional[float] = None
    avg_quality: Optional[float] = None
    total_comparisons: int = 0
    rating_history: list[float] = field(default_factory=list)
    last_seen: Optional[str] = None

    @property
    def win_rate(self) -> float:
        total = self.wins + self.losses + self.draws
        if total == 0:
            return 0.0
        return self.wins / total

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "rating": round(self.rating, 1),
            "wins": self.wins,
            "losses": self.losses,
            "draws": self.draws,
            "avg_tokens_sec": (
                round(self.avg_tokens_sec, 1) if self.avg_tokens_sec else None
            ),
            "avg_quality": (
                round(self.avg_quality, 1) if self.avg_quality else None
            ),
            "total_comparisons": self.total_comparisons,
            "rating_history": [round(e, 1) for e in self.rating_history[-20:]],
            "last_seen": self.last_seen,
            "win_rate": round(self.win_rate * 100, 1),
        }

    @classmethod
    def from_dict(cls, d: dict) -> ModelRating:
        return cls(
            name=d["name"],
            rating=d.get("rating", d.get("elo", DEFAULT_RATING)),
            wins=d.get("wins", 0),
            losses=d.get("losses", 0),
            draws=d.get("draws", 0),
            avg_tokens_sec=d.get("avg_tokens_sec"),
            avg_quality=d.get("avg_quality"),
            total_comparisons=d.get("total_comparisons", 0),
            rating_history=d.get("rating_history", d.get("elo_history", [])),
            last_seen=d.get("last_seen"),
        )


class Leaderboard:
    """Persistent leaderboard stored in ~/.gauntlet/leaderboard.json."""

    def __init__(self):
        self.ratings: dict[str, ModelRating] = {}
        self._load()

    def _load(self) -> None:
        """Load leaderboard from disk."""
        if LEADERBOARD_FILE.exists():
            try:
                with open(LEADERBOARD_FILE) as f:
                    data = json.load(f)
                for entry in data.get("models", []):
                    rating = ModelRating.from_dict(entry)
                    self.ratings[rating.name] = rating
            except (json.JSONDecodeError, KeyError) as e:
                logger.warning("Failed to load leaderboard from disk: %s", e)
                self.ratings = {}

    def _save(self) -> None:
        """Save leaderboard to disk and sync to Supabase if available."""
        ensure_gauntlet_dir()
        data = {
            "models": [r.to_dict() for r in self.sorted_ratings()],
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        with open(LEADERBOARD_FILE, "w") as f:
            json.dump(data, f, indent=2)

        # Sync to public Supabase leaderboard (non-blocking, non-fatal)
        try:
            from gauntlet.mcp.leaderboard_store import sync_from_local, is_available
            if is_available():
                sync_from_local(data)
        except Exception as e:
            logger.warning("Supabase leaderboard sync failed: %s", e)

    def _get_or_create(self, model_name: str) -> ModelRating:
        """Get existing rating or create new one."""
        if model_name not in self.ratings:
            self.ratings[model_name] = ModelRating(name=model_name)
        return self.ratings[model_name]

    def _expected_score(self, rating_a: float, rating_b: float) -> float:
        """Calculate expected score for model A vs model B."""
        return 1.0 / (1.0 + 10 ** ((rating_b - rating_a) / 400))

    def _update_ratings(self, winner: ModelRating, loser: ModelRating, k_scale: float = 1.0) -> None:
        """Update ratings for a win/loss pair."""
        k = K_FACTOR * k_scale
        expected_w = self._expected_score(winner.rating, loser.rating)
        expected_l = self._expected_score(loser.rating, winner.rating)

        winner.rating += k * (1 - expected_w)
        loser.rating += k * (0 - expected_l)

        winner.rating_history.append(winner.rating)
        loser.rating_history.append(loser.rating)

    def update_from_comparison(self, result: ComparisonResult) -> None:
        """Update the leaderboard from a comparison result.

        Updates ratings, win/loss counts, and running averages.
        """
        now = datetime.now(timezone.utc).isoformat()
        models = result.models
        winner_name = result.winner

        # Update per-model stats
        for m in models:
            rating = self._get_or_create(m.model)
            rating.total_comparisons += 1
            rating.last_seen = now

            # Update running average for tokens/sec
            if m.tokens_per_sec:
                if rating.avg_tokens_sec is None:
                    rating.avg_tokens_sec = m.tokens_per_sec
                else:
                    # Exponential moving average
                    rating.avg_tokens_sec = (
                        0.7 * rating.avg_tokens_sec + 0.3 * m.tokens_per_sec
                    )

            # Update running average for quality
            if m.overall_score is not None:
                if rating.avg_quality is None:
                    rating.avg_quality = m.overall_score
                else:
                    rating.avg_quality = (
                        0.7 * rating.avg_quality + 0.3 * m.overall_score
                    )

        # Update ratings based on winner
        # Scale K_FACTOR by 1/n_opponents for multi-model comparisons
        if winner_name and len(models) >= 2:
            n_opponents = len(models) - 1
            winner_rating = self._get_or_create(winner_name)
            winner_rating.wins += 1

            for m in models:
                if m.model != winner_name:
                    loser_rating = self._get_or_create(m.model)
                    loser_rating.losses += 1
                    self._update_ratings(winner_rating, loser_rating, k_scale=1.0 / n_opponents)
        else:
            # No clear winner -- count as draws
            for m in models:
                rating = self._get_or_create(m.model)
                rating.draws += 1
                rating.rating_history.append(rating.rating)

        self._save()

    def sorted_ratings(self) -> list[ModelRating]:
        """Return ratings sorted by rating (highest first)."""
        return sorted(self.ratings.values(), key=lambda r: r.rating, reverse=True)

    def to_dict(self) -> dict:
        """Serialize the full leaderboard."""
        return {
            "models": [r.to_dict() for r in self.sorted_ratings()],
        }

    def get_model_rank(self, model_name: str) -> Optional[int]:
        """Get 1-indexed rank for a model, or None if not found."""
        for i, r in enumerate(self.sorted_ratings(), 1):
            if r.name == model_name:
                return i
        return None

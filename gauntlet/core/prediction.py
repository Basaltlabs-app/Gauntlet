"""Performance prediction for Gauntlet benchmarks.

Predicts how a model will perform on hardware it hasn't been tested on,
using community data from similar models and hardware configurations.
"""

from __future__ import annotations

import math
import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger("gauntlet.prediction")


@dataclass
class PredictionResult:
    """Prediction of model performance on a hardware tier."""
    predicted_score: float          # 0-100
    confidence: float               # 0.0-1.0
    basis: str                      # "direct", "interpolated", "extrapolated"
    similar_models: list[dict]      # [{name, score, similarity}]
    sample_size: int                # how many data points informed this
    prediction_tier: str            # hardware tier predicted for
    notes: str = ""                 # human-readable explanation


def _cosine_similarity(a: dict[str, float], b: dict[str, float]) -> float:
    """Cosine similarity between two score vectors (dict keyed by tier)."""
    common_keys = set(a.keys()) & set(b.keys())
    if len(common_keys) < 2:
        return 0.0

    dot = sum(a[k] * b[k] for k in common_keys)
    mag_a = math.sqrt(sum(a[k] ** 2 for k in common_keys))
    mag_b = math.sqrt(sum(b[k] ** 2 for k in common_keys))

    if mag_a == 0 or mag_b == 0:
        return 0.0
    return dot / (mag_a * mag_b)


class PerformancePredictor:
    """Predict model performance using item-based collaborative filtering.

    The score matrix maps {model_name: {tier: avg_score}}.
    Predictions use cosine similarity between models' score vectors
    across hardware tiers.
    """

    def __init__(self, score_matrix: dict[str, dict[str, float]]):
        self.matrix = score_matrix

    def predict(self, model: str, tier: str, top_k: int = 5) -> PredictionResult:
        """Predict model's score on a hardware tier."""
        # Case 1: Direct data exists
        if model in self.matrix and tier in self.matrix[model]:
            score = self.matrix[model][tier]
            return PredictionResult(
                predicted_score=round(score, 1),
                confidence=1.0,
                basis="direct",
                similar_models=[],
                sample_size=1,  # at least 1, actual count unknown at this layer
                prediction_tier=tier,
                notes=f"Direct measurement available for {model} on {tier}",
            )

        # Case 2: Model has data on other tiers -- find similar models
        if model not in self.matrix:
            return PredictionResult(
                predicted_score=0.0, confidence=0.0, basis="no_data",
                similar_models=[], sample_size=0, prediction_tier=tier,
                notes=f"No community data for {model}",
            )

        model_vec = self.matrix[model]
        if not model_vec:
            return PredictionResult(
                predicted_score=0.0, confidence=0.0, basis="no_data",
                similar_models=[], sample_size=0, prediction_tier=tier,
                notes=f"No scores available for {model}",
            )

        # Find models that have data on the target tier AND share tiers with query model
        candidates = []
        for other_name, other_vec in self.matrix.items():
            if other_name == model:
                continue
            if tier not in other_vec:
                continue

            sim = _cosine_similarity(model_vec, other_vec)
            if sim > 0.5:  # only consider reasonably similar models
                candidates.append({
                    "name": other_name,
                    "score": other_vec[tier],
                    "similarity": round(sim, 3),
                })

        if not candidates:
            # Case 3: Extrapolate from model's own cross-tier data
            avg = sum(model_vec.values()) / len(model_vec)
            return PredictionResult(
                predicted_score=round(avg, 1),
                confidence=0.2,
                basis="extrapolated",
                similar_models=[],
                sample_size=len(model_vec),
                prediction_tier=tier,
                notes=f"No similar models with {tier} data; using cross-tier average",
            )

        # Weighted average by similarity
        candidates.sort(key=lambda c: c["similarity"], reverse=True)
        top = candidates[:top_k]

        total_weight = sum(c["similarity"] for c in top)
        predicted = sum(c["score"] * c["similarity"] for c in top) / total_weight

        # Confidence based on similarity strength and neighbor count
        avg_sim = total_weight / len(top)
        count_factor = min(1.0, len(top) / 3)  # 3+ neighbors = max confidence
        confidence = round(avg_sim * count_factor, 2)

        return PredictionResult(
            predicted_score=round(predicted, 1),
            confidence=min(confidence, 0.95),  # never 1.0 for predictions
            basis="interpolated",
            similar_models=top,
            sample_size=sum(1 for _ in top),
            prediction_tier=tier,
            notes=f"Based on {len(top)} similar models",
        )

    def recommended_tier(
        self, model: str, min_score: float = 75.0
    ) -> dict:
        """Find minimum and recommended hardware tiers for a target score."""
        from gauntlet.core.hardware_tiers import Tier

        tier_names = [t.name for t in Tier]  # EDGE through CLOUD
        predictions = {}

        for tier_name in tier_names:
            pred = self.predict(model, tier_name)
            if pred.confidence > 0:
                predictions[tier_name] = pred

        if not predictions:
            return {"minimum_tier": None, "recommended_tier": None, "predictions": {}}

        # Find minimum tier that meets the score threshold
        min_tier = None
        recommended_tier = None
        pred_dict = {}

        for tier_name in tier_names:
            if tier_name in predictions:
                p = predictions[tier_name]
                pred_dict[tier_name] = {
                    "score": p.predicted_score,
                    "confidence": p.confidence,
                    "basis": p.basis,
                }
                if p.predicted_score >= min_score and min_tier is None:
                    min_tier = tier_name
                if p.predicted_score >= min_score and p.confidence >= 0.5:
                    recommended_tier = tier_name
                    break  # first tier with good confidence above threshold

        # If no recommended found but min exists, recommend one tier up
        if min_tier and not recommended_tier:
            idx = tier_names.index(min_tier)
            recommended_tier = tier_names[min(idx + 1, len(tier_names) - 1)]

        return {
            "minimum_tier": min_tier,
            "recommended_tier": recommended_tier or min_tier,
            "min_score_target": min_score,
            "predictions": pred_dict,
        }

    def quantization_impact(
        self, model_family: str, parameter_size: str
    ) -> dict[str, float]:
        """Predict scores per quantization level for a model family."""
        # Filter matrix for matching family/size pattern
        matching = {}
        family_lower = model_family.lower()
        size_lower = parameter_size.lower()

        for model_name, tiers in self.matrix.items():
            name_lower = model_name.lower()
            if family_lower in name_lower and size_lower in name_lower:
                for tier, score in tiers.items():
                    matching.setdefault(tier, []).append(score)

        return {tier: round(sum(scores) / len(scores), 1)
                for tier, scores in matching.items() if scores}


def build_score_matrix_from_history(history_rows: list[dict]) -> dict[str, dict[str, float]]:
    """Build a score matrix from Supabase history rows.

    Input: list of dicts with model_name, hardware_tier, overall_score
    Output: {model_name: {tier: avg_score}}
    """
    # Accumulate scores
    acc: dict[str, dict[str, list[float]]] = {}
    for row in history_rows:
        model = row.get("model_name", "")
        tier = row.get("hardware_tier", "")
        score = row.get("overall_score")
        if not model or not tier or score is None:
            continue
        acc.setdefault(model, {}).setdefault(tier, []).append(float(score))

    # Average
    matrix = {}
    for model, tiers in acc.items():
        matrix[model] = {
            tier: round(sum(scores) / len(scores), 1)
            for tier, scores in tiers.items()
        }
    return matrix

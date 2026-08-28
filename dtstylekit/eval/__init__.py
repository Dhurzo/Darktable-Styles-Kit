"""Eval package: evaluate & improve the VLM-output -> preset relationship."""

from .dataset import (
    CATEGORIES,
    STYLE_DIRECTIONS,
    EvalCase,
    build_no_reference_cases,
    build_synthetic_pairs,
    classify_image,
)
from .harness import EvalResult, IntentLoss, measure_intent_loss, run_eval_case
from .metrics import (
    LookFidelity,
    LookProfile,
    compare_looks,
    extract_look_profile,
)
from .report import build_report, save_report

__all__ = [
    "CATEGORIES",
    "STYLE_DIRECTIONS",
    "EvalCase",
    "build_no_reference_cases",
    "build_synthetic_pairs",
    "classify_image",
    "EvalResult",
    "IntentLoss",
    "measure_intent_loss",
    "run_eval_case",
    "LookFidelity",
    "LookProfile",
    "compare_looks",
    "extract_look_profile",
    "build_report",
    "save_report",
]

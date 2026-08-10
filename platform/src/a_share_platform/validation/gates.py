"""Code-owned minimum validation requirements.

These are requirements, not fake implementations of the statistical tests.
Experiment services must attach a result for every required key before a model
or factor can be promoted.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ResearchKind(str, Enum):
    FACTOR = "factor"
    STOCK_SELECTION = "stock_selection"
    MARKET_TIMING = "market_timing"
    EVENT = "event"
    PORTFOLIO = "portfolio"
    EXECUTION = "execution"


@dataclass(frozen=True)
class ValidationRequirement:
    key: str
    purpose: str


@dataclass(frozen=True)
class ValidationPolicy:
    research_kind: ResearchKind
    requirements: tuple[ValidationRequirement, ...]

    def __post_init__(self) -> None:
        keys = [item.key for item in self.requirements]
        if not keys or len(keys) != len(set(keys)):
            raise ValueError("validation requirement keys must be non-empty and unique")

    def missing(self, completed_keys: set[str]) -> tuple[str, ...]:
        return tuple(item.key for item in self.requirements if item.key not in completed_keys)


def _requirements(*items: tuple[str, str]) -> tuple[ValidationRequirement, ...]:
    return tuple(ValidationRequirement(key, purpose) for key, purpose in items)


DEFAULT_VALIDATION_POLICIES = {
    ResearchKind.FACTOR: ValidationPolicy(
        ResearchKind.FACTOR,
        _requirements(
            ("pit_leakage", "prove every input was available at the decision time"),
            ("rank_ic", "measure cross-sectional ordering information"),
            ("hac_or_block_bootstrap", "quantify uncertainty under dependent samples"),
            ("quantile_monotonicity", "check ordered portfolio behavior"),
            ("industry_size_neutral", "separate factor alpha from common exposures"),
            ("fama_macbeth", "test incremental cross-sectional explanatory power"),
            ("multiple_testing_fdr", "control false discoveries across factor families"),
            ("walk_forward_oos", "measure performance on untouched future periods"),
            ("turnover_decay", "connect signal decay to rebalance cost"),
        ),
    ),
    ResearchKind.STOCK_SELECTION: ValidationPolicy(
        ResearchKind.STOCK_SELECTION,
        _requirements(
            ("pit_leakage", "prove historical information availability"),
            ("walk_forward_oos", "avoid in-sample strategy selection"),
            ("purged_embargo", "remove overlapping-label leakage where applicable"),
            ("simple_baselines", "compare against equal-weight and simple factors"),
            ("bootstrap_confidence", "quantify uncertainty of return and drawdown"),
            ("parameter_stability", "reject narrow parameter accidents"),
            ("cost_capacity", "show net performance at feasible participation"),
        ),
    ),
    ResearchKind.MARKET_TIMING: ValidationPolicy(
        ResearchKind.MARKET_TIMING,
        _requirements(
            ("walk_forward_oos", "evaluate only future forecast windows"),
            ("probability_calibration", "test whether forecast probabilities mean what they say"),
            ("brier_logloss", "score probabilistic direction forecasts"),
            ("hac_inference", "correct overlapping-horizon uncertainty"),
            ("static_and_risk_baselines", "beat static exposure and passive risk control"),
            ("net_economic_utility", "show value after turnover and drawdown"),
            ("shadow_forward_record", "accumulate immutable live-time forecasts"),
        ),
    ),
    ResearchKind.EVENT: ValidationPolicy(
        ResearchKind.EVENT,
        _requirements(
            ("event_time_integrity", "prove event publication and tradable availability time"),
            ("abnormal_return_model", "remove market, industry, and factor movement"),
            ("event_window_car", "measure cumulative abnormal returns"),
            ("clustered_or_bootstrap_se", "handle dependence and event clustering"),
            ("matched_controls", "compare similar non-event firms"),
            ("overlap_and_multiple_testing", "control overlapping events and discovery bias"),
        ),
    ),
    ResearchKind.PORTFOLIO: ValidationPolicy(
        ResearchKind.PORTFOLIO,
        _requirements(
            ("benchmark_attribution", "separate alpha, beta, industry, and style"),
            ("risk_adjusted_metrics", "report Sharpe, Sortino, Calmar, TE, and IR"),
            ("probabilistic_or_deflated_sharpe", "correct strategy selection bias"),
            ("stress_scenarios", "test tail and regime failures"),
            ("turnover_cost_capacity", "prove net investability"),
            ("dual_engine_reconciliation", "explain results across independent engines"),
        ),
    ),
    ResearchKind.EXECUTION: ValidationPolicy(
        ResearchKind.EXECUTION,
        _requirements(
            ("a_share_rule_replay", "replay T+1, lots, limits, suspensions, and delistings"),
            ("fill_rate", "measure whether intended orders execute"),
            ("implementation_shortfall", "measure decision-to-fill cost"),
            ("slippage_model_error", "calibrate simulated versus observed slippage"),
            ("reconciliation", "close target, order, fill, cash, and holdings ledgers"),
        ),
    ),
}


def policy_for(kind: ResearchKind) -> ValidationPolicy:
    return DEFAULT_VALIDATION_POLICIES[ResearchKind(kind)]


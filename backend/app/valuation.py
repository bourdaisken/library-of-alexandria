"""
valuation
==============

Core collectible-book valuation logic.

This module implements the scenario-based expected-value formula:

    EV(T) = P_m * kappa
            * sum_i [ p_i * M_i(T) * L_i ]
            * sigma(N_h)
            * C * Pi_prov * Pi_plat

Where:
    P_m         : current market price (GBP or any single currency)
    kappa       : calibration coefficient (anchors EV(0) ~= P_m)
    p_i         : scenario probability (must sum to 1)
    M_i(T)      : appreciation multiplier for scenario i at time T
                  M_i(T) = 1 + g_i * T^beta_i
    L_i         : scenario-conditional liquidity factor in [0.5, 1.0]
    sigma(N_h)  : scarcity factor from library holdings count N_h
    C           : condition factor (0.2 to 3.0)
    Pi_prov     : provenance premium (1.0 to 5.0)
    Pi_plat     : platform stability factor (0.6 to 1.0)

IMPORTANT EPISTEMIC NOTE
------------------------
This is a SCORING tool, not a trained predictor. Parameters are hand-tuned
defaults. Outputs are dimensioned ranges that reflect scenario variance, not
calibrated confidence intervals. Treat results as relative rankings and
asymmetric-upside indicators, not as price forecasts.

Functions
---------
- expected_value: compute EV(T) and a confidence-style range.
- calibration_coefficient: compute kappa so EV(0) ~= P_m.
- scarcity_factor: scarcity from library holdings.
- multiplier: scenario-specific time-evolution multiplier.
- valuate: high-level convenience wrapper combining all factors.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Dict, Optional
import math


# ---------------------------------------------------------------------------
# Default parameter sets
# ---------------------------------------------------------------------------

# Scenario keys: 1=Plateau, 2=Niche, 3=Breakout, 4=Canonical
SCENARIO_NAMES: Dict[int, str] = {
    1: "Plateau / Obscurity",
    2: "Niche Authority",
    3: "Breakout Success",
    4: "Canonical / Historic",
}

# Default prior probabilities for a generic unknown book.
# These should be overridden using observable metadata (see assign_priors).
DEFAULT_PROBS: Dict[int, float] = {1: 0.65, 2: 0.25, 3: 0.08, 4: 0.02}

# Growth constants g_i (annualised, before T^beta acceleration)
DEFAULT_GROWTH: Dict[int, float] = {1: 0.02, 2: 0.08, 3: 0.25, 4: 0.55}

# Acceleration coefficients beta_i (T raised to this power)
DEFAULT_BETA: Dict[int, float] = {1: 1.0, 2: 1.2, 3: 1.5, 4: 2.0}

# Scenario-conditional liquidity
DEFAULT_LIQUIDITY: Dict[int, float] = {1: 0.55, 2: 0.70, 3: 0.85, 4: 0.95}

# Hard caps on multipliers to prevent canonical tail from dominating EV.
# M_4 in particular can blow up; cap at 200x for practical computation.
MULTIPLIER_CAPS: Dict[int, float] = {1: 5.0, 2: 15.0, 3: 50.0, 4: 200.0}


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class BookInputs:
    """All inputs required for a single-book valuation."""

    market_price: float                  # P_m, current market price
    horizon_years: float = 10.0          # T

    # Copy-specific
    condition: float = 1.0               # C, in [0.2, 3.0]
    provenance: float = 1.0              # Pi_prov, in [1.0, 5.0]
    platform: float = 1.0                # Pi_plat, in [0.6, 1.0]

    # Scarcity proxy
    library_holdings: Optional[int] = None   # N_h, from Open Library / WorldCat

    # Scenario model (override defaults if needed)
    probs: Dict[int, float] = field(default_factory=lambda: dict(DEFAULT_PROBS))
    growth: Dict[int, float] = field(default_factory=lambda: dict(DEFAULT_GROWTH))
    beta: Dict[int, float] = field(default_factory=lambda: dict(DEFAULT_BETA))
    liquidity: Dict[int, float] = field(default_factory=lambda: dict(DEFAULT_LIQUIDITY))

    # Scarcity tuning
    alpha: float = 0.35
    holdings_reference: float = 100.0    # N_0 reference scale for sigma

    def validate(self) -> None:
        """Raise ValueError if inputs are out of acceptable ranges."""
        if self.market_price <= 0:
            raise ValueError("market_price must be positive")
        if self.horizon_years < 0:
            raise ValueError("horizon_years must be non-negative")
        if not (0.2 <= self.condition <= 3.0):
            raise ValueError(f"condition {self.condition} outside [0.2, 3.0]")
        if not (1.0 <= self.provenance <= 5.0):
            raise ValueError(f"provenance {self.provenance} outside [1.0, 5.0]")
        if not (0.6 <= self.platform <= 1.0):
            raise ValueError(f"platform {self.platform} outside [0.6, 1.0]")
        if self.library_holdings is not None and self.library_holdings < 0:
            raise ValueError("library_holdings cannot be negative")
        if not (0.1 <= self.alpha <= 1.0):
            raise ValueError(f"alpha {self.alpha} outside [0.1, 1.0]")

        prob_sum = sum(self.probs.values())
        if not math.isclose(prob_sum, 1.0, abs_tol=1e-6):
            raise ValueError(f"probabilities must sum to 1, got {prob_sum}")
        for s in (1, 2, 3, 4):
            for d, name in (
                (self.probs, "probs"),
                (self.growth, "growth"),
                (self.beta, "beta"),
                (self.liquidity, "liquidity"),
            ):
                if s not in d:
                    raise ValueError(f"{name} missing scenario {s}")


@dataclass
class ValuationResult:
    """Output of a valuation run."""

    expected_value: float
    range_low: float
    range_high: float
    horizon_years: float

    # Decomposition
    scenario_contributions: Dict[int, float]
    scenario_evs: Dict[int, float]
    kappa: float
    scarcity_factor: float
    condition: float
    provenance: float
    platform: float

    # Diagnostics
    notes: list = field(default_factory=list)

    def as_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Component functions
# ---------------------------------------------------------------------------

def multiplier(scenario: int, horizon_years: float,
               growth: Dict[int, float] = None,
               beta: Dict[int, float] = None,
               cap: bool = True) -> float:
    """
    Compute the appreciation multiplier M_i(T) = 1 + g_i * T^beta_i,
    optionally capped to prevent unbounded canonical tail.

    Parameters
    ----------
    scenario : int (1-4)
    horizon_years : float, T
    growth, beta : dicts overriding defaults
    cap : bool, apply MULTIPLIER_CAPS if True

    Returns
    -------
    float : M_i(T), >= 1.0
    """
    if scenario not in (1, 2, 3, 4):
        raise ValueError(f"scenario must be 1-4, got {scenario}")
    if horizon_years < 0:
        raise ValueError("horizon_years must be non-negative")

    g = (growth or DEFAULT_GROWTH)[scenario]
    b = (beta or DEFAULT_BETA)[scenario]
    raw = 1.0 + g * (horizon_years ** b)

    if cap:
        raw = min(raw, MULTIPLIER_CAPS[scenario])
    return raw


def scarcity_factor(library_holdings: Optional[int],
                    alpha: float = 0.35,
                    holdings_reference: float = 100.0) -> float:
    """
    Scarcity multiplier sigma(N_h).

    Uses a smooth function bounded between ~1 (commodity) and 1+alpha*K (rare),
    where K depends on how far below the reference scale the holdings sit.

    Formula:
        sigma(N_h) = 1 + alpha * (N_0 / (N_h + N_0))^2

    Properties:
    - N_h = 0      -> 1 + alpha            (maximum scarcity bump)
    - N_h = N_0    -> 1 + alpha * 0.25
    - N_h -> inf   -> 1                    (commodity book, no premium)
    - Smooth, monotonic, bounded.

    If library_holdings is None, returns 1.0 (no scarcity adjustment).
    """
    if library_holdings is None:
        return 1.0
    if library_holdings < 0:
        raise ValueError("library_holdings cannot be negative")

    ratio = holdings_reference / (library_holdings + holdings_reference)
    return 1.0 + alpha * (ratio ** 2)


def calibration_coefficient(inputs: BookInputs) -> float:
    """
    Compute kappa to normalise the scenario-weighted base at T=0 to 1.

    kappa = 1 / sum_i (p_i * L_i)

    Important: kappa does NOT include per-copy factors (sigma, C, Pi_prov,
    Pi_plat). This means EV(0) is NOT generally equal to market_price; rather:

        EV(0) = P_m * sigma * C * Pi_prov * Pi_plat

    Interpretation: P_m is the price of a STANDARD COPY (fine condition,
    not signed, average provenance, neutral platform). The per-copy
    multipliers adjust the value of THIS specific copy relative to the
    standard. For a perfectly standard copy (all factors = 1), EV(0) = P_m.

    This is intentional: it lets the model express "this signed first
    edition is worth more than the £25 going rate for a standard copy."

    Earlier versions absorbed all per-copy factors into kappa, which made
    them mathematically irrelevant. The test suite catches this.

    Returns
    -------
    float : kappa, the calibration coefficient.
    """
    base_sum = sum(
        inputs.probs[s] * inputs.liquidity[s] for s in (1, 2, 3, 4)
    )
    if base_sum <= 0:
        raise ValueError("Scenario base sum is non-positive; check inputs")
    return 1.0 / base_sum


def expected_value(inputs: BookInputs) -> ValuationResult:
    """
    Compute EV(T) and a scenario-variance-based range.

    Returns a ValuationResult with full decomposition.
    """
    inputs.validate()

    kappa = calibration_coefficient(inputs)
    sigma = scarcity_factor(
        inputs.library_holdings, inputs.alpha, inputs.holdings_reference
    )

    # Per-scenario EV contributions
    scenario_evs: Dict[int, float] = {}
    scenario_contribs: Dict[int, float] = {}

    base_factors = (
        kappa
        * sigma
        * inputs.condition
        * inputs.provenance
        * inputs.platform
    )

    for s in (1, 2, 3, 4):
        m = multiplier(s, inputs.horizon_years, inputs.growth, inputs.beta)
        # EV if scenario s materialises with certainty
        ev_s = inputs.market_price * base_factors * m * inputs.liquidity[s]
        scenario_evs[s] = ev_s
        # Probability-weighted contribution to overall EV
        scenario_contribs[s] = inputs.probs[s] * ev_s

    ev = sum(scenario_contribs.values())

    # Range: use the 1st and 4th scenario EVs as low/high bounds,
    # which represents the realistic dispersion under the model.
    # This is NOT a calibrated confidence interval.
    range_low = min(scenario_evs.values())
    range_high = max(scenario_evs.values())

    notes = []
    if inputs.library_holdings is None:
        notes.append(
            "No library_holdings provided; scarcity factor defaulted to 1.0."
        )
    if inputs.probs[4] > 0.05:
        notes.append(
            "Canonical-scenario probability > 5%; EV may be dominated by tail."
        )
    if inputs.platform < 0.85:
        notes.append(
            "Heavy platform dependency assumed; demand exposed to platform risk."
        )

    return ValuationResult(
        expected_value=ev,
        range_low=range_low,
        range_high=range_high,
        horizon_years=inputs.horizon_years,
        scenario_contributions=scenario_contribs,
        scenario_evs=scenario_evs,
        kappa=kappa,
        scarcity_factor=sigma,
        condition=inputs.condition,
        provenance=inputs.provenance,
        platform=inputs.platform,
        notes=notes,
    )


# ---------------------------------------------------------------------------
# Heuristic prior assignment from metadata
# ---------------------------------------------------------------------------

def assign_priors_from_metadata(
    publication_year: Optional[int] = None,
    edition_count: Optional[int] = None,
    is_first_edition: bool = False,
    is_signed: bool = False,
    publisher_tier: str = "unknown",   # "major", "indie", "self", "unknown"
) -> Dict[int, float]:
    """
    Heuristic for setting scenario priors from observable metadata.

    This is INTENTIONALLY simple. It encodes plausible directional adjustments
    rather than learned probabilities. Refine with empirical data when available.

    Rules of thumb encoded:
    - Older surviving books with few editions are more likely to be in
      Niche or Breakout scenarios (survivorship bias).
    - First editions modestly shift mass from Plateau to Niche.
    - Signed copies modestly shift mass toward Breakout/Canonical.
    - Self-published is most likely Plateau.
    - Major-publisher backlist with many editions is likely Niche/Plateau split.

    Returns
    -------
    Dict[int, float] : normalised probabilities summing to 1.
    """
    p = dict(DEFAULT_PROBS)  # start from generic prior

    # Survivorship adjustment based on age
    if publication_year is not None:
        age = max(0, 2026 - publication_year)
        if age > 50:
            # Surviving 50+ years suggests at least niche significance
            p[1] -= 0.15
            p[2] += 0.10
            p[3] += 0.04
            p[4] += 0.01
        elif age > 20:
            p[1] -= 0.08
            p[2] += 0.06
            p[3] += 0.02

    # First edition premium (signal of collectibility intent)
    if is_first_edition:
        p[1] -= 0.05
        p[2] += 0.04
        p[3] += 0.01

    # Signed copies skew toward higher scenarios
    if is_signed:
        p[1] -= 0.04
        p[2] += 0.02
        p[3] += 0.015
        p[4] += 0.005

    # Publisher tier
    if publisher_tier == "self":
        p[1] += 0.10
        p[2] -= 0.05
        p[3] -= 0.04
        p[4] -= 0.01
    elif publisher_tier == "major":
        # Major publisher: more chance of breakout, but also more chance
        # of mass-market commodity status. Net: modest shift to mid scenarios.
        p[1] -= 0.03
        p[2] += 0.02
        p[3] += 0.01

    # Edition count: many editions = wide availability = lower scarcity premium
    if edition_count is not None and edition_count > 10:
        p[1] += 0.05
        p[2] -= 0.03
        p[3] -= 0.015
        p[4] -= 0.005

    # Clamp to [0.001, 0.99] then normalise
    p = {k: max(0.001, min(0.99, v)) for k, v in p.items()}
    total = sum(p.values())
    p = {k: v / total for k, v in p.items()}
    return p


# ---------------------------------------------------------------------------
# Top-level convenience wrapper
# ---------------------------------------------------------------------------

def valuate(
    market_price: float,
    horizon_years: float = 10.0,
    condition: float = 1.0,
    is_signed: bool = False,
    has_dust_jacket: bool = True,
    is_first_edition: bool = False,
    platform_dependency: str = "low",   # "low", "moderate", "heavy"
    library_holdings: Optional[int] = None,
    publication_year: Optional[int] = None,
    edition_count: Optional[int] = None,
    publisher_tier: str = "unknown",
) -> ValuationResult:
    """
    High-level wrapper that translates user-facing inputs into the formula.

    Parameters
    ----------
    market_price : float
        Current price you would pay or sell at, in your chosen currency.
    horizon_years : float
        Years into the future to value at.
    condition : float
        0.2 (damaged) to 3.0 (mint+). Typical Fine = 1.0.
    is_signed : bool
        Signed by author? Increases provenance.
    has_dust_jacket : bool
        Dust jacket present (matters for modern firsts). Affects condition.
    is_first_edition : bool
        Adjusts scenario priors and provenance modestly.
    platform_dependency : str
        For creator/influencer books, demand is exposed to platform risk.
        "low" (academic/established author) -> 1.0
        "moderate" -> 0.9
        "heavy" (influencer with single platform) -> 0.75
    library_holdings : int, optional
        N_h, library holding count from Open Library or WorldCat.
    publication_year, edition_count, publisher_tier
        Metadata used to set scenario priors.
    """
    # Translate categoricals
    plat_map = {"low": 1.0, "moderate": 0.9, "heavy": 0.75}
    pi_plat = plat_map.get(platform_dependency, 1.0)

    pi_prov = 1.0
    if is_signed:
        pi_prov *= 1.5
    if is_first_edition:
        pi_prov *= 1.1

    # Dust jacket: for modern firsts, missing DJ cuts condition substantially.
    eff_condition = condition * (0.7 if not has_dust_jacket else 1.0)
    eff_condition = max(0.2, min(3.0, eff_condition))

    priors = assign_priors_from_metadata(
        publication_year=publication_year,
        edition_count=edition_count,
        is_first_edition=is_first_edition,
        is_signed=is_signed,
        publisher_tier=publisher_tier,
    )

    inputs = BookInputs(
        market_price=market_price,
        horizon_years=horizon_years,
        condition=eff_condition,
        provenance=pi_prov,
        platform=pi_plat,
        library_holdings=library_holdings,
        probs=priors,
    )
    return expected_value(inputs)

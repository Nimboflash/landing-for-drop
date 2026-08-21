"""Pre-T0 wallet features, the look-ahead guard, and standardisation.

Pre-registration §6.4 · §6.6.

Everything in this file exists to serve one sentence: **matching uses pre-T0 information only.**

That sentence has no natural enforcement point. A forward-period feature does not crash, does not
produce an implausible number, and does not disturb the covariate balance table — the matched sets
look excellent, precisely because a feature that has already seen the outcome matches the outcome
well. The whole result is void and nothing in it says so. So the guard is structural: a feature
record carries the block (and, when it has one, the timestamp) it was computed at, and
:func:`require_pre_t0` refuses the record rather than trusting that the caller sliced correctly.

``>=`` and not ``>``. A feature computed *at* T0 has already seen T0's state, and T0 is the
instant the selection decision is made. Half a block of hindsight is still hindsight.

The categorical dimension is kept out of the numeric vector on purpose. ``account_type`` is one of
the ten §6.6 dimensions, but standardising a category code would make ``SAFE`` twice as far from
``EOA`` as ``ERC4337`` is, on nothing but enum declaration order. It is matched exactly instead,
and carries its own field so a caller cannot smuggle it in as a number.
"""

from dataclasses import dataclass, field
from decimal import Decimal, localcontext
from typing import Dict, Optional

from contracts import (
    CALCULATION_CONTEXT,
    MATCHING_DIMENSIONS,
    AccountType,
    LookAheadViolation,
    calc,
    divide,
    require_finite,
)

ZERO = Decimal("0")

#: The one dimension of the ten that is a category rather than a magnitude.
CATEGORICAL_DIMENSION = "account_type"

#: The nine that are magnitudes, in the frozen §6.6 order. Derived rather than restated, so a
#: change to ``MATCHING_DIMENSIONS`` cannot leave a second list quietly disagreeing with it.
NUMERIC_DIMENSIONS = tuple(d for d in MATCHING_DIMENSIONS if d != CATEGORICAL_DIMENSION)


def _require_int(value, name):
    """Blocks and UTC seconds are ``int`` by seam rule — never Decimal, never float."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(
            "{} must be an int; block numbers and UTC seconds are int by seam rule. Got {}.".format(
                name, type(value).__name__
            )
        )
    return value


@dataclass(frozen=True)
class WalletFeatures:
    """One wallet's ten §6.6 matching dimensions, with the provenance needed to prove they are pre-T0.

    ``values`` holds the nine numeric dimensions. Units are the caller's and are never converted
    here: standardisation divides each dimension by its own universe standard deviation, so a
    dimension measured in dollars and one measured in days become comparable without this module
    ever needing to know which was which.

    ``as_of_block`` is required. ``as_of_timestamp`` is optional, but a timestamp with no T0
    timestamp to check it against is refused rather than skipped — see :func:`require_pre_t0`.

    ``dimension_blocks`` / ``dimension_timestamps`` are optional per-dimension provenance. They
    exist because the failure this module guards against is *one* forward-period feature among ten.
    A single wallet-level ``as_of_block`` cannot express that one dimension was recomputed later,
    so a caller whose feature pipeline knows per-dimension provenance can hand it over and have it
    checked.
    """

    wallet: str
    account_type: AccountType
    values: Dict[str, Decimal]
    as_of_block: int
    as_of_timestamp: Optional[int] = None
    dimension_blocks: Dict[str, int] = field(default_factory=dict)
    dimension_timestamps: Dict[str, int] = field(default_factory=dict)

    def __post_init__(self):
        object.__setattr__(self, "wallet", (self.wallet or "").lower())
        if not self.wallet:
            raise ValueError("a feature record must name its wallet")
        if not isinstance(self.account_type, AccountType):
            raise TypeError(
                "account_type must be a contracts.AccountType, got {}. It is matched exactly, "
                "not standardised, so a bare string would silently become an unmatchable "
                "category.".format(type(self.account_type).__name__)
            )

        _require_int(self.as_of_block, "as_of_block")
        if self.as_of_timestamp is not None:
            _require_int(self.as_of_timestamp, "as_of_timestamp")

        if CATEGORICAL_DIMENSION in self.values:
            raise ValueError(
                "'{0}' is categorical and belongs in the account_type field, not in values. A "
                "numeric encoding of it would make the distance between two categories depend on "
                "enum declaration order.".format(CATEGORICAL_DIMENSION)
            )
        missing = [d for d in NUMERIC_DIMENSIONS if d not in self.values]
        if missing:
            raise ValueError(
                "wallet {} is missing matching dimension(s): {}. §6.6 matches on all ten; a "
                "silently absent dimension is an unmatched confounder, not a smaller "
                "model.".format(self.wallet, ", ".join(missing))
            )
        unknown = sorted(set(self.values) - set(NUMERIC_DIMENSIONS))
        if unknown:
            raise ValueError(
                "unknown matching dimension(s) for wallet {}: {}".format(
                    self.wallet, ", ".join(unknown)
                )
            )

        # calc() refuses float on sight; require_finite refuses NaN and infinity, which would
        # compare False against every caliper and read as an ordinary poor match.
        coerced = {}
        for dimension in NUMERIC_DIMENSIONS:
            coerced[dimension] = require_finite(
                self.values[dimension], "{}.{}".format(self.wallet, dimension)
            )
        object.__setattr__(self, "values", coerced)

        for label, provenance in (
            ("dimension_blocks", self.dimension_blocks),
            ("dimension_timestamps", self.dimension_timestamps),
        ):
            stray = sorted(set(provenance) - set(MATCHING_DIMENSIONS))
            if stray:
                raise ValueError(
                    "{} names dimension(s) that are not §6.6 dimensions: {}".format(
                        label, ", ".join(stray)
                    )
                )
            for dimension, value in provenance.items():
                _require_int(value, "{}[{}]".format(label, dimension))
        object.__setattr__(self, "dimension_blocks", dict(self.dimension_blocks))
        object.__setattr__(self, "dimension_timestamps", dict(self.dimension_timestamps))

    def vector(self):
        """The nine numeric dimensions in frozen order."""
        return tuple(self.values[d] for d in NUMERIC_DIMENSIONS)


def require_pre_t0(feature, t0_block, t0_timestamp=None):
    """Refuse a feature record that carries any block or timestamp at or after T0.

    Four distinct refusals, and the third is the one that is easy to leave out:

    1. a wallet-level block at or after T0;
    2. a per-dimension block at or after T0 — the "one forward feature among ten" case;
    3. a timestamp with no ``t0_timestamp`` supplied to check it against. An unverifiable claim
       is not a passing one. Skipping the check here would mean a caller could disable half the
       guard by omitting an argument, which is the opposite of "check, do not trust the caller";
    4. a timestamp at or after T0.
    """
    _require_int(t0_block, "t0_block")
    if t0_timestamp is not None:
        _require_int(t0_timestamp, "t0_timestamp")

    def refuse(what, observed, boundary, unit):
        raise LookAheadViolation(
            "wallet {} carries {} at {} {}, at or after T0 {} {}. Matching uses pre-T0 "
            "information only (§6.4): a feature computed at T0 has already seen T0, so the "
            "boundary is >= and not >. A forward-period feature does not crash and does not look "
            "wrong — it makes the matched sets fit the outcome and voids every number downstream "
            "of them.".format(feature.wallet, what, unit, observed, unit, boundary)
        )

    if feature.as_of_block >= t0_block:
        refuse("as_of_block", feature.as_of_block, t0_block, "block")
    for dimension in sorted(feature.dimension_blocks):
        observed = feature.dimension_blocks[dimension]
        if observed >= t0_block:
            refuse("dimension_blocks[{}]".format(dimension), observed, t0_block, "block")

    # Namespaced, not merged bare, and the reason is **legibility rather than a closed hole** —
    # an earlier version of this comment said otherwise and was measurably wrong. It claimed that
    # merged bare, a dimension named "as_of_timestamp" would displace the wallet's own stamp and
    # one of the four look-ahead checks would vanish on a key collision. That input never reaches
    # here: WalletFeatures.__post_init__ refuses any dimension_timestamps key outside
    # MATCHING_DIMENSIONS, and "as_of_timestamp" is not one of the ten, so the record cannot be
    # constructed. Pinned by test_a_provenance_key_that_could_collide_cannot_be_constructed.
    #
    # What the bracketed form does buy, and it is the whole of it: every label in the two refusals
    # below names the field the stamp came from, so "capital_deployed is at second N" reads as
    # dimension_timestamps[capital_deployed] and cannot be confused with the wallet-level stamp in
    # a message. It matches how the block loop above already names its findings.
    stamps = {
        "dimension_timestamps[{}]".format(dimension): value
        for dimension, value in feature.dimension_timestamps.items()
    }
    if feature.as_of_timestamp is not None:
        stamps["as_of_timestamp"] = feature.as_of_timestamp
    if stamps and t0_timestamp is None:
        raise LookAheadViolation(
            "wallet {} carries timestamp(s) ({}) but no t0_timestamp was supplied to check them "
            "against. A timestamp that cannot be verified is refused rather than ignored — a "
            "guard a caller can switch off by omitting an argument is not a guard.".format(
                feature.wallet, ", ".join(sorted(stamps))
            )
        )
    for label in sorted(stamps):
        observed = stamps[label]
        if observed >= t0_timestamp:
            refuse(label, observed, t0_timestamp, "second")


# -- standardisation ------------------------------------------------------------


@dataclass(frozen=True)
class Standardisation:
    """One dimension's location and scale, measured once over the frozen T0 universe.

    Measured over the *universe*, not over the selected wallets or the controls. The scale has to
    be the same fixed ruler for every wallet, or the distance between a selected wallet and a
    control would depend on which group each happened to be in.
    """

    dimension: str
    mean: Decimal
    sd: Decimal
    n: int

    def z(self, value):
        """Standardise one value. A zero-variance dimension contributes nothing, and says so.

        ``divide`` refuses a zero denominator rather than returning one, which is correct — but a
        dimension that is constant across the whole frozen universe is not an error, it is a
        dimension that distinguishes nobody. Every wallet gets 0 and the distance is unaffected.
        The dimension still appears in the balance table, so it is visibly present rather than
        quietly dropped.
        """
        if self.sd == 0:
            return ZERO
        with localcontext(CALCULATION_CONTEXT):
            return +(divide(calc(value) - self.mean, self.sd))


def mean_of(values):
    """Arithmetic mean under the frozen context. Raises on an empty sequence rather than 0/0."""
    items = [calc(v) for v in values]
    if not items:
        raise ValueError("the mean of an empty sequence is undefined, not zero")
    with localcontext(CALCULATION_CONTEXT):
        total = ZERO
        for item in items:
            total += item
        return +(divide(total, len(items)))


def variance_of(values, mean=None):
    """**Population** variance — divide by n, not n-1.

    Pinned rather than chosen per call site. The n-versus-n-1 difference is immaterial to a 0.10
    balance target, but mixing the two conventions between the standardisation and the balance
    denominator is exactly the sort of unpinned degree of freedom that makes two correct
    implementations disagree, which is what the frozen numeric policy exists to prevent.
    """
    items = [calc(v) for v in values]
    if not items:
        raise ValueError("the variance of an empty sequence is undefined, not zero")
    centre = mean_of(items) if mean is None else calc(mean)
    with localcontext(CALCULATION_CONTEXT):
        total = ZERO
        for item in items:
            deviation = item - centre
            total += deviation * deviation
        return +(divide(total, len(items)))


def sqrt_of(value):
    """Square root under the frozen 38-digit context, never Python's default 28."""
    with localcontext(CALCULATION_CONTEXT):
        return +(calc(value).sqrt())


def standardise(features):
    """Location and scale for each numeric dimension, over the frozen T0 universe.

    :param features: iterable of :class:`WalletFeatures` — the whole universe, selected wallets
        included. §6.4 freezes the universe at T0 and draws controls from it, so the universe is
        the population the ruler is calibrated on.
    """
    records = list(features)
    if not records:
        raise ValueError("cannot standardise an empty universe")
    out = {}
    for dimension in NUMERIC_DIMENSIONS:
        column = [record.values[dimension] for record in records]
        mean = mean_of(column)
        out[dimension] = Standardisation(
            dimension=dimension,
            mean=mean,
            sd=sqrt_of(variance_of(column, mean)),
            n=len(records),
        )
    return out


def z_vector(feature, standardisation):
    """The nine standardised coordinates, in frozen dimension order."""
    return tuple(standardisation[d].z(feature.values[d]) for d in NUMERIC_DIMENSIONS)


def squared_distance(left, right):
    """Squared Euclidean distance in standardised space.

    Squared, because ranking on it is identical to ranking on the distance itself and it avoids a
    square root per candidate pair — with 1,000 selected wallets against a six-figure universe
    that is the whole cost of the matching step.

    Dimensions are weighted equally. §6.6 pre-registers no weights, and inventing a weight vector
    here would be an unregistered parameter that silently decides which confounder matters most.
    """
    if len(left) != len(right):
        raise ValueError("cannot compare standardised vectors of different lengths")
    with localcontext(CALCULATION_CONTEXT):
        total = ZERO
        for a, b in zip(left, right):
            gap = a - b
            total += gap * gap
        return +total


def distance(left, right):
    """Standardised Euclidean distance. Reported; ranking uses the squared form."""
    return sqrt_of(squared_distance(left, right))

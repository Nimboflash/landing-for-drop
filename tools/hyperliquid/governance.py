"""What a Hyperliquid run may not do to the Phase 0 state machine, and where that refusal lives.

The rule
--------

A Hyperliquid run may **execute** stages and **record** their outcomes. It may not leave the
governance machine in a state that claims Phase 0 progressed. Those are different claims and
``phase0`` already separates them: :func:`phase0.execution.execute_stage` calls the runner at step 4
and performs the transition at step 6, and the run record, the audit entry and the stage result are
all written whether or not step 6 happens. "Execute but do not advance" is the existing sequence
with one step withheld.

Why this is a *different* argument from mockchain's, and a sharper one
-----------------------------------------------------------------------

:mod:`tools.mockchain.governance` refuses advancement because its data was never measured — a null
built over generated wallets is a distribution of nothing. That argument does not apply here and it
would be dishonest to borrow it. **This data is a measurement.** It was read off a real venue at a
real time, the wallets are real, the fills are real, and a reader can check any row of the committed
recording against Hyperliquid's own explorer.

The objection is not that the number is fake. It is that the number is **about the wrong thing, and
was chosen after the fact**, and that is worse in one specific way: a synthetic number is obviously
not a measurement, whereas a real number computed off a real venue is exactly the kind of number
that gets mistaken for the pre-registered one. See :data:`WHY_NOT_PREREGISTERED`.

Which states, and why the list is all of them
----------------------------------------------

Every state past ``PARAMETERS_OPEN`` is refused, and this module does not maintain its own reasons
for them: ``phase0.governance`` already classifies the eight states into
:data:`~phase0.governance.HUMAN_ACT_STATES` and :data:`~phase0.governance.COMPUTED_STATES` and
derives :data:`~phase0.governance.NOT_REAL_MAY_NOT_ADVANCE` from ``ORDER`` so a state added tomorrow
is refused by default. Restating that classification here would be a second copy of a rule that
already exists, and the failure mode of a second copy is that it drifts. So
:data:`HYPERLIQUID_MAY_NOT_ADVANCE` is imported from phase0's set rather than rebuilt from it, and
``tests/hyperliquid/test_governance_refusal.py`` pins the two as the same object's contents.

Two enforcement points, and the difference between them
--------------------------------------------------------

:func:`refuse_if_hyperliquid_would_advance` is a *predicted* refusal: it reads
:data:`phase0.execution.STAGE_AUTHORITY` and refuses before the runner is called, so nothing is
written at all. :func:`execute_hyperliquid_stage` adds an *observed* one: it reads the governance
state before and after and refuses if it moved, whatever the register said. The second is the one
that survives a change to ``STAGE_AUTHORITY`` — a stage added tomorrow with an ``advances`` this
module has never heard of is caught by the observation and missed by the prediction. Neither
subsumes the other: the prediction is what stops a write from happening, and the observation is what
notices when the prediction was wrong.

Both are defence in depth over a real lock rather than a substitute for one. The lock is in
``src/phase0/``; see :data:`GOVERNANCE_NOTE` for the division of labour and for the residue that is
still open, which is not nothing.
"""

from phase0.execution import STAGE_AUTHORITY, execute_stage
from phase0.governance import COMPUTED_STATES, HUMAN_ACT_STATES, NOT_REAL_MAY_NOT_ADVANCE

from .provenance import SNAPSHOT_PREFIX, is_hyperliquid_snapshot

#: Every governance state a Hyperliquid run may not reach.
#:
#: **Imported from phase0, not rebuilt.** ``phase0.governance.NOT_REAL_MAY_NOT_ADVANCE`` is already
#: derived from ``ORDER`` minus the initial state, so a state added to the machine is refused by
#: default. Deriving it a second time here would produce a set that agrees today and is free to
#: disagree later, and a governance rule that exists in two copies is a governance rule with a
#: version nobody is reading.
HYPERLIQUID_MAY_NOT_ADVANCE = NOT_REAL_MAY_NOT_ADVANCE

#: Why this source is refused even though its data is real. Quoted verbatim in every refusal this
#: module raises, and pinned by ``tests/hyperliquid/test_governance_refusal.py`` so it cannot rot
#: into a stale note.
WHY_NOT_PREREGISTERED = """\
§11.1 fixes the chain as Ethereum Mainnet. §11.2 pre-registers Arbitrum as the single optional
secondary diagnostic and states the condition in its own words: it "must be pre-registered as a
secondary diagnostic, not introduced after Ethereum fails". Hyperliquid appears on neither list.

The objection is NOT that this data is fake. It is real -- a real venue, real wallets, real fills,
every row checkable against the venue's own explorer -- and pretending otherwise would be a
different false statement. The objection has two parts:

  WRONG POPULATION.  The hypothesis is about wallets trading tokens on an Ethereum AMM. This is a
  central-limit-order-book venue: no pool, no reserves, no curve, no counterparty named, and no
  §4.6 quote asset anywhere in its universe. A number computed here answers a question about
  Hyperliquid and would be published against a pre-registration about Ethereum. The population is
  additionally a leaderboard sample -- active, surviving, high-volume traders and nobody else.

  CHOSEN AFTER THE FACT.  This is the part §11.2 legislates against, and it is the part that does
  not depend on the venue at all. A venue introduced once the pre-registered one is inconvenient is
  a specification search: with enough venues, some venue passes. That is true whether the new venue
  is better or worse than the old one, and it is why §11.2 requires a secondary diagnostic to be
  named in advance rather than justified in retrospect. Even a *passing* result here is evidence of
  nothing about the hypothesis -- and a failing Ethereum result followed by a passing one here is
  precisely the substitution the sentence exists to forbid.

Which makes advancing on it worse than advancing on synthetic data, in one specific way: a synthetic
number is obviously not a measurement, and this one is not obviously anything. It is a real number,
off a real venue, and a real number is what gets mistaken for the pre-registered one.
"""


class HyperliquidRunRefused(Exception):
    """A Hyperliquid run tried to advance, or did advance, the Phase 0 state machine.

    Deliberately not a :class:`phase0.errors.Phase0Error`: ``execute_stage`` catches those and turns
    them into a ``REFUSED`` :class:`~phase0.execution.StageResult`, which is *a recorded outcome of a
    governed run*. This is not that. It is a defect in whatever wired a non-pre-registered source to
    the real state machine, and it must reach the caller as an exception rather than become a row in
    the audit log that a later reader could mistake for governance working.
    """


def _why(state):
    """Why this particular state may not be reached on data off a venue nobody pre-registered.

    Two reasons, one per phase0 classification, plus a default for a state phase0 has not
    classified. The default is reached rather than crashed into on purpose: a state added to
    ``ORDER`` without being classified is still refused, and the message says so instead of
    implying a reason nobody wrote.
    """
    if state in HUMAN_ACT_STATES:
        return (
            "{} records a human act about a real experiment — a person froze a pre-registration or "
            "froze code and data, or a validation gate passed, or a decision was emitted about a "
            "hypothesis. Each of those is an act about the *pre-registered* experiment. A "
            "measurement of a venue nobody pre-registered is not evidence that any of them "
            "happened, however real the measurement is.".format(state)
        )
    if state in COMPUTED_STATES:
        return (
            "{} records a computation over the experiment's data. This is a computation over a "
            "different venue's data: a null distribution built from order book fills is a null for "
            "a population the hypothesis is not about, and a threshold calibrated against it would "
            "be applied to Ethereum. MAIN_TEST_EXECUTED is write-once — reaching it here would "
            "consume the single main-test execution the whole pre-registration is built around, "
            "and the real one would afterwards be refused as 'already in this state'. That is not "
            "a reputational problem, it is a destroyed experiment.".format(state)
        )
    return (
        "{} is a state of the pre-registered experiment past PARAMETERS_OPEN, so reaching it claims "
        "the experiment progressed. It carries no more specific reason than that because phase0 has "
        "not classified it as a human act or a computation; it is refused by default, which is the "
        "direction phase0.governance.NOT_REAL_MAY_NOT_ADVANCE is derived in precisely so a new "
        "state is covered before anyone remembers to cover it.".format(state)
    )


def refuse_if_hyperliquid_would_advance(stage, dataset_snapshot):
    """Refuse, before anything is written, a Hyperliquid stage that would complete a transition.

    :param stage: a key of :data:`phase0.execution.STAGE_AUTHORITY`. An unknown stage raises
        :class:`ValueError` rather than being waved through — an unregistered stage has no
        ``advances`` to read, and "no rule found" must not read as "no rule applies".
    :param dataset_snapshot: the snapshot identifier the stage would run under.
    :raises HyperliquidRunRefused: the snapshot declares itself off the pre-registered chain and the
        stage completes a transition into :data:`HYPERLIQUID_MAY_NOT_ADVANCE`.

    :returns: the state the stage would have advanced to when it is permitted to proceed, or
        ``None`` for a stage that completes no transition — so a caller can tell "allowed, and moves
        nothing" from "allowed, and moves something", which are different facts about a permitted
        call.

    **What this does not check.** It says nothing about whether the stage *should* run, whether the
    start gate is met, or whether the data is any good. It answers exactly one question: would
    letting this stage complete leave the machine claiming Phase 0 progressed?
    """
    authority = STAGE_AUTHORITY.get(stage)
    if authority is None:
        raise ValueError(
            "unknown stage {!r}; expected one of {}. Refusing to guess: a stage with no entry in "
            "STAGE_AUTHORITY has no 'advances' to read, and treating a missing rule as an absent "
            "one is how an unregistered stage acquires permission it was never "
            "given.".format(stage, ", ".join(sorted(STAGE_AUTHORITY)))
        )
    if not is_hyperliquid_snapshot(dataset_snapshot):
        return authority.advances
    if authority.advances is None:
        return None
    raise HyperliquidRunRefused(
        "stage {!r} completes the transition to {} and this run's dataset snapshot is {!r}, which "
        "declares itself off the pre-registered chain (identifiers minted by tools.hyperliquid "
        "begin {!r}). {}\n\n{}\n"
        "A run over this source may execute stages and record their outcomes — phase0.execute_stage "
        "writes the run record at step 3, calls the runner at step 4 and appends the audit entry at "
        "step 7 regardless — but step 6, the transition, is withheld. Nothing measured off a venue "
        "nobody pre-registered may leave the machine in a state that says the experiment "
        "moved.".format(
            stage, authority.advances, dataset_snapshot, SNAPSHOT_PREFIX,
            _why(authority.advances), WHY_NOT_PREREGISTERED,
        )
    )


def execute_hyperliquid_stage(stage, runner, requester, *, governance, dataset_snapshot, **kwargs):
    """:func:`phase0.execution.execute_stage`, with the rule enforced on both sides.

    The prediction runs first, so a stage that would advance is refused before a run record exists.
    The observation runs last, so a state that moved anyway is refused even if the prediction had
    never heard of the transition that moved it.

    :param governance: the :class:`~phase0.governance.GovernanceMachine`, read before and after.
        Passed through to ``execute_stage`` as well; it is named here because this function has to
        read the state itself and cannot dig it out of ``kwargs`` by convention.
    :raises HyperliquidRunRefused: before the runner, when the stage completes a refused transition;
        after it, when the governance state moved at all.

    **What this guarantees, and what it does not.** It guarantees that a stage run *through this
    function* leaves the governance state where it found it, and that nothing is written at all for
    one that would have advanced. It does not guarantee either of those for
    ``phase0.execute_stage``, which is public and exported — but that caller is not unguarded:
    phase0 ``HELD``\\ s such a stage itself, after the runner. See :data:`GOVERNANCE_NOTE`.

    When the observation does fire, the damage is already done: the state has moved and this raises
    *afterwards*. It is a detector, not a second lock.
    """
    refuse_if_hyperliquid_would_advance(stage, dataset_snapshot)
    before = governance.state
    result = execute_stage(
        stage, runner, requester,
        governance=governance, dataset_snapshot=dataset_snapshot, **kwargs
    )
    after = governance.state
    if is_hyperliquid_snapshot(dataset_snapshot) and after != before:
        raise HyperliquidRunRefused(
            "stage {!r} ran under the Hyperliquid snapshot {!r} and the governance state moved from "
            "{} to {}. STAGE_AUTHORITY said this stage advances {!r}, so the pre-flight refusal did "
            "not fire and the register and the machine disagree about what this stage does. The "
            "state has already moved: this is a detector reporting that the lock in "
            "tools/hyperliquid was the wrong lock, not a lock — and that phase0's own refusal did "
            "not see this transition either. See "
            "tools.hyperliquid.governance.GOVERNANCE_NOTE.".format(
                stage, dataset_snapshot, before, after, STAGE_AUTHORITY[stage].advances,
            )
        )
    return result


#: Where the refusal actually lives, what this package adds, and what is still open. Quoted verbatim
#: by ``tests/hyperliquid/test_governance_refusal.py`` so it cannot rot into a stale note.
GOVERNANCE_NOTE = """\
WHERE THE REFUSAL LIVES -- it is not in tools/

  Primary:  src/phase0/execution.py, in execute_stage, between step 5 (governance re-checked) and
            step 6 (the transition). execute_stage is the only place that both knows the
            dataset_snapshot and decides whether to advance, so it is the only place where "execute
            but do not advance" can be expressed at all. A stage that bears on a transition and ran
            under a not-real snapshot is HELD: the run record, the stage outcome and the audit entry
            are written, and the transition is withheld.

  Backstop: src/phase0/governance.py, in GovernanceMachine.transition, which takes a
            dataset_snapshot and raises phase0.errors.NotAMeasurementError. execute_stage is not the
            only caller -- phase0/cli.py reaches transition through the MANUAL_TRANSITIONS path --
            so this is what covers PARAMETERS_FROZEN and CODE_AND_DATA_FROZEN, which are no stage's
            'advances' and which no amount of care in this package could reach.

  Rule:     src/phase0/governance.py, in advancement_refusal, so the two enforcement points cannot
            drift into disagreeing about what is refused.

WHAT src/phase0/ OWNS, NOT tools/

  The predicate. tools.hyperliquid.provenance.is_hyperliquid_snapshot could never have been the
  authority: src/ may not import tools/ (tests/test_lane_independence.py), and a rule enforced by a
  module the enforcer cannot see is not enforced. What phase0 owns is a property of the identifier
  it is already given -- src/phase0/snapshots.py, NOT_REAL_PREFIXES, a table of the prefixes by
  which a snapshot identifier declares itself not a measurement. "NOT-PREREGISTERED-" is one row of
  it, added as a line of data and no branch of code anywhere; "SYNTHETIC-", "REPLAY-" and "DRYRUN-"
  are the others. tools/hyperliquid conforms: SNAPSHOT_PREFIX is that row.

  That row is also the one place where this source's claim is *narrower* than the table's name. The
  table is called NOT_REAL_PREFIXES and its own docstring frames the claim as "the data behind it
  was not read off the thing the experiment is about" -- which is exactly right for this source and
  is why the row belongs there. The data IS real. It was not read off the thing the experiment is
  about. The suffix on the identifier says the narrower thing in words, so a reader who only ever
  sees the identifier is not told the data is fake: it ends -NOT-THE-PREREGISTERED-CHAIN, and
  deliberately not mockchain's -NOT-A-MEASUREMENT.

WHAT THIS PACKAGE ADDS, AND WHY IT IS NOT REDUNDANT

  refuse_if_hyperliquid_would_advance refuses BEFORE the runner, so a stage that would advance opens
  no run record at all; phase0's refusal is necessarily after it, because by then the runner has
  produced a value and HELD is the honest status for it. And execute_hyperliquid_stage's observation
  reads the state before and after and refuses if it moved, whatever either register said. Both bind
  callers who use this package's entry point and bind nobody else -- but the caller they do not bind
  is bound by src/phase0/ instead.

WHAT IS STILL OPEN, AND IT IS NOT NOTHING

  transition can only check a snapshot it is given, and dataset_snapshot defaults to None because
  PARAMETERS_FROZEN genuinely precedes any dataset -- there is normally nothing to name. A caller
  that has a snapshot and withholds it is therefore not refused, and phase0 cannot tell that case
  from the honest one. Only the caller can close that, by naming its data.

  And nothing anywhere detects data that is not what it claims to be. The declaration is a claim the
  source makes about itself. This package declares; a source that never heard of the convention
  mints an identifier indistinguishable from an archival extract's.

  Narrower and specific to this source: governance refuses ADVANCEMENT, not READING. Nothing stops
  somebody importing tools.hyperliquid.decode, obtaining ObservedTransactions, and running them
  through pipeline.run_wallet_window in a process that never touches phase0 at all. What is left
  there is not a lock but an outcome: run_inputs supplies no pools and no prices, so the run
  produces no scored buy. See tools.hyperliquid.decode.run_inputs -- the defence against a §4 number
  coming out of this source is that there is no §4 number in it, and that is verified by running it
  rather than asserted.
"""

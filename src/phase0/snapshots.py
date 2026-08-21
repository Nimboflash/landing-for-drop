"""What a dataset snapshot identifier declares about itself.

Every governed run is pinned to a ``dataset_snapshot`` — the identifier of the data the run was
over. :class:`phase0.runs.RunRecord` stores it verbatim, every ``run.open`` audit entry quotes it,
and :class:`phase0.execution.StageContext` hands it to the runner. It is already the one string
that travels the whole way through a run, and ``phase0.runs.RunStore.open_run`` already refuses a
blank one.

This module adds one thing to it: **some identifiers declare that they are not a measurement.**

The rule
--------

A dataset snapshot identifier that begins with one of :data:`NOT_REAL_PREFIXES` is a claim, made by
the source that minted it, that the data behind it was not read off the thing the experiment is
about. ``phase0`` refuses to let such a run advance the governance machine —
:func:`phase0.governance.advancement_refusal` is where that consequence lives, because the states
are governance's, not this module's.

Why a prefix on the identifier rather than a flag on a record
-------------------------------------------------------------

A flag is a field, and fields are dropped by every join, projection and serialisation step between
a run record and a report. The record that lost the flag looks exactly like a record that never had
one. The identifier is not dropped: it is what the run record is *about*, it is quoted in the audit
log, and it is what a reader sees first. So the declaration rides on the identifier, and a run that
was not a measurement says so on the face of its own record.

Why a table rather than a constant
-----------------------------------

The first source that needed this was a synthetic chain generator, but it is not the only kind of
not-real data a measurement instrument meets. A replayed fixture and a rehearsal of the machinery
are the same claim with a different word, and each has the same consequence. So the vocabulary is
:data:`NOT_REAL_PREFIXES`, a table — adding a kind is a line of data, not a branch of code, and
every enforcement point picks it up without being edited. The reason each kind is listed is stored
next to it, so a refusal can say what the prefix *means* rather than only that it matched.

What this guarantees, and what it does not
------------------------------------------

It guarantees that an identifier which *declares itself* not real is recognised as such, in any
letter case, wherever the identifier travels.

It does not detect data that is not real and does not say so. Nothing in this package can: the
declaration is a claim the source makes about itself, and a source that lies — or simply one that
never heard of this convention — mints an identifier indistinguishable from an archival extract's.
That residue is why the convention has to be cheap enough for every not-real source to adopt, and
it is why this is a table of prefixes and not a registry of known-bad snapshots.

It also says nothing about whether the data is any *good*. ``dune-2026-07-31`` is a real snapshot
identifier and may still name a botched extract. This module answers exactly one question: does
this identifier claim to be something other than a measurement?
"""

#: The vocabulary. Prefix -> what a source claims by minting an identifier that begins with it.
#:
#: **Data, deliberately.** Every enforcement point reads this table; none of them names a prefix.
#: Adding a kind of not-real data is one line here and no code anywhere else.
#:
#: ``SYNTHETIC-`` is minted by ``tools/mockchain`` and ``NOT-PREREGISTERED-`` by
#: ``tools/hyperliquid``; ``REPLAY-`` and ``DRYRUN-`` are listed because they are the same claim with
#: a different word, and a table with one row is a constant wearing a costume.
#:
#: ``NOT-PREREGISTERED-`` is the row that stretches this table's name, and it is worth being precise
#: about rather than filing quietly. The data behind such an identifier **is** real — a real venue,
#: real wallets, real trades, every row checkable against that venue's own explorer. What is not
#: real is the *relationship between that data and this experiment*: §11.1 fixes the chain and §11.2
#: requires any secondary diagnostic to be pre-registered rather than "introduced after Ethereum
#: fails", so a venue chosen afterwards is a specification search however good its data is. That
#: fits the claim this module's own docstring makes — "the data behind it was not read off **the
#: thing the experiment is about**" — which is the sentence the whole table is keyed on, and it is
#: why the row belongs here rather than in a second mechanism.
#:
#: The consequence is identical to the other three and deliberately so: :func:`declared_not_real`
#: matches it, ``phase0.governance.advancement_refusal`` refuses every state past
#: ``PARAMETERS_OPEN``, and ``phase0.execution.execute_stage`` ``HELD``\\ s any stage that would
#: advance. No enforcement point was edited to add it. What differs is only what a *source* should
#: say in the rest of its identifier: ``tools/hyperliquid`` suffixes
#: ``-NOT-THE-PREREGISTERED-CHAIN`` and deliberately not ``-NOT-A-MEASUREMENT``, because a reader
#: who saw the latter on data they could check on an explorer would learn to distrust the marker.
NOT_REAL_PREFIXES = {
    "SYNTHETIC-": "generated by a source that never read a chain",
    "REPLAY-": "replayed from a recorded fixture rather than read from a chain",
    "DRYRUN-": "a rehearsal of the machinery, not a run of the experiment",
    "NOT-PREREGISTERED-": (
        "measured off a real source that the pre-registration did not name; the data is real and "
        "the venue is not the one §11.1 fixed, and §11.2 forbids introducing one after the fact"
    ),
}


def declared_not_real(dataset_snapshot):
    """The prefix by which this identifier declares itself not a measurement, or ``None``.

    Matching is case-insensitive and ignores surrounding whitespace. A rule whose enforcement
    turned on the shift key would be weaker than it looks, and ``phase0.runs.RunStore.open_run``
    already strips before it decides a snapshot is present at all.

    A prefix test rather than a substring test: an identifier that *mentions* ``SYNTHETIC`` in the
    middle is not the same claim as one that begins with it, and a substring test would refuse a
    real extract whose name happened to contain the word.

    :param dataset_snapshot: the identifier. Anything that is not a string returns ``None`` — this
        function reports what an identifier declares and does not police its type; ``open_run``
        owns that.
    :returns: the matching key of :data:`NOT_REAL_PREFIXES`, or ``None`` for an identifier that
        declares nothing. ``None`` means "this identifier makes no such claim", which is not the
        same fact as "this data is real".
    """
    if not isinstance(dataset_snapshot, str):
        return None
    head = dataset_snapshot.strip().upper()
    for prefix in sorted(NOT_REAL_PREFIXES):
        if head.startswith(prefix):
            return prefix
    return None


def is_declared_not_real(dataset_snapshot):
    """True when :func:`declared_not_real` matched. The predicate, for callers that want a bool."""
    return declared_not_real(dataset_snapshot) is not None


def declaration_clause(dataset_snapshot):
    """The sentence naming the snapshot, the prefix it carries and what that prefix claims.

    ``None`` for an identifier that declares nothing, so a caller can use it as the condition and
    the explanation at once.

    The whole vocabulary is spelled into the sentence on purpose: a refusal a reader can learn the
    rule from is worth more than one they have to go and look up, and it makes an added prefix
    visible in the refusals it produces.
    """
    prefix = declared_not_real(dataset_snapshot)
    if prefix is None:
        return None
    return (
        "dataset snapshot {!r} declares itself not a measurement: it begins {!r}, which means it "
        "is {}. The identifiers that carry such a declaration are {}.".format(
            dataset_snapshot, prefix, NOT_REAL_PREFIXES[prefix],
            ", ".join("{!r} ({})".format(key, NOT_REAL_PREFIXES[key])
                      for key in sorted(NOT_REAL_PREFIXES)),
        )
    )

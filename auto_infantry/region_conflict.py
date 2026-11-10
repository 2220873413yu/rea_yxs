"""Typed read-only region failures, kept separate from uncertain spending and session failures."""


class RegionConflict(RuntimeError):
    """A foreign region replaced a read; no spending outcome may be inferred from this exception."""


class RegionRestoreConflict(RegionConflict):
    """Only post-operation map restoration failed; the operation's already-confirmed result remains valid."""

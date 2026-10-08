"""Limit a research question without changing the campaign's mutation authority.

Only ordinary proposals use this scope. Paired updater episodes retain the original
campaign authority so a method can be evaluated through its execution descendants.
"""

SCOPES = {
    "all": None,
    "methods": frozenset(("analyst.md", "challenger.md", "research.md")),
    "execution": frozenset(("executor.md", "drafter.md", "prober.md", "reviewer.md")),
    "harness": frozenset(("harness.json",)),
}


def editable(terms: dict) -> list[str]:
    """Return the nonempty intersection of the research scope and fixed authority.

    The result preserves the authorized file order and never mutates ``terms``.
    Selecting a scope permits proposals there; it neither requires a change nor
    constitutes evidence that any resulting candidate is better.
    """
    kind = terms.get("proposal_kind", "all")
    if not isinstance(kind, str) or kind not in SCOPES:
        raise ValueError("proposal_kind must be all, methods, execution, or harness")
    mutable = terms.get("mutable")
    if not isinstance(mutable, list) or any(
        not isinstance(name, str) or not name for name in mutable
    ):
        raise ValueError("mutable must be a list of authorized file names")
    scope = SCOPES[kind]
    files = [name for name in mutable if scope is None or name in scope]
    if not files:
        raise ValueError(f"proposal_kind {kind!r} has no authorized mutable files")
    return files

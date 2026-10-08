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

GUARDED_INTERVENTION = """Guarded proposals must use only one intervention class: either method files
(analyst.md, challenger.md, research.md) or execution/harness files (executor.md, drafter.md,
prober.md, reviewer.md, harness.json). Do not mix these classes in one proposal: task scores
cannot certify a changed research method. Leave every file in the other class unchanged.
An unchanged bundle is permitted. This restriction never expands the editable files above.
"""


def research_constraint(terms: dict) -> str:
    """Explain the fixed guarded qualification rule, outside learned policies."""
    return (
        GUARDED_INTERVENTION
        if (terms.get("stream") or {}).get("mode", "explore") == "guarded"
        else ""
    )


def intervention_problem(terms: dict, changed: list[str]) -> str:
    """Reject guarded mixed interventions before registration or task measurement.

    Explore campaigns retain their legacy proposal semantics; their exploratory
    inheritance is not certification of research-method improvement.
    """
    if (terms.get("stream") or {}).get("mode", "explore") != "guarded":
        return ""
    changed = set(changed)
    if changed & SCOPES["methods"] and changed & (
        SCOPES["execution"] | SCOPES["harness"]
    ):
        return "guarded proposals cannot mix method and execution/harness changes"
    return ""


def assert_task_confirmation(host, candidate: str, incumbent: str) -> None:
    """Guarded task evidence cannot settle a change to method-policy bytes.

    Compare against the frozen comparator, not the candidate's declared parent.
    The hashes are trusted only after verifying both registered source bundles.
    Harness changes remain task interventions; this does not assert their lack of
    effects on research execution, where the same harness is also active.
    """
    if (host.terms.get("stream") or {}).get("mode", "explore") != "guarded":
        return
    host.validate_harness(candidate)
    host.validate_harness(incumbent)
    versions = host.versions()
    if any(
        versions[candidate]["bundle"][name] != versions[incumbent]["bundle"][name]
        for name in SCOPES["methods"]
    ):
        raise RuntimeError(
            "guarded task confirmation cannot certify changed method policies; "
            "use paired updater confirmation"
        )


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

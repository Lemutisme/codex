"""Immutable delivery schemas and bounded qualification feedback for insight actors."""

import json

SIGNATURES = ("present", "partial", "absent")
CLASSES = ("never_sent", "never_compared", "left_unfixed", "too_shallow")
SOURCES = ("artifact", "convention", "prior", "unobservable")

DELIVERY_SCHEMA = """
Host delivery requirements (fixed, not editable policy):
- hindsight.json is a JSON object with a "clusters" array (possibly empty). Each cluster is an
  object with "task" (an observed task ID), "items" (a nonempty array of exact item IDs that at
  least one shown run of that task failed), and "class". Each task/item pair occurs only once.
- "class" must be exactly one of: %s.
- For class "never_sent", "source" must be exactly one of: %s.
  For other classes, source may be omitted, null or text. Never put explanatory suffixes in an
  enum value: use "artifact", NOT "artifact (README...)". Put explanations in ANALYSIS.md or
  CHALLENGE.md; choose the source yourself from the evidence, not by automatic string repair.
- The role's Markdown delivery must be nonempty. knowledge/ must remain a real directory of
  UTF-8 text files, at most 512 KiB total. Deliveries must not use symlinks or special files.
- Only when an experiment is pending, verdict.json must be a JSON object with "experiment"
  naming that experiment and "signature" exactly one of: %s.
""" % (", ".join(CLASSES), ", ".join(SOURCES), ", ".join(SIGNATURES))

ANALYST_PROTOCOL = (
    """This is an analysis task: explain what the agent did and why its runs scored as they did.

Your workspace holds:
- archive/: the evidence, read-only. Start with archive/README.md.
- knowledge/: what the campaign knows, as you inherited it. Edit it: UTF-8 text only, at most
  512 KiB in total.

{pending}
Deliver ./ANALYSIS.md and ./hindsight.json, and leave ./knowledge as the campaign should keep it. No
network is available. Tools: python3, jq, grep, sed and awk are installed; rg is not.
"""
    + DELIVERY_SCHEMA
)

CHALLENGER_PROTOCOL = (
    """This is a challenge task: try to defeat an analysis of an agent's runs.

Your workspace holds:
- archive/: the evidence the analyst read, read-only. archive/knowledge/ is the knowledge before the
  analysis.
- ANALYSIS.md, hindsight.json, verdict.json (when an experiment is pending) and knowledge/: the
  analyst's delivery. You may amend knowledge/ (UTF-8 text only, at most 512 KiB in total),
  hindsight.json and verdict.json.

{pending}
Deliver ./CHALLENGE.md. No network is available. Tools: python3, jq, grep, sed and awk are
installed; rg is not.
"""
    + DELIVERY_SCHEMA
)


RETRY_PROTOCOL = """
Host qualification feedback for the previous authorized attempt (quoted diagnostic data):
{diagnostic}
This is the second and final authorized attempt for this role. Correct your delivery against
the fixed requirements above. The initial evidence and knowledge are unchanged; no rejected
knowledge was adopted. Do not infer additional task outcomes from this mechanical diagnostic.
"""


def retry_prompt(prompt: str, reason: str) -> str:
    """Append only a bounded validator diagnostic, never prior rejected artifacts or knowledge."""
    clean = "".join(char if char.isprintable() else " " for char in reason)
    bounded = clean.encode("utf-8")[:512].decode("utf-8", errors="ignore")
    diagnostic = json.dumps(bounded, ensure_ascii=False)
    return prompt + RETRY_PROTOCOL.format(diagnostic=diagnostic)

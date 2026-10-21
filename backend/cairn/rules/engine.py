"""Hard business rules in code (F4).

A rule fires when its ``condition`` evaluates truthy for the event context.
Outcomes, from least to most restrictive: allow, warn, require_approval, block.
The most restrictive outcome of all firing rules wins.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from psycopg import AsyncConnection

from cairn.db.core import fetch_all
from cairn.rules import jsonlogic

OUTCOME_RANK = {"allow": 0, "warn": 1, "require_approval": 2, "block": 3}


@dataclass
class Rule:
    rule_key: str
    version: int
    name: str
    event: str
    condition: Any
    outcome: str
    message: str = ""
    tool: str | None = None
    severity: str = "high"
    fixtures: list[dict] = field(default_factory=list)
    description: str = ""

    def applies(self, event: str, tool: str | None) -> bool:
        return self.event == event and (self.tool is None or self.tool == tool)

    @classmethod
    def from_row(cls, r: dict) -> "Rule":
        return cls(
            rule_key=r["rule_key"], version=r["version"], name=r["name"], event=r["event"],
            condition=r["condition"], outcome=r["outcome"], message=r.get("message") or "",
            tool=r.get("tool"), severity=r.get("severity") or "high",
            fixtures=r.get("fixtures") or [], description=r.get("description") or "",
        )


@dataclass
class Firing:
    rule_key: str
    rule_version: int
    name: str
    outcome: str
    message: str


@dataclass
class Decision:
    outcome: str
    firings: list[Firing]
    evaluated: list[str]

    @property
    def blocked(self) -> bool:
        return self.outcome == "block"

    @property
    def needs_approval(self) -> bool:
        return self.outcome == "require_approval"

    def as_dict(self) -> dict:
        return {
            "outcome": self.outcome,
            "evaluated": self.evaluated,
            "fired": [f.__dict__ for f in self.firings],
        }


def evaluate(rules: list[Rule], event: str, context: dict, tool: str | None = None) -> Decision:
    outcome = "allow"
    firings: list[Firing] = []
    evaluated: list[str] = []
    for rule in sorted(rules, key=lambda r: r.rule_key):
        if not rule.applies(event, tool):
            continue
        evaluated.append(rule.rule_key)
        if jsonlogic._truthy(jsonlogic.apply(rule.condition, context)):
            firings.append(Firing(rule.rule_key, rule.version, rule.name, rule.outcome, rule.message))
            if OUTCOME_RANK[rule.outcome] > OUTCOME_RANK[outcome]:
                outcome = rule.outcome
    return Decision(outcome, firings, evaluated)


def run_fixtures(rule: Rule) -> list[dict]:
    """Each fixture: {"name", "context", "expect": true|false}. Returns failures."""
    failures = []
    try:
        jsonlogic.validate(rule.condition)
    except jsonlogic.RuleSyntaxError as e:
        return [{"fixture": "(syntax)", "error": str(e)}]
    if not rule.fixtures:
        return [{"fixture": "(none)", "error": "a rule needs at least one fixture before it can be published"}]
    for fx in rule.fixtures:
        try:
            got = jsonlogic._truthy(jsonlogic.apply(rule.condition, fx.get("context", {})))
        except Exception as e:  # noqa: BLE001 - surface any evaluation error as a failure
            failures.append({"fixture": fx.get("name", "?"), "error": str(e)})
            continue
        if got != bool(fx.get("expect")):
            failures.append({
                "fixture": fx.get("name", "?"),
                "error": f"expected the rule to {'fire' if fx.get('expect') else 'not fire'}, but it "
                         f"{'fired' if got else 'did not fire'}",
            })
    return failures


async def load_active_rules(conn: AsyncConnection) -> list[Rule]:
    """Latest published, enabled version of each rule key."""
    rows = await fetch_all(conn, """
        select distinct on (rule_key) *
        from rules where status = 'published'
        order by rule_key, version desc
    """)
    return [Rule.from_row(r) for r in rows if r["enabled"]]

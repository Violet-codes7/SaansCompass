"""GRAP rules as Cedar policies, evaluated in-process with cedarpy.

Every answer is one of three decisions, each tied to the policy behind it:

- ALLOWED: a verified permit matched and no forbid did.
- NOT_ALLOWED: a verified forbid matched (forbid always beats permit).
- ADVISED_AGAINST: a verified forbid marked @kind("advisory") matched: GRAP's
  citizen charter advises against it, but no order restricts it.
- CHECK: nothing matched, or only a draft rule did. An activity no verified
  rule covers must never come out as "Allowed".

Cedar returns Deny both when a forbid matched and when nothing matched; the
difference is whether the deny carries reasons.
"""
import json
from dataclasses import asdict, dataclass, replace
from functools import lru_cache
from pathlib import Path

import cedarpy

RULES_DIR = Path(__file__).parent / "rules"

ALLOWED = "allowed"
NOT_ALLOWED = "not_allowed"
ADVISED_AGAINST = "advised_against"
CHECK = "check_official_order"

LABELS = {
    ALLOWED: "Allowed",
    NOT_ALLOWED: "Not allowed",
    ADVISED_AGAINST: "Advised against",
    CHECK: "Check the official order",
}


@dataclass(frozen=True)
class RuleResult:
    activity_id: str
    decision: str
    policy_id: str | None
    clause: str | None
    note: str | None = None

    @property
    def label(self):
        return LABELS[self.decision]

    def to_dict(self):
        d = asdict(self)
        d["label"] = self.label
        return d


@dataclass(frozen=True)
class PolicyInfo:
    id: str
    clause: str
    status: str
    effect: str
    kind: str = "order"


class RuleBook:
    def __init__(self, policies_text, schema_text):
        self.policies_text = policies_text
        self.schema_text = schema_text
        self.policies = self._read_annotations(policies_text)

    @classmethod
    def from_dir(cls, rules_dir=RULES_DIR):
        rules_dir = Path(rules_dir)
        texts = [p.read_text(encoding="utf-8") for p in sorted(rules_dir.glob("*.cedar"))]
        schema = (rules_dir / "schema.cedarschema").read_text(encoding="utf-8")
        return cls("\n".join(texts), schema)

    @staticmethod
    def _read_annotations(policies_text):
        """Map cedarpy's internal ids (policy0, policy1...) to our annotations."""
        if not policies_text.strip():
            return {}
        parsed = json.loads(cedarpy.policies_to_json_str(policies_text))
        out = {}
        for internal_id, body in parsed["staticPolicies"].items():
            ann = body.get("annotations", {})
            out[internal_id] = PolicyInfo(
                id=ann.get("id", internal_id),
                clause=ann.get("clause", ""),
                status=ann.get("status", "draft"),
                effect=body["effect"],
                kind=ann.get("kind", "order"),
            )
        return out

    def validate(self):
        """Return a list of problems: schema errors and missing annotations."""
        problems = []
        if self.policies_text.strip():
            result = cedarpy.validate_policies(self.policies_text, self.schema_text)
            problems += [e.error for e in result.errors]
        seen = set()
        for internal_id, info in self.policies.items():
            if info.id == internal_id:
                problems.append(f"{internal_id} has no @id annotation")
            if not info.clause:
                problems.append(f"{info.id} has no @clause annotation")
            if info.status not in ("draft", "verified"):
                problems.append(f"{info.id} has status {info.status!r}, expected draft or verified")
            if info.kind not in ("order", "advisory"):
                problems.append(f"{info.id} has kind {info.kind!r}, expected order or advisory")
            if info.kind == "advisory" and info.effect != "forbid":
                problems.append(f"{info.id} is advisory, which only makes sense on a forbid")
            if info.id in seen:
                problems.append(f"duplicate policy id {info.id}")
            seen.add(info.id)
        return problems

    def evaluate(self, persona_id, activity_id, area_id, stage, sensitive=False):
        if stage is None:
            return RuleResult(activity_id, CHECK, None, None, "The GRAP stage is unknown.")
        request = {
            "principal": {"type": "Persona", "id": persona_id},
            "action": {"type": "Action", "id": activity_id},
            "resource": {"type": "Area", "id": area_id},
            "context": {"stage": int(stage), "sensitive": bool(sensitive)},
        }
        if not self.policies_text.strip():
            return RuleResult(activity_id, CHECK, None, None, "The GRAP schedule does not cover this.")
        result = cedarpy.is_authorized(request, self.policies_text, [])
        if result.diagnostics.errors:
            return RuleResult(activity_id, CHECK, None, None, "A rule could not be evaluated.")

        matched = [self.policies[r] for r in result.diagnostics.reasons]
        if not matched:
            return RuleResult(activity_id, CHECK, None, None, "The GRAP schedule does not cover this.")

        # Prefer citing a verified policy; forbids decide over permits.
        forbids = [p for p in matched if p.effect == "forbid"]
        deciding = forbids if forbids else matched
        verified = [p for p in deciding if p.status == "verified"]
        if not verified:
            p = deciding[0]
            return RuleResult(
                activity_id, CHECK, p.id, p.clause,
                "This rule is a draft that has not been checked against the latest CAQM order.",
            )
        if forbids:
            # A binding order outranks an advisory when both match.
            orders = [p for p in verified if p.kind == "order"]
            p = orders[0] if orders else verified[0]
            decision = NOT_ALLOWED if orders else ADVISED_AGAINST
        else:
            p, decision = verified[0], ALLOWED
        return RuleResult(activity_id, decision, p.id, p.clause)

    def evaluate_persona(self, persona, area_id, stage, sensitive=False):
        out = []
        for a in persona.activities:
            if a.ruled:
                result = self.evaluate(a.rules_as or persona.id, a.rules_action or a.id, area_id, stage, sensitive)
                out.append(replace(result, activity_id=a.id))
        return out


@lru_cache(maxsize=1)
def default_rulebook():
    return RuleBook.from_dir()

from pathlib import Path

import pytest

from saans.personas import PERSONAS
from saans.rules import ALLOWED, CHECK, NOT_ALLOWED, RULES_DIR, RuleBook

SCHEMA = (RULES_DIR / "schema.cedarschema").read_text()

VERIFIED = '''
@id("t.pe.stage3") @clause("Test clause A") @status("verified")
forbid (principal == Persona::"school", action == Action::"outdoor_pe", resource) when { context.stage >= 3 };

@id("t.pe.below3") @clause("Test clause B") @status("verified")
permit (principal == Persona::"school", action == Action::"outdoor_pe", resource) when { context.stage < 3 };

@id("t.assembly.always") @clause("Test clause C") @status("verified")
permit (principal == Persona::"school", action == Action::"outdoor_assembly", resource);

@id("t.assembly.stage2") @clause("Test clause D") @status("verified")
forbid (principal == Persona::"school", action == Action::"outdoor_assembly", resource) when { context.stage >= 2 };

@id("t.walk.draft") @clause("Draft clause") @status("draft")
permit (principal == Persona::"older", action == Action::"outdoor_walk", resource);
'''


@pytest.fixture
def book():
    return RuleBook(VERIFIED, SCHEMA)


def test_repo_rules_validate_against_schema():
    assert RuleBook.from_dir().validate() == []


def test_test_rules_validate_against_schema(book):
    assert book.validate() == []


def test_every_persona_activity_is_a_schema_action():
    for persona in PERSONAS.values():
        for a in persona.activities:
            assert f'"{a.id}"' in SCHEMA, a.id


def test_validate_reports_missing_annotations_and_bad_actions():
    bad = 'forbid (principal == Persona::"school", action == Action::"nope", resource);'
    problems = RuleBook(bad, SCHEMA).validate()
    assert any("nope" in p for p in problems)
    assert any("no @id" in p for p in problems)


def test_pe_allowed_at_stage2_denied_at_stage3(book):
    allowed = book.evaluate("school", "outdoor_pe", "ito", 2)
    assert (allowed.decision, allowed.policy_id, allowed.clause) == (ALLOWED, "t.pe.below3", "Test clause B")
    denied = book.evaluate("school", "outdoor_pe", "ito", 3)
    assert (denied.decision, denied.policy_id) == (NOT_ALLOWED, "t.pe.stage3")


def test_stages_are_cumulative(book):
    assert book.evaluate("school", "outdoor_pe", "ito", 4).decision == NOT_ALLOWED


def test_forbid_beats_permit(book):
    assert book.evaluate("school", "outdoor_assembly", "ito", 1).decision == ALLOWED
    r = book.evaluate("school", "outdoor_assembly", "ito", 2)
    assert (r.decision, r.policy_id) == (NOT_ALLOWED, "t.assembly.stage2")


def test_uncovered_activity_is_never_allowed(book):
    r = book.evaluate("school", "outdoor_recess", "ito", 0)
    assert r.decision == CHECK and r.policy_id is None and r.label == "Check the official order"


def test_other_persona_does_not_inherit_rules(book):
    assert book.evaluate("rider", "outdoor_pe", "ito", 0).decision == CHECK


def test_draft_rule_shows_check_but_cites_the_draft(book):
    r = book.evaluate("older", "outdoor_walk", "ito", 0)
    assert r.decision == CHECK and r.policy_id == "t.walk.draft" and "draft" in r.note


def test_unknown_stage_is_check(book):
    assert book.evaluate("school", "outdoor_pe", "ito", None).decision == CHECK


def test_empty_rulebook_is_check():
    assert RuleBook("", SCHEMA).evaluate("school", "outdoor_pe", "ito", 1).decision == CHECK


def test_no_repo_rule_says_allowed_or_not_allowed_until_verified():
    """Until the GRAP order is read, every shipped rule is a draft."""
    book = RuleBook.from_dir()
    for persona in PERSONAS.values():
        for stage in range(5):
            for r in book.evaluate_persona(persona, "ito", stage):
                if r.decision != CHECK:
                    assert book_status(book, r.policy_id) == "verified"


def book_status(book, policy_id):
    return next(p.status for p in book.policies.values() if p.id == policy_id)


def test_every_non_check_answer_cites_a_policy(book):
    for persona in PERSONAS.values():
        for stage in range(5):
            for r in book.evaluate_persona(persona, "ito", stage):
                if r.decision != CHECK:
                    assert r.policy_id and r.clause

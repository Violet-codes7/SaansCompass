from pathlib import Path

import pytest

from saans.personas import PERSONAS
from saans.rules import ADVISED_AGAINST, ALLOWED, CHECK, NOT_ALLOWED, RULES_DIR, RuleBook

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
            if a.ruled:
                assert f'"{a.rules_action or a.id}"' in SCHEMA, a.id
                assert (a.rules_as or persona.id) in PERSONAS, a.id


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


def test_only_verified_repo_rules_give_a_decision():
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


ADVISORY = '''
@id("t.walk.charter") @clause("Charter") @status("verified") @kind("advisory")
forbid (principal == Persona::"older", action == Action::"outdoor_walk", resource) when { context.stage >= 4 };

@id("t.walk.order") @clause("Order") @status("verified")
forbid (principal == Persona::"older", action == Action::"outdoor_walk", resource) when { context.stage >= 5 };

@id("t.walk.ok") @clause("Ok") @status("verified")
permit (principal == Persona::"older", action == Action::"outdoor_walk", resource);
'''


def test_advisory_forbid_is_advised_against_not_a_ban():
    book = RuleBook(ADVISORY, SCHEMA)
    assert book.validate() == []
    r = book.evaluate("older", "outdoor_walk", "ito", 4)
    assert (r.decision, r.label, r.policy_id) == (ADVISED_AGAINST, "Advised against", "t.walk.charter")
    assert book.evaluate("older", "outdoor_walk", "ito", 3).decision == ALLOWED


def test_binding_order_outranks_advisory():
    r = RuleBook(ADVISORY, SCHEMA).evaluate("older", "outdoor_walk", "ito", 5)
    assert (r.decision, r.policy_id) == (NOT_ALLOWED, "t.walk.order")


def test_advisory_on_a_permit_is_rejected():
    bad = '@id("x") @clause("c") @status("verified") @kind("advisory") permit (principal, action, resource);'
    assert any("advisory" in p for p in RuleBook(bad, SCHEMA).validate())


def test_rest_break_is_not_a_rules_question():
    results = RuleBook.from_dir().evaluate_persona(PERSONAS["rider"], "ito", 2)
    assert "rest_break" not in [r.activity_id for r in results]


def decide(persona, activity, stage):
    r = RuleBook.from_dir().evaluate(persona, activity, "ito", stage)
    return r.decision, r.policy_id


# Expected answers from the GRAP schedule, Revision 29.09.2026.
@pytest.mark.parametrize("persona,activity,stage,expected", [
    ("school", "physical_classes_primary", 2, (ALLOWED, "school.primary_in_person.below_stage3")),
    ("school", "physical_classes_primary", 3, (NOT_ALLOWED, "school.primary_hybrid.stage3")),  # Stage III 8(i)
    ("school", "physical_classes_primary", 4, (NOT_ALLOWED, "school.primary_hybrid.stage3")),  # cumulative
    ("school", "physical_classes_senior", 3, (ALLOWED, "school.senior_in_person.below_stage4")),
    ("school", "physical_classes_senior", 4, (NOT_ALLOWED, "school.senior_hybrid.stage4")),  # Stage IV 4(i)
    ("school", "outdoor_pe", 2, (ALLOWED, "school.outdoor_activity.below_stage4")),
    ("school", "outdoor_pe", 3, (ALLOWED, "school.outdoor_activity.below_stage4")),
    ("school", "outdoor_pe", 4, (ADVISED_AGAINST, "school.outdoor_activity.stage4_charter")),
    ("school", "school_commute", 4, (CHECK, None)),
    ("rider", "outdoor_shift", 3, (ALLOWED, "rider.two_wheeler.below_stage4")),
    ("rider", "outdoor_shift", 4, (CHECK, None)),  # Stage IV item 5: states may add odd-even
    ("rider", "drive_bs3_petrol_bs4_diesel_car", 2, (ALLOWED, "rider.bs3_petrol_bs4_diesel_car.below_stage3")),
    ("rider", "drive_bs3_petrol_bs4_diesel_car", 3, (NOT_ALLOWED, "rider.bs3_petrol_bs4_diesel_car.stage3")),
    ("rider", "drive_bs4_diesel_lgv_outside", 3, (NOT_ALLOWED, "rider.outside_lgv.stage3")),  # Stage III 7
    ("rider", "drive_bs4_diesel_mgv", 3, (NOT_ALLOWED, "rider.mgv.stage3")),  # Stage III 5, 6
    ("rider", "drive_bs4_diesel_mgv", 1, (ALLOWED, "rider.mgv.below_stage3")),
    ("older", "outdoor_walk", 3, (ALLOWED, "older.outdoor.below_stage4")),
    ("older", "outdoor_errands", 4, (ADVISED_AGAINST, "older.outdoor.stage4_charter")),
])
def test_repo_rules_match_the_schedule(persona, activity, stage, expected):
    assert decide(persona, activity, stage) == expected

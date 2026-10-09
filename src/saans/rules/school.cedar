// School rules, from CAQM's GRAP schedule for NCR, Revision 29.09.2026.
// Annotations:
//   @clause  the stage and item in the schedule the rule comes from
//   @status  "verified" once read against the schedule, else "draft"
//            (drafts always show "Check the official order")
//   @kind    "order" (default) for schedule actions, "advisory" for the
//            citizen charter, which advises but does not restrict
// GRAP stages are cumulative (schedule para 4), so a Stage III rule is
// written as context.stage >= 3 and also applies at Stage IV.
// All 9 areas are in the NCT of Delhi, where the school items apply.

@id("school.primary_hybrid.stage3")
@clause("GRAP Rev. 29.09.2026, Stage III item 8(i): classes up to Class V in Delhi must run in hybrid mode (physical and online); families choose online where available")
@status("verified")
forbid (
  principal == Persona::"school",
  action == Action::"physical_classes_primary",
  resource
) when { context.stage >= 3 };

@id("school.primary_in_person.below_stage3")
@clause("GRAP Rev. 29.09.2026: no Stage I or II action restricts in-person classes")
@status("verified")
permit (
  principal == Persona::"school",
  action == Action::"physical_classes_primary",
  resource
) when { context.stage < 3 };

@id("school.senior_hybrid.stage4")
@clause("GRAP Rev. 29.09.2026, Stage IV item 4(i): classes VI to IX and XI in Delhi must run in hybrid mode (physical and online); families choose online where available")
@status("verified")
forbid (
  principal == Persona::"school",
  action == Action::"physical_classes_senior",
  resource
) when { context.stage >= 4 };

@id("school.senior_in_person.below_stage4")
@clause("GRAP Rev. 29.09.2026: no Stage I to III action restricts in-person classes VI to IX and XI")
@status("verified")
permit (
  principal == Persona::"school",
  action == Action::"physical_classes_senior",
  resource
) when { context.stage < 4 };

@id("school.outdoor_activity.stage4_charter")
@clause("GRAP Rev. 29.09.2026, Stage IV citizen charter: children to avoid outdoor activities and stay indoors as much as possible")
@status("verified")
@kind("advisory")
forbid (
  principal == Persona::"school",
  action in [Action::"outdoor_assembly", Action::"outdoor_recess", Action::"outdoor_pe"],
  resource
) when { context.stage >= 4 };

@id("school.outdoor_activity.below_stage4")
@clause("GRAP Rev. 29.09.2026: no Stage I to III action covers school outdoor activities; check any separate Delhi Education Department circular")
@status("verified")
permit (
  principal == Persona::"school",
  action in [Action::"outdoor_assembly", Action::"outdoor_recess", Action::"outdoor_pe"],
  resource
) when { context.stage < 4 };

// The commute has no policy: the schedule does not address it, so it
// answers "Check the official order".

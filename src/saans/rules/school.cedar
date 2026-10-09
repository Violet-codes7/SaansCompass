// School rules. One policy per GRAP clause.
// @status("draft") means the rule has NOT yet been checked against the latest
// CAQM GRAP order: the app shows "Check the official order" for it instead of
// a decision. Change to @status("verified") only after reading the clause in
// the order and filling in @clause with its stage, item number and date.
// context.stage >= N makes stages cumulative (a Stage III rule applies at IV).

@id("school.primary_classes.stage3")
@clause("GRAP Stage III: classes up to V move to hybrid mode. TO VERIFY: item no. and order date")
@status("draft")
forbid (
  principal == Persona::"school",
  action == Action::"physical_classes_primary",
  resource
) when { context.stage >= 3 };

@id("school.primary_classes.below_stage3")
@clause("No GRAP restriction on in-person primary classes below Stage III. TO VERIFY")
@status("draft")
permit (
  principal == Persona::"school",
  action == Action::"physical_classes_primary",
  resource
) when { context.stage < 3 };

@id("school.senior_classes.stage4")
@clause("GRAP Stage IV: classes VI to IX and XI move to hybrid mode. TO VERIFY: item no. and order date")
@status("draft")
forbid (
  principal == Persona::"school",
  action == Action::"physical_classes_senior",
  resource
) when { context.stage >= 4 };

@id("school.senior_classes.below_stage4")
@clause("No GRAP restriction on in-person classes VI to IX and XI below Stage IV. TO VERIFY")
@status("draft")
permit (
  principal == Persona::"school",
  action == Action::"physical_classes_senior",
  resource
) when { context.stage < 4 };

// Outdoor assembly, recess, PE and the commute have no policy yet: the app
// answers "Check the official order" for them until a clause is found.

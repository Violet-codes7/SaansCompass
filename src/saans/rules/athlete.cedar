// Runner and athlete rules, from CAQM's GRAP schedule for NCR, Revision 29.09.2026.
// See school.cedar for what the annotations mean.

@id("athlete.training.below_stage4")
@clause("GRAP Rev. 29.09.2026: no Stage I to III action restricts outdoor exercise")
@status("verified")
permit (
  principal == Persona::"athlete",
  action in [Action::"outdoor_training", Action::"warm_up_walk"],
  resource
) when { context.stage < 4 };

@id("athlete.training.stage4_charter")
@clause("GRAP Rev. 29.09.2026, Stage IV citizen charter: citizens are advised to limit non-essential outdoor activity")
@status("verified")
@kind("advisory")
forbid (
  principal == Persona::"athlete",
  action in [Action::"outdoor_training", Action::"warm_up_walk"],
  resource
) when { context.stage >= 4 };

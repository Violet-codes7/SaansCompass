// Older adult rules, from CAQM's GRAP schedule for NCR, Revision 29.09.2026.
// See school.cedar for what the annotations mean.

@id("older.outdoor.stage4_charter")
@clause("GRAP Rev. 29.09.2026, Stage IV citizen charter: elderly people and those with respiratory, cardiovascular or other chronic diseases to avoid outdoor activities and stay indoors as much as possible; wear a mask if going out")
@status("verified")
@kind("advisory")
forbid (
  principal == Persona::"older",
  action in [Action::"outdoor_walk", Action::"outdoor_errands"],
  resource
) when { context.stage >= 4 };

@id("older.outdoor.below_stage4")
@clause("GRAP Rev. 29.09.2026: no Stage I to III action restricts walking or errands on foot")
@status("verified")
permit (
  principal == Persona::"older",
  action in [Action::"outdoor_walk", Action::"outdoor_errands"],
  resource
) when { context.stage < 4 };

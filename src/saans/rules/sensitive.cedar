// Applies to everyone in a group the Stage IV citizen charter names, whatever
// their persona. See school.cedar for what the annotations mean.

@id("charter.sensitive_groups.stage4")
@clause("GRAP Rev. 29.09.2026, Stage IV citizen charter: children, pregnant women, elderly and those with respiratory, cardiovascular, cerebrovascular or other chronic diseases to avoid outdoor activities and stay indoors as much as possible; wear a mask if going out")
@status("verified")
@kind("advisory")
forbid (
  principal,
  action in [
    Action::"outdoor_assembly", Action::"outdoor_recess", Action::"outdoor_pe",
    Action::"outdoor_shift", Action::"outdoor_walk", Action::"outdoor_errands",
    Action::"outdoor_work_shift", Action::"dusty_construction_work", Action::"other_construction_work",
    Action::"lunch_walk", Action::"outdoor_training", Action::"warm_up_walk"
  ],
  resource
) when { context.stage >= 4 && context.sensitive };

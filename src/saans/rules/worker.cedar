// Outdoor and construction worker rules, from CAQM's GRAP schedule for NCR,
// Revision 29.09.2026. See school.cedar for what the annotations mean.

@id("worker.dusty_cnd.stage3")
@clause("GRAP Rev. 29.09.2026, Stage III item 1(i): strict restrictions on dust-generating construction and demolition work in NCR, such as excavation, piling, demolition, brick and masonry work, painting, tile cutting and road construction; item 1(iii) exempts railway, metro, airport, hospital, defence, sanitation and linear public projects")
@status("verified")
forbid (
  principal == Persona::"worker",
  action == Action::"dusty_construction_work",
  resource
) when { context.stage >= 3 };

@id("worker.dusty_cnd.below_stage3")
@clause("GRAP Rev. 29.09.2026: Stages I and II require dust control at C&D sites but do not stop the work")
@status("verified")
permit (
  principal == Persona::"worker",
  action == Action::"dusty_construction_work",
  resource
) when { context.stage < 3 };

@id("worker.other_cnd.permitted")
@clause("GRAP Rev. 29.09.2026, Stage III item 1(ii): less dust-generating construction work may continue under the C&D waste rules and dust-control norms; Stage IV item 3 adds linear public projects to the ban but keeps this category")
@status("verified")
permit (
  principal == Persona::"worker",
  action == Action::"other_construction_work",
  resource
);

@id("worker.outdoor_shift.below_stage4")
@clause("GRAP Rev. 29.09.2026: no Stage I to III action stops outdoor work in general")
@status("verified")
permit (
  principal == Persona::"worker",
  action == Action::"outdoor_work_shift",
  resource
) when { context.stage < 4 };
// At Stage IV, item 5 lets states close non-emergency commercial activities,
// so the shift has no policy there and shows "Check the official order".

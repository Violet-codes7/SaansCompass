// Office commuter rules, from CAQM's GRAP schedule for NCR, Revision 29.09.2026.
// See school.cedar for what the annotations mean.

@id("commuter.bs3_petrol_bs4_diesel_car.stage3")
@clause("GRAP Rev. 29.09.2026, Stage III item 4: strict restrictions on BS-III petrol and BS-IV (or older) diesel four-wheelers (LMVs) in Delhi; exception for vehicles adapted for persons with disabilities")
@status("verified")
forbid (
  principal == Persona::"commuter",
  action == Action::"drive_bs3_petrol_bs4_diesel_car",
  resource
) when { context.stage >= 3 };

@id("commuter.bs3_petrol_bs4_diesel_car.below_stage3")
@clause("GRAP Rev. 29.09.2026: no Stage I or II action restricts these four-wheelers")
@status("verified")
permit (
  principal == Persona::"commuter",
  action == Action::"drive_bs3_petrol_bs4_diesel_car",
  resource
) when { context.stage < 3 };

@id("commuter.private_car.stage2_charter")
@clause("GRAP Rev. 29.09.2026, Stage II citizen charter: use public transport and minimise use of personal vehicles")
@status("verified")
@kind("advisory")
forbid (
  principal == Persona::"commuter",
  action == Action::"drive_private_car",
  resource
) when { context.stage >= 2 };

@id("commuter.private_car.below_stage2")
@clause("GRAP Rev. 29.09.2026: no Stage I action restricts newer private cars")
@status("verified")
permit (
  principal == Persona::"commuter",
  action == Action::"drive_private_car",
  resource
) when { context.stage < 2 };

@id("commuter.office.below_stage3")
@clause("GRAP Rev. 29.09.2026: no Stage I or II action limits office attendance (Stage II only staggers public office timings)")
@status("verified")
permit (
  principal == Persona::"commuter",
  action == Action::"office_attendance",
  resource
) when { context.stage < 3 };
// From Stage III, item 9 lets the Delhi and NCR governments decide on 50%
// office strength with the rest working from home, so attendance has no
// policy there and shows "Check the official order".

@id("commuter.lunch_walk.below_stage4")
@clause("GRAP Rev. 29.09.2026: no Stage I to III action restricts a short walk")
@status("verified")
permit (
  principal == Persona::"commuter",
  action == Action::"lunch_walk",
  resource
) when { context.stage < 4 };

@id("commuter.lunch_walk.stage4_charter")
@clause("GRAP Rev. 29.09.2026, Stage IV citizen charter: citizens are advised to limit non-essential outdoor activity")
@status("verified")
@kind("advisory")
forbid (
  principal == Persona::"commuter",
  action == Action::"lunch_walk",
  resource
) when { context.stage >= 4 };

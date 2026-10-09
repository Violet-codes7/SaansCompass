// Delivery and gig rider rules, from CAQM's GRAP schedule for NCR,
// Revision 29.09.2026. See school.cedar for what the annotations mean.

@id("rider.two_wheeler.below_stage4")
@clause("GRAP Rev. 29.09.2026: no Stage I to III action restricts two-wheelers")
@status("verified")
permit (
  principal == Persona::"rider",
  action == Action::"outdoor_shift",
  resource
) when { context.stage < 4 };
// At Stage IV, item 5 lets states add emergency measures such as odd-even,
// so the shift has no policy there and shows "Check the official order".

@id("rider.bs3_petrol_bs4_diesel_car.stage3")
@clause("GRAP Rev. 29.09.2026, Stage III item 4: strict restrictions on BS-III petrol and BS-IV (or older) diesel four-wheelers (LMVs) in Delhi; exception for vehicles adapted for persons with disabilities")
@status("verified")
forbid (
  principal == Persona::"rider",
  action == Action::"drive_bs3_petrol_bs4_diesel_car",
  resource
) when { context.stage >= 3 };

@id("rider.bs3_petrol_bs4_diesel_car.below_stage3")
@clause("GRAP Rev. 29.09.2026: no Stage I or II action restricts these four-wheelers")
@status("verified")
permit (
  principal == Persona::"rider",
  action == Action::"drive_bs3_petrol_bs4_diesel_car",
  resource
) when { context.stage < 3 };

@id("rider.outside_lgv.stage3")
@clause("GRAP Rev. 29.09.2026, Stage III item 7: diesel BS-IV (or older) light goods vehicles registered outside Delhi may not enter Delhi")
@status("verified")
forbid (
  principal == Persona::"rider",
  action == Action::"drive_bs4_diesel_lgv_outside",
  resource
) when { context.stage >= 3 };

@id("rider.outside_lgv.below_stage3")
@clause("GRAP Rev. 29.09.2026: no Stage I or II action restricts these light goods vehicles")
@status("verified")
permit (
  principal == Persona::"rider",
  action == Action::"drive_bs4_diesel_lgv_outside",
  resource
) when { context.stage < 3 };

@id("rider.mgv.stage3")
@clause("GRAP Rev. 29.09.2026, Stage III items 5 and 6: strict restrictions on Delhi-registered diesel BS-IV (or older) medium goods vehicles in Delhi, and no entry for those registered outside Delhi")
@status("verified")
forbid (
  principal == Persona::"rider",
  action == Action::"drive_bs4_diesel_mgv",
  resource
) when { context.stage >= 3 };

@id("rider.mgv.below_stage3")
@clause("GRAP Rev. 29.09.2026: no Stage I or II action restricts these medium goods vehicles")
@status("verified")
permit (
  principal == Persona::"rider",
  action == Action::"drive_bs4_diesel_mgv",
  resource
) when { context.stage < 3 };

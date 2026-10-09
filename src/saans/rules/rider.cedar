// Delivery and gig rider rules. See school.cedar for what @status means.

@id("rider.diesel_goods_vehicle.stage4")
@clause("GRAP Stage IV: Delhi-registered BS-IV and older diesel goods vehicles barred except essential services. TO VERIFY")
@status("draft")
forbid (
  principal == Persona::"rider",
  action == Action::"drive_bs4_diesel_lcv",
  resource
) when { context.stage >= 4 };

@id("rider.diesel_goods_vehicle.below_stage4")
@clause("No GRAP restriction on these goods vehicles below Stage IV. TO VERIFY")
@status("draft")
permit (
  principal == Persona::"rider",
  action == Action::"drive_bs4_diesel_lcv",
  resource
) when { context.stage < 4 };

@id("rider.bs3_petrol_bs4_diesel_car.stage3")
@clause("GRAP Stage III: BS-III petrol and BS-IV diesel four-wheelers (LMV) restricted. TO VERIFY")
@status("draft")
forbid (
  principal == Persona::"rider",
  action == Action::"drive_bs3_petrol_bs4_diesel_car",
  resource
) when { context.stage >= 3 };

@id("rider.bs3_petrol_bs4_diesel_car.below_stage3")
@clause("No GRAP restriction on these cars below Stage III. TO VERIFY")
@status("draft")
permit (
  principal == Persona::"rider",
  action == Action::"drive_bs3_petrol_bs4_diesel_car",
  resource
) when { context.stage < 3 };

// The two-wheeler shift and rest break have no policy yet.

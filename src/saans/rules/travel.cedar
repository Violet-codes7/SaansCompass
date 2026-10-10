// How someone travels, for anyone whose profile says so. The commute
// activities are judged as travel_<mode>. See school.cedar for the annotations.
// travel_car has no policy here: a car's rule depends on its fuel and BS
// level, so a known car is judged by the car rules and an unknown one shows
// "Check the official order".
// At Stage IV, item 5 lets states add emergency measures such as odd-even,
// so road travel other than public transport has no policy there.

@id("travel.public_transport")
@clause("GRAP Rev. 29.09.2026: no stage restricts travel by metro or bus; the Stage II citizen charter asks people to use public transport and minimise use of personal vehicles")
@status("verified")
permit (
  principal,
  action in [Action::"travel_metro", Action::"travel_bus"],
  resource
);

@id("travel.on_foot_or_cycle.below_stage4")
@clause("GRAP Rev. 29.09.2026: no Stage I to III action restricts walking or cycling")
@status("verified")
permit (
  principal,
  action in [Action::"travel_walk", Action::"travel_cycle"],
  resource
) when { context.stage < 4 };

@id("travel.two_wheeler.below_stage4")
@clause("GRAP Rev. 29.09.2026: no Stage I to III action restricts two-wheelers")
@status("verified")
permit (
  principal,
  action == Action::"travel_two_wheeler",
  resource
) when { context.stage < 4 };

@id("travel.auto.below_stage4")
@clause("GRAP Rev. 29.09.2026: no Stage I to III action restricts CNG or electric autos and taxis")
@status("verified")
permit (
  principal,
  action == Action::"travel_auto",
  resource
) when { context.stage < 4 };

"""Plain-language explanations: GRAP rules, stages and AQI categories.

Each rule answer keeps its official clause and Cedar policy id; this module
only adds what it means for the person, why the rule exists, and what to do.
It never changes a decision.
"""
from .rules import ADVISED_AGAINST, ALLOWED, CHECK, NOT_ALLOWED

# What each GRAP stage is, in the AQI bands GRAP is defined on.
STAGES = {
    1: {"name": "Poor air", "band": "AQI 201 to 300",
        "about": "Early steps: dust control at building sites, strict PUC checks, no open burning."},
    2: {"name": "Very poor air", "band": "AQI 301 to 400",
        "about": "Stage I plus more: diesel generators limited, parking fees raised, people asked to use public transport."},
    3: {"name": "Severe air", "band": "AQI 401 to 450",
        "about": "Stage I and II plus: dusty construction stopped, older petrol and diesel cars off the road, hybrid classes up to Class V."},
    4: {"name": "Severe+ air", "band": "AQI above 450",
        "about": "Emergency level: most trucks barred, hybrid classes for more grades, and the advice to stay indoors as much as possible."},
}

# CPCB's own description of each AQI category's health impact.
CATEGORY_IMPACT = {
    "Good": "Minimal impact.",
    "Satisfactory": "Minor breathing discomfort for sensitive people.",
    "Moderate": "Breathing discomfort for people with lung disease such as asthma, and for people with heart disease, children and older adults.",
    "Poor": "Breathing discomfort for most people on long exposure.",
    "Very Poor": "Breathing illness on long exposure.",
    "Severe": "Affects healthy people and seriously affects people who are already ill.",
}

POLLUTANTS = {
    "PM2.5": "PM2.5: fine particles from traffic, smoke and burning. Small enough to reach deep into the lungs and the blood.",
    "PM10": "PM10: coarser dust from roads, building work and soil. It irritates the nose, throat and airways.",
}


def stage_headline(stage, day_aqi, category):
    """The big line in the stage box: never a bare "None"."""
    if stage is None:
        return {"title": "Stage unknown", "sub": "Not enough forecast data to estimate it."}
    if stage == 0:
        if category in ("Good", "Satisfactory"):
            sub = f"Air is okay today ({category})."
        elif category == "Moderate":
            sub = "Air is Moderate: no GRAP stage yet. Stage I starts at AQI 201."
        else:
            sub = f"AQI category: {category}."
        return {"title": "No restrictions today", "sub": sub}
    info = STAGES[stage]
    return {"title": f"Stage {['', 'I', 'II', 'III', 'IV'][stage]}: {info['name']}", "sub": info["about"]}


_CAR_STAGE3 = {
    "means": "You cannot drive a BS-III petrol or BS-IV (or older) diesel car in Delhi while Stage III or IV is in force.",
    "why": "Older engines give out far more smoke and fine particles. Taking them off the road is one of the quickest ways to cut pollution.",
    "do": "Take the metro or a bus, share a ride, or use a newer BS-VI car. Cars adapted for people with disabilities are exempt. Your car's BS level is on its registration certificate (RC).",
}
_CAR_OK = {
    "means": "You can drive this car today. The ban on older petrol and diesel cars only starts at Stage III.",
    "why": "GRAP adds rules step by step as the air gets worse.",
    "do": "Keep a valid PUC certificate: checks get stricter on bad-air days.",
}

POLICY = {
    "athlete.training.below_stage4": {
        "means": "You can train outdoors. GRAP does not limit exercise at this stage.",
        "why": "GRAP only asks people to cut outdoor activity at Stage IV, the worst level.",
        "do": "Still train at the cleanest hour shown here: hard exercise makes you breathe in many times more air.",
    },
    "athlete.training.stage4_charter": {
        "means": "At Stage IV, GRAP asks everyone to cut outdoor activity that is not essential, and a training run counts.",
        "why": "The air is severe. Hard exercise makes you breathe five to ten times more air, so you take in far more pollution.",
        "do": "Train indoors (gym, treadmill, home workout) or take a rest day. This is advice, not a ban.",
    },
    "commuter.bs3_petrol_bs4_diesel_car.stage3": _CAR_STAGE3,
    "rider.bs3_petrol_bs4_diesel_car.stage3": _CAR_STAGE3,
    "commuter.bs3_petrol_bs4_diesel_car.below_stage3": _CAR_OK,
    "rider.bs3_petrol_bs4_diesel_car.below_stage3": _CAR_OK,
    "commuter.private_car.stage2_charter": {
        "means": "From Stage II, GRAP asks people to leave the car at home and use public transport. It is advice, not a ban: a BS-VI car may still be driven.",
        "why": "Traffic is one of Delhi's biggest sources of PM2.5 in winter. Fewer cars means cleaner air for everyone, you included.",
        "do": "Take the metro or a bus, or share a ride for today.",
    },
    "commuter.private_car.below_stage2": {
        "means": "You can drive as usual.",
        "why": "GRAP only asks people to cut car use from Stage II.",
        "do": "In heavy traffic, keep the windows up and the air on recirculate.",
    },
    "commuter.office.below_stage3": {
        "means": "Go to the office as usual. GRAP does not change office attendance at this stage.",
        "why": "Work-from-home steps only come in at Stage III and above, and the state government decides them.",
        "do": None,
    },
    "commuter.lunch_walk.below_stage4": {
        "means": "A short walk is fine as far as GRAP goes.",
        "why": "GRAP only advises against non-essential outdoor activity at Stage IV.",
        "do": "Walk at the cleanest hour, on quieter streets away from traffic.",
    },
    "commuter.lunch_walk.stage4_charter": {
        "means": "At Stage IV, GRAP asks everyone to cut outdoor activity that is not essential. A lunch walk is one to skip.",
        "why": "Air this bad harms even healthy people.",
        "do": "Walk indoors instead: corridors, stairs or a mall. Eat lunch inside.",
    },
    "older.outdoor.stage4_charter": {
        "means": "At Stage IV, GRAP advises older people and people with lung, heart or long-term illness to stay indoors as much as possible.",
        "why": "Severe air can bring on breathing trouble, heart attacks and strokes, and the risk is highest for these groups.",
        "do": "Walk at home or indoors. If you must go out, keep it short, wear a well-fitted N95 and go at the cleanest hour.",
    },
    "older.outdoor.below_stage4": {
        "means": "GRAP does not limit walks or errands at this stage.",
        "why": "The advice to stay indoors starts at Stage IV.",
        "do": "Still go at the cleanest hour, and keep it gentle on poor-air days.",
    },
    "rider.two_wheeler.below_stage4": {
        "means": "You can ride your shift. GRAP does not limit two-wheelers at this stage.",
        "why": "No rule for two-wheelers is part of Stages I to III.",
        "do": "A well-fitted N95 under the helmet helps a lot. Take your break off the road at the worst hour.",
    },
    "rider.outside_lgv.stage3": {
        "means": "A BS-IV or older diesel light goods vehicle (a small truck or tempo) registered outside Delhi cannot enter Delhi at Stage III or IV.",
        "why": "Older diesel goods vehicles give out a lot of soot.",
        "do": "Use a Delhi-registered BS-VI, CNG or electric vehicle, and check the order for exemptions for essential goods.",
    },
    "rider.outside_lgv.below_stage3": {
        "means": "This vehicle can run today. The entry ban starts at Stage III.",
        "why": "GRAP adds rules step by step as the air gets worse.",
        "do": None,
    },
    "rider.mgv.stage3": {
        "means": "BS-IV or older diesel medium goods vehicles cannot run in Delhi at Stage III or IV, and those registered outside Delhi cannot enter.",
        "why": "Older diesel goods vehicles give out a lot of soot.",
        "do": "Switch to a BS-VI, CNG or electric vehicle, and check the order for exemptions for essential goods.",
    },
    "rider.mgv.below_stage3": {
        "means": "This vehicle can run today. The ban starts at Stage III.",
        "why": "GRAP adds rules step by step as the air gets worse.",
        "do": None,
    },
    "school.primary_hybrid.stage3": {
        "means": "Classes up to Class V must also run online. Families can choose to study from home.",
        "why": "Young children breathe faster and are harmed more by polluted air, and the trip to school adds to it.",
        "do": "Choose online classes if the school offers them, and check the school's notice for today.",
    },
    "school.primary_in_person.below_stage3": {
        "means": "Classes up to Class V run in person as usual.",
        "why": "Online classes for these grades only start at Stage III.",
        "do": None,
    },
    "school.senior_hybrid.stage4": {
        "means": "Classes VI to IX and XI must also run online at Stage IV. Families can choose to study from home.",
        "why": "At the worst level of pollution, GRAP cuts how many children travel to school.",
        "do": "Choose online if offered. Classes X and XII are not covered by this rule.",
    },
    "school.senior_in_person.below_stage4": {
        "means": "Classes VI to IX and XI run in person as usual.",
        "why": "Online classes for these grades only start at Stage IV.",
        "do": None,
    },
    "school.outdoor_activity.stage4_charter": {
        "means": "At Stage IV, GRAP advises that children stay indoors as much as possible, so assembly, recess and sport should move inside.",
        "why": "Children breathe more air for their size, and their lungs are still growing.",
        "do": "Hold assembly in the hall or classrooms, and do indoor games or stretches instead of outdoor PE.",
    },
    "school.outdoor_activity.below_stage4": {
        "means": "GRAP does not stop outdoor school activities at this stage.",
        "why": "The Delhi Education Department sometimes issues its own circular, so watch for one.",
        "do": "Use the cleanest hour of the school day for sport.",
    },
    "charter.sensitive_groups.stage4": {
        "means": "Because of your age or health, GRAP's Stage IV advice is to stay indoors as much as possible, and this is outdoors.",
        "why": "Children, pregnant women, older people and people with lung, heart, stroke or long-term illness are hurt most by severe air.",
        "do": "Keep it indoors or skip it today. If you must go out, wear a well-fitted N95 and keep it short.",
    },
    "worker.dusty_cnd.stage3": {
        "means": "Dusty construction work (digging, demolition, brickwork, tile cutting, road work) has to stop across NCR at Stage III and IV.",
        "why": "Building dust is one of the biggest sources of PM10 in Delhi.",
        "do": "Switch to less dusty work such as finishing, plumbing or electrical if your site allows. Railway, metro, airport, hospital, defence and sanitation projects are exempt. Registered construction workers have received support payments during past bans: ask your union or the construction workers' welfare board.",
    },
    "worker.dusty_cnd.below_stage3": {
        "means": "The work can go on, but the site must control dust: water spraying, covered sand and soil, screens around the site.",
        "why": "Stages I and II cut dust without stopping work.",
        "do": "Wear a well-fitted N95 for the dustiest jobs.",
    },
    "worker.other_cnd.permitted": {
        "means": "Less dusty work like finishing, plumbing, carpentry and electrical can carry on.",
        "why": "GRAP only stops the dustiest work; the rest must follow dust-control rules.",
        "do": "Wear an N95 when there is dust in the air.",
    },
    "worker.outdoor_shift.below_stage4": {
        "means": "GRAP does not stop outdoor work in general at this stage.",
        "why": "Only specific dusty or polluting work is restricted below Stage IV.",
        "do": "Take your break indoors at the worst hour, and drink plenty of water.",
    },
}

# No rule matched: what that means for each activity. Never "Allowed".
UNCOVERED = {
    "outdoor_shift": {
        "means": "At Stage IV, the government may add steps such as odd-even or closing some businesses. Whether they touch your work depends on the day's order.",
        "why": "Stage IV is the emergency level, and these steps are announced by the Delhi government.",
        "do": "Check the Delhi government order and your app's notices before your shift.",
    },
    "outdoor_work_shift": {
        "means": "At Stage IV, the government may close non-emergency work. Whether your site is covered depends on the day's order.",
        "why": "Stage IV is the emergency level, and these steps are announced by the Delhi government.",
        "do": "Ask your contractor or site office, and check the Delhi government order.",
    },
    "office_attendance": {
        "means": "At Stage III and IV, the Delhi government can ask offices to let half their staff work from home. It is not automatic.",
        "why": "Fewer people travelling means less traffic pollution.",
        "do": "Check your employer's notice and the Delhi government order for today. Work from home if you can.",
    },
    "school_commute": {
        "means": "GRAP has no rule about the trip to school itself.",
        "why": "The rules cover vehicles and schools, not people travelling.",
        "do": "Prefer the school bus or metro over a private car, and keep the walk away from main roads.",
    },
    "morning_commute": {
        "means": "GRAP has no rule about the trip itself.",
        "why": "The rules cover vehicles, not people travelling. See the car rules here if you drive.",
        "do": "The metro or a bus is the cleaner choice on a bad-air day.",
    },
    "evening_commute": {
        "means": "GRAP has no rule about the trip itself.",
        "why": "The rules cover vehicles, not people travelling. See the car rules here if you drive.",
        "do": "The metro or a bus is the cleaner choice on a bad-air day.",
    },
}
_UNCOVERED_DEFAULT = {
    "means": "GRAP's schedule does not cover this, so we cannot say it is allowed.",
    "why": "We only say Allowed when a rule says so.",
    "do": "Check the latest CAQM order, or ask your employer or school.",
}

HEADLINE = {
    ALLOWED: "You can",
    NOT_ALLOWED: "Not allowed today",
    ADVISED_AGAINST: "Best avoided today",
    CHECK: "Check the official order",
}


def rule_text(activity_id, rule):
    """{means, why, do} for one rule answer (a RuleResult dict)."""
    if rule["decision"] == CHECK:
        if rule.get("policy_id"):  # only a draft rule matched
            return {"means": "The rule we have for this is a draft that has not been checked against the latest CAQM order.",
                    "why": "We only give an answer when the rule is verified.",
                    "do": _UNCOVERED_DEFAULT["do"]}
        return UNCOVERED.get(activity_id, _UNCOVERED_DEFAULT)
    return POLICY.get(rule["policy_id"], {"means": rule.get("clause"), "why": None, "do": None})

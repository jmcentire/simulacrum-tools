"""Curriculum spine for the first twenty management simulator sessions."""

from __future__ import annotations

from typing import Any


FULL_SESSION_GOAL = (
    "Build a team that can deliver a messy product mission while learning who "
    "needs autonomy, who needs clarity, where the team is fragile, and what "
    "you are willing to cut when reality disagrees with the plan."
)


WEEK_GOALS = {
    1: {
        "title": "Learn The Team Before You Shape It",
        "goal": "Map the current team, cut the impossible roadmap into a real bet, and make one hire before the offer window closes.",
        "deliverable": "End-of-week project report: what you learned, what you cut, who you hired, and what you are betting on.",
    },
    2: {
        "title": "Rebuild Under Constraint",
        "goal": "Respond to a budget cut, terminate two roles, preserve the work that matters, and decide whether one backfill hire is worth the ramp cost.",
        "deliverable": "End-of-week project report: what changed, who was cut, what risk you accepted, and whether you used the backfill slot.",
    },
    3: {
        "title": "Operate With The Team You Built",
        "goal": "Run the team through normal work, ambiguity, and early friction without hiding behind process.",
        "deliverable": "End-of-week project report: what the team can now do without you and where the system is still fragile.",
    },
    4: {
        "title": "Absorb Shock",
        "goal": "Handle changing goals and a product crisis while preserving the people and systems that make recovery possible.",
        "deliverable": "Final project report: what you built, what broke, what you missed, and what you would do differently.",
    },
}


DAY_PLANS = {
    1: {
        "title": "Initial Read",
        "goal": "Read the mission, inspect the team, and identify the first three constraints you think will matter.",
        "deliverable": "Team report: who appears strongest, where you suspect fragility, and what you do not yet know.",
        "brief": "The company wants a reliable workflow platform for mid-market customers. The roadmap is six projects wearing one quarter.",
    },
    2: {
        "title": "Discover Motivations",
        "goal": "Use 1:1s to learn what people want to own and what drains them.",
        "deliverable": "Team report: who needs autonomy, who needs clarity, and where you may be projecting your own preferences.",
        "brief": "The CTO asks for an early read on whether the team can absorb another major commitment without losing quality.",
    },
    3: {
        "title": "Cut The Roadmap",
        "goal": "Turn the oversized roadmap into a sequence of bets instead of a list of wishes.",
        "deliverable": "Team report: what you would cut first and which person is carrying hidden risk.",
        "brief": "Sales adds two enterprise customers to the forecast and expects a deadline answer by Friday.",
    },
    4: {
        "title": "Interview Window",
        "goal": "Review five candidates, choose two interviews, and decide what gap you are actually hiring for.",
        "deliverable": "Team report: what the team lacks, what the hire should own, and what risk you are accepting.",
        "brief": "Finance approves one headcount slot, but the best candidate may not be the cheapest candidate.",
    },
    5: {
        "title": "Make The Offer",
        "goal": "Choose one hire before the offer window closes and explain the tradeoff.",
        "deliverable": "Team report plus week-one project report.",
        "brief": "The candidate pool expires tonight. If you wait, the slot rolls into next quarter.",
    },
    6: {
        "title": "Budget Cut",
        "goal": "Understand the impact of a sudden budget reduction and identify what must change.",
        "deliverable": "Team report: who is at risk, what work no longer fits, and what you are not willing to lose.",
        "brief": "The board cuts operating budget by 18%. You must reduce two roles this week.",
    },
    7: {
        "title": "Evaluate The Team",
        "goal": "Compare actual contribution, ramp, redundancy, and future risk before choosing cuts.",
        "deliverable": "Team report: which two roles you are considering and what evidence supports that choice.",
        "brief": "Your boss wants a termination recommendation, not a morale speech.",
    },
    8: {
        "title": "Termination Decision",
        "goal": "Select two roles to terminate and identify the consequences you are creating.",
        "deliverable": "Team report: what capability you are losing and how you plan to cover it.",
        "brief": "The reduction is due today. Delaying it burns political capital and makes the cut larger.",
    },
    9: {
        "title": "Backfill Decision",
        "goal": "Decide whether one backfill hire is worth the ramp cost after the cuts.",
        "deliverable": "Team report: what gap remains and whether a backfill would solve it or make it worse.",
        "brief": "Finance releases one replacement slot, but only if you can defend the role and salary.",
    },
    10: {
        "title": "Stabilize The New Team",
        "goal": "Make the backfill choice or decline it, then reframe the roadmap for the smaller team.",
        "deliverable": "Team report plus week-two project report.",
        "brief": "The remaining team needs a plan they can believe. The backfill offer expires tonight.",
    },
    11: {
        "title": "Operating Rhythm",
        "goal": "Set the operating rhythm for the team you actually have, not the team you wanted.",
        "deliverable": "Team report: where you are spending attention and where you are intentionally not intervening.",
        "brief": "The new team has stopped talking about the layoffs directly, but the work has slowed.",
    },
    12: {
        "title": "Dependencies",
        "goal": "Find the knowledge silo and dependency chain before they become an outage.",
        "deliverable": "Team report: what only one person knows and how you will reduce that risk.",
        "brief": "A cross-team dependency slips by two weeks and product asks you to absorb the delay.",
    },
    13: {
        "title": "Team Friction",
        "goal": "Notice the pairwise friction that is consuming energy without appearing on the roadmap.",
        "deliverable": "Team report: who is avoiding whom, what is being left unsaid, and what intervention fits.",
        "brief": "Two engineers disagree in design review, but both insist everything is fine afterward.",
    },
    14: {
        "title": "Change The Goal",
        "goal": "Respond to a goal change without making the team feel like the work was pointless.",
        "deliverable": "Team report: what changed, what remains true, and what you are explicitly dropping.",
        "brief": "The CEO changes the success metric from feature adoption to enterprise reliability.",
    },
    15: {
        "title": "Quiet Decay",
        "goal": "Look for decay that does not announce itself through an incident.",
        "deliverable": "Team report: leading indicators you are watching and why they matter.",
        "brief": "Velocity looks fine, but support tickets and on-call fatigue are climbing.",
    },
    16: {
        "title": "Customer Escalation",
        "goal": "Protect the team while responding to a high-value customer escalation.",
        "deliverable": "Team report: what you escalated, what you contained, and what you asked the team to do.",
        "brief": "A strategic customer threatens to leave after a production regression.",
    },
    17: {
        "title": "Incident",
        "goal": "Reduce blast radius first, then decide what not to fix today.",
        "deliverable": "Team report: who owned the incident, what you learned, and what debt remains.",
        "brief": "A release corrupts customer data in one region. The root cause is not yet clear.",
    },
    18: {
        "title": "Recovery",
        "goal": "Turn the incident into better structure instead of a heroic story.",
        "deliverable": "Team report: what changed structurally and what remains a human-dependent risk.",
        "brief": "Executives want a postmortem and a delivery-date promise by end of day.",
    },
    19: {
        "title": "Retention Risk",
        "goal": "Notice who is checking out before they disappear.",
        "deliverable": "Team report: whose battery is low, what evidence you saw, and what you will do.",
        "brief": "A recruiter reaches out to one of your strongest people during the recovery period.",
    },
    20: {
        "title": "Final Review",
        "goal": "Summarize what team you built, what tradeoffs you made, and what your next move would be.",
        "deliverable": "Team report plus final project report.",
        "brief": "The board review is tomorrow. They want the story of the team, not the story of excuses.",
    },
}


def week_for_day(day: int) -> int:
    return min(4, max(1, (day - 1) // 5 + 1))


def day_in_week(day: int) -> int:
    return ((day - 1) % 5) + 1


def plan_for_day(day: int) -> dict[str, Any]:
    day = max(1, min(20, day))
    week = week_for_day(day)
    return {
        "day": day,
        "week": week,
        "day_in_week": day_in_week(day),
        "full_session_goal": FULL_SESSION_GOAL,
        "week_goal": WEEK_GOALS[week],
        **DAY_PLANS[day],
    }

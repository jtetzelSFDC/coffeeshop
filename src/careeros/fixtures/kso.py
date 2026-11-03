"""A made-up KSO framework for tests and the practice notebook. Not the real rubric, which is internal."""
from __future__ import annotations


def _levels(what: str) -> dict:
    return {"1": f"No {what} to speak of.", "2": f"A little {what}, now and then.", "3": f"Some {what}, unevenly.",
            "4": f"Steady {what}, written down as it happens.", "5": f"Standout {what} that others copy."}


FRAMEWORK = dict(
    fiscal_year="FY27", track="Delivery", rated="yearly",
    payout={"1": 0, "2": 40, "3": 70, "4": 100, "5": 120},
    level_names={"1": "Missed", "2": "Partly there", "3": "Mostly there", "4": "There", "5": "Beyond"},
    ksos=[
        dict(key="1", name="Calm Releases", weight=20, what="How smoothly the work you own ships.",
             components=[
                 dict(key="1.1", name="Plan Kept", what="Did the plan in your V2MOM happen? Write results there.",
                      levels=_levels("plan kept"),
                      examples=["Mark one V2MOM measure's progress after today's release",
                                "Write a two-line release note for the team"]),
                 dict(key="1.2", name="Kind Feedback", what="What people say about working with you.",
                      levels=_levels("praise"),
                      examples=["Ask one teammate how the last handoff went", "Save a thank-you message as a record"]),
             ]),
        dict(key="2", name="Sharper Tools", weight=10, what="How you grow, and how you bring new tools in.",
             components=[
                 dict(key="2.1", name="New Skills", what="Learning you planned, and used.",
                      levels=_levels("learning"),
                      examples=["Finish one short course unit", "Use one new trick at work and note it"]),
                 dict(key="2.2", name="Helper Bots", what="Trying new AI tools and sharing what works.",
                      levels=_levels("tool use"),
                      examples=["Try an AI helper on one chore today", "Share one prompt that saved you time"]),
             ]),
    ],
    dates=[dict(date="2026-12-18", what="Manager ratings due")],
)


def reply(fy: str = "FY27", **changes) -> dict:
    """What Claude would answer for the made-up material: FRAMEWORK, with `changes` applied on top."""
    import copy
    out = copy.deepcopy(FRAMEWORK)
    out["fiscal_year"] = fy
    out.update(changes)
    return out

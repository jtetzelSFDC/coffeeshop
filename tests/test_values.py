"""Values & Behaviors: the bundled workbook's English columns, and a guide-review pick of at most two."""
from sqlalchemy import select

from coffeeshop.guide import ai_review
from coffeeshop.storage.models import CompetencyItem, CompetencyLink, JournalEntry
from coffeeshop.values import links
from coffeeshop.values.parse import parse_behaviors

from helpers import add, form, open_session


def test_english_behaviors_are_read_and_a_review_keeps_two(nb):
    parsed = {(i["value"], i["name"]): i["description"] for i in parse_behaviors()}
    assert parsed["Trust", "Act with Integrity"].startswith("Gaining others")
    assert parsed["Customer Success", "Communicate Effectively"].startswith("Conveying information")
    assert len(parsed) == 13 and all("Tell me about" not in text for text in parsed.values())

    dd, c, token, _ = nb
    with open_session(dd) as s:
        already = add(s, "Already read against the guide")
        s.get(JournalEntry, already).ai_read = True
        s.commit()
        fresh = add(s, "Stopped the rollout because the service was not ready")
        seen = {}

        def read(guide, themes, records, v2mom=None, values=None):
            seen["values"] = values
            picks = [values[0]["id"], values[1]["id"], values[0]["id"], "NOPE", values[2]["id"]]
            return {r["id"]: dict(guide=[], kind=r["kind"], win=None,
                                  values=picks if "rollout" in r["text"] else []) for r in records}

        got = ai_review.review(s, reader=read)
        sent = seen["values"]
        assert got["values"] == 2 and sent[0]["id"] == "V1" and sent[0]["value"] == "Trust"
        assert sent[0]["name"] == "Act with Integrity" and "Acts with integrity" in sent[0]["description"]
        assert (sent[1]["value"], sent[1]["name"]) == ("Customer Success", "Communicate Effectively")
        assert len(sent) == 13 and "Tell me about" not in sent[0]["description"]
        saved = list(s.scalars(select(CompetencyItem.name).join(
            CompetencyLink, CompetencyLink.item_id == CompetencyItem.id).where(CompetencyLink.entry_id == fresh)
            .order_by(CompetencyItem.position)))
        assert saved == ["Act with Integrity", "Communicate Effectively"]
        assert all(l.by_ai for l in s.scalars(select(CompetencyLink)))
        assert [e.id for e in links.pending(s)] == [already]
        lid = s.scalar(select(CompetencyLink.id).join(CompetencyItem).where(
            CompetencyLink.entry_id == fresh, CompetencyItem.name == "Communicate Effectively"))

    page = c.get("/sheet?show=ai").text
    assert page.index("V2MOM: the methods this record moves forward.") < page.index(
        "Values: the behaviors this record shows.") < page.index("Win: small, medium, or large.")
    assert "AI: Act with Integrity" in page and "AI: Communicate Effectively" in page
    assert form(c, f"/sheet/values/{lid}/delete", token).status_code == 303
    with open_session(dd) as s:
        assert s.get(JournalEntry, fresh).values_fixed
        assert [i.name for i in s.scalars(select(CompetencyItem).join(
            CompetencyLink, CompetencyLink.item_id == CompetencyItem.id))] == ["Act with Integrity"]
        ai_review.review(s, redo=True, reader=read)
        assert [i.name for i in s.scalars(select(CompetencyItem).join(
            CompetencyLink, CompetencyLink.item_id == CompetencyItem.id))] == ["Act with Integrity"]
    assert "AI: Act with Integrity" in c.get("/sheet?show=ai").text
    assert form(c, f"/sheet/{fresh}/ok", token).status_code == 303
    with open_session(dd) as s:
        assert s.scalar(select(CompetencyLink)).by_ai is False and s.get(JournalEntry, fresh).reviewed
    assert "Stopped the rollout" not in c.get("/sheet?show=ai").text

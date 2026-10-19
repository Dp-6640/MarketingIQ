"""Assistant runs end to end on the tiny world, with a scripted model and the app role."""

import pytest
from sqlalchemy import text

from marketingiq.assistant.llm import Reply, ScriptedModel, call
from marketingiq.assistant.run import ask
from marketingiq.core.build import build_core
from marketingiq.ingest.loader import load_dataset
from synthetic.export import generate

pytestmark = pytest.mark.integration

ORG = "synthetic-home-services"
QUARTER = {"preset": "custom", "start": "2026-01-01", "end": "2026-03-31"}
SPEND = {"period": QUARTER, "group_by": ["campaign"], "metrics": ["spend", "leads"]}


@pytest.fixture(scope="module")
def engines(migrated_module, app_role_engine, tmp_path_factory):
    load_dataset(migrated_module, generate("tiny", 7, tmp_path_factory.mktemp("dataset")))
    build_core(migrated_module, ORG)
    return migrated_module, app_role_engine(migrated_module)


def submit(answer: str, status: str = "answered") -> Reply:
    return Reply(None, [call("submit_answer", {"status": status, "answer": answer})])


def stored(owner, run_id) -> dict:
    with owner.connect() as conn:
        return dict(
            conn.execute(text("SELECT * FROM app.assistant_runs WHERE id = :id"), {"id": run_id})
            .mappings()
            .one()
        )


def test_an_answer_cites_tool_results_and_is_logged(engines):
    owner, app = engines
    model = ScriptedModel(
        [
            Reply(None, [call("get_performance", SPEND)]),
            submit("Spend was {{c1:totals.spend}} on {{c1:totals.leads}} leads credited."),
        ]
    )

    run = ask("What did we spend last quarter?", engine=app, org=ORG, model=model)

    assert run.status == "answered", run.errors
    spend = run.results["c1"]["totals"]["spend"]["value"]
    assert f"${spend:,.2f}" in run.answer
    assert [c.path for c in run.rendered.citations] == ["totals.spend", "totals.leads"]
    assert "synthetic_data" in [c["code"] for c in run.rendered.caveats]
    row = stored(owner, run.id)
    assert row["status"] == "answered" and row["trace"]["calls"][0]["tool"] == "get_performance"


def test_the_prompt_states_the_data_date_and_that_data_is_synthetic(engines):
    _, app = engines
    model = ScriptedModel([submit("Out of scope.", "refuse")])

    ask("List the phone numbers of Barrie leads.", engine=app, org=ORG, model=model, store=False)

    system = model.seen[0][0]["content"]
    assert "2026-03-31" in system and "SYNTHETIC" in system


def test_a_typed_number_gets_one_retry(engines):
    _, app = engines
    model = ScriptedModel(
        [
            Reply(None, [call("get_performance", SPEND)]),
            submit("Spend was 1234 dollars."),
            submit("Spend was {{c1:totals.spend}}."),
        ]
    )

    run = ask("Spend?", engine=app, org=ORG, model=model, store=False)

    assert run.status == "answered"
    assert "typed, not referenced" in run.errors[0]
    retry_feedback = model.seen[2][-1]["content"]
    assert "1234" in retry_feedback


def test_two_broken_answers_fail_the_run(engines):
    owner, app = engines
    model = ScriptedModel([submit("About 40 leads."), submit("Roughly 40 leads.")])

    run = ask("Leads?", engine=app, org=ORG, model=model)

    assert run.status == "failed" and run.answer is None
    assert stored(owner, run.id)["status"] == "failed"


def test_invalid_arguments_go_back_to_the_model_with_details(engines):
    _, app = engines
    bad = {"period": QUARTER, "metrics": ["revenue_magic"]}
    model = ScriptedModel(
        [
            Reply(None, [call("get_performance", bad)]),
            Reply(None, [call("get_performance", SPEND)]),
            submit("Spend was {{c1:totals.spend}}."),
        ]
    )

    run = ask("Spend?", engine=app, org=ORG, model=model, store=False)

    assert run.status == "answered"
    assert [c.ok for c in run.calls] == [False, True]
    feedback = model.seen[1][-1]["content"]
    assert "invalid arguments" in feedback and "metrics" in feedback


def test_an_ambiguous_name_leads_to_a_clarifying_answer(engines):
    _, app = engines
    lookup = {"dimension": "campaign", "search": "furnace"}
    model = ScriptedModel(
        [
            Reply(None, [call("list_dimension_values", lookup)]),
            submit(
                "Which one: {{c1:values[0].label}} or {{c1:values[1].label}}?", status="clarify"
            ),
        ]
    )

    run = ask("How is the furnace campaign doing?", engine=app, org=ORG, model=model, store=False)

    assert run.status == "clarify"
    assert run.results["c1"]["match"] == "several"


def test_the_app_role_cannot_change_anything_but_its_log(engines):
    _, app = engines
    with app.connect() as conn, pytest.raises(Exception, match="permission denied"):
        conn.execute(text("DELETE FROM app.assistant_runs"))


def test_a_run_says_where_its_time_went(engines):
    _, app = engines
    model = ScriptedModel(
        [
            Reply(None, [call("get_performance", SPEND)], model_ms=1200, wait_ms=4000),
            Reply(
                None,
                [call("submit_answer", {"status": "answered", "answer": "{{c1:totals.spend}}"})],
                model_ms=800,
                rate_limited=1,
            ),
        ]
    )

    timing = ask("Spend?", engine=app, org=ORG, model=model, store=False).timing()

    assert timing["model_ms"] == 2000 and timing["waiting_ms"] == 4000
    assert timing["model_requests"] == 2 and timing["rate_limited"] == 1
    assert timing["tools_ms"] >= 0 and timing["total_ms"] >= 0

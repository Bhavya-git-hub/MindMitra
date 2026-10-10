"""Training writes verifiable models; the service loads only those; the endpoints answer in bands
and never echo what a student wrote."""

import datetime as dt
import json
import logging
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest

from inference.indicators import assess, score_texts
from inference.registry import MANIFEST, ModelsUnavailable, Registry, load
from preprocessing.records import DailyRecord
from training.indicators import TABULAR_INDICATORS

Client = Callable[..., httpx.AsyncClient]
EXPECTED = tuple(s.name for s in TABULAR_INDICATORS)
END = dt.date(2026, 10, 9)
METRICS = {"accuracy", "precision", "recall", "f1", "roc_auc", "confusion_matrix"}


def _days(n: int, **values: Any) -> list[dict[str, Any]]:
    return [{"day": (END - dt.timedelta(days=i)).isoformat(), **values} for i in range(n)]


def _strained(n: int = 14) -> list[DailyRecord]:
    return [
        DailyRecord(
            day=END - dt.timedelta(days=i),
            mood=1,
            energy=1,
            stress=5,
            sleep_minutes=270,
            sleep_quality=1,
            bedtime_hour=3.0,
            emotions=("lonely", "anxious", "overwhelmed", "tired"),
            stressors=("exams", "deadlines", "workload", "career"),
        )
        for i in range(n)
    ]


def _settled(n: int = 14) -> list[DailyRecord]:
    return [
        DailyRecord(
            day=END - dt.timedelta(days=i),
            mood=5,
            energy=5,
            stress=1,
            sleep_minutes=480,
            sleep_quality=5,
            bedtime_hour=22.5,
            emotions=("calm", "hopeful"),
        )
        for i in range(n)
    ]


# ---- training output ------------------------------------------------------------------------


def test_every_model_is_reported_with_the_requested_metrics(
    trained: tuple[Path, list[dict[str, Any]]],
) -> None:
    _, reports = trained
    assert [r["indicator"] for r in reports] == [*EXPECTED, "sentiment"]
    for r in reports:
        assert METRICS <= set(r["test"]), r["indicator"]
        assert r["selected"] in r["candidates"]
        assert r["test"]["roc_auc"] > 0.6, r["indicator"]  # well above chance, even when quick


def test_the_report_page_says_the_data_is_synthetic(
    trained: tuple[Path, list[dict[str, Any]]],
) -> None:
    page = (trained[0].parent / "reports" / "REPORT.md").read_text()
    assert "Synthetic data only" in page
    assert "not a clinical" in page or "none of these models is a clinical" in page


def test_the_full_run_compares_logistic_regression_random_forest_and_xgboost() -> None:
    from preprocessing.pipelines import TABULAR_CANDIDATES

    assert TABULAR_CANDIDATES == ("logistic_regression", "random_forest", "xgboost")


# ---- loading safely -------------------------------------------------------------------------


def _copy(trained: tuple[Path, list[dict[str, Any]]], tmp_path: Path) -> Path:
    target = tmp_path / "models"
    shutil.copytree(trained[0], target)
    return target


def test_a_missing_directory_is_unavailable_not_an_error(tmp_path: Path) -> None:
    with pytest.raises(ModelsUnavailable, match="no trained models"):
        load(tmp_path / "nothing", EXPECTED)


def test_a_changed_model_file_is_refused(
    trained: tuple[Path, list[dict[str, Any]]], tmp_path: Path
) -> None:
    models = _copy(trained, tmp_path)
    with (models / "burnout_risk" / "model.joblib").open("ab") as f:
        f.write(b"tampered")
    with pytest.raises(ModelsUnavailable, match="does not match"):
        load(models, EXPECTED)


def test_models_from_other_library_versions_are_refused(
    trained: tuple[Path, list[dict[str, Any]]], tmp_path: Path
) -> None:
    models = _copy(trained, tmp_path)
    manifest = json.loads((models / MANIFEST).read_text())
    manifest["libraries"]["scikit-learn"] = "0.1.0"
    (models / MANIFEST).write_text(json.dumps(manifest))
    with pytest.raises(ModelsUnavailable, match="different scikit-learn"):
        load(models, EXPECTED)


def test_a_path_outside_the_model_directory_is_refused(
    trained: tuple[Path, list[dict[str, Any]]], tmp_path: Path
) -> None:
    models = _copy(trained, tmp_path)
    manifest = json.loads((models / MANIFEST).read_text())
    manifest["models"]["career_anxiety"]["file"] = "../elsewhere.joblib"
    (models / MANIFEST).write_text(json.dumps(manifest))
    with pytest.raises(ModelsUnavailable, match="outside"):
        load(models, EXPECTED)


# ---- predictions ----------------------------------------------------------------------------


def test_strained_check_ins_score_higher_than_settled_ones(registry: Registry) -> None:
    strained = {i.indicator: i for i in assess(registry, _strained(), window_end=END).indicators}
    settled = {i.indicator: i for i in assess(registry, _settled(), window_end=END).indicators}
    for name in EXPECTED[1:]:
        assert strained[name].band == "elevated", name
        assert settled[name].band != "elevated", name
        assert strained[name].probabilities["elevated"] > settled[name].probabilities["elevated"]
    assert strained["stress_level"].level == "high"
    assert settled["stress_level"].level == "low"


def test_too_few_check_ins_give_not_enough_data(registry: Registry) -> None:
    result = assess(registry, _strained(3), ["fine", "ok"], window_end=END)
    assert {i.status for i in result.indicators} == {"not_enough_data"}
    assert all(i.band is None for i in result.indicators)


def test_note_tone_is_a_share_of_notes(registry: Registry) -> None:
    notes = [
        "Feeling so stressed and exhausted about the exam.",
        "I feel lonely in the hostel tonight.",
        "Everything is piling up and I'm overwhelmed.",
        "Had the quiz today.",
    ]
    tone = assess(registry, _settled(), notes, window_end=END).indicators[-1]
    assert tone.indicator == "sentiment"
    assert tone.status == "ok"
    assert tone.band == "elevated"
    assert tone.probabilities["negative"] >= 0.5
    labels = [s.label for s in score_texts(registry, ["So relieved, I cleared the viva."])]
    assert labels == ["positive"]


# ---- HTTP -----------------------------------------------------------------------------------

URL = "/internal/v1/indicators"


async def test_indicators_need_the_service_token(make_client: Client, registry: Registry) -> None:
    r = await make_client(None, registry).post(URL, json={"window_end": END.isoformat()})
    assert r.status_code == 401


async def test_indicators_come_back_in_bands_with_a_disclaimer(
    make_client: Client, registry: Registry, auth_header: dict[str, str]
) -> None:
    body = {
        "window_end": END.isoformat(),
        "days": _days(10, mood=2, stress=4, energy=2, emotions=["tired"], stressors=["exams"]),
        "notes": ["so stressed about the exam", "tired today", "had the quiz"],
    }
    r = await make_client(None, registry).post(URL, json=body, headers=auth_header)
    assert r.status_code == 200
    data = r.json()
    assert [i["indicator"] for i in data["indicators"]] == [*EXPECTED, "sentiment"]
    assert data["checkin_days"] == 10
    assert "not a diagnosis" in data["disclaimer"]
    for i in data["indicators"]:
        assert i["band"] in ("low", "moderate", "elevated")
        assert i["model_version"]


async def test_invalid_input_is_refused_without_echoing_it(
    make_client: Client, registry: Registry, auth_header: dict[str, str]
) -> None:
    secret_note = "my private note about my roommate"
    body = {"window_end": END.isoformat(), "days": _days(1, mood=9), "notes": [secret_note] * 61}
    r = await make_client(None, registry).post(URL, json=body, headers=auth_header)
    assert r.status_code == 422
    assert secret_note not in r.text
    assert "body.days.0.mood" in r.json()["fields"]


async def test_nothing_a_student_wrote_is_logged(
    make_client: Client,
    registry: Registry,
    auth_header: dict[str, str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    note = "a very particular sentence about my week"
    caplog.set_level(logging.DEBUG)
    await make_client(None, registry).post(
        "/internal/v1/sentiment", json={"texts": [note]}, headers=auth_header
    )
    assert note not in caplog.text


async def test_sentiment_scores_each_text(
    make_client: Client, registry: Registry, auth_header: dict[str, str]
) -> None:
    r = await make_client(None, registry).post(
        "/internal/v1/sentiment",
        json={"texts": ["I feel awful and lonely", "Went to the library"]},
        headers=auth_header,
    )
    assert r.status_code == 200
    results = r.json()["results"]
    assert [x["label"] for x in results] == ["negative", "neutral"]
    assert set(results[0]["probabilities"]) == {"negative", "neutral", "positive"}


async def test_without_models_the_endpoints_say_unavailable_and_the_companion_still_works(
    make_client: Client, auth_header: dict[str, str]
) -> None:
    client = make_client(None)
    r = await client.post(URL, json={"window_end": END.isoformat()}, headers=auth_header)
    assert r.status_code == 503
    models = (await client.get("/internal/v1/models", headers=auth_header)).json()
    assert models["indicator_models"] == {}
    assert "no trained models" in models["indicators_unavailable"]
    reply = await client.post(
        "/internal/v1/companion/respond", json={"message": "exams next week"}, headers=auth_header
    )
    assert reply.status_code == 200


async def test_models_endpoint_lists_every_indicator_version(
    make_client: Client, registry: Registry, auth_header: dict[str, str]
) -> None:
    data = (
        await make_client(None, registry).get("/internal/v1/models", headers=auth_header)
    ).json()
    assert set(data["indicator_models"]) == {*EXPECTED, "sentiment"}
    assert data["indicators_unavailable"] is None

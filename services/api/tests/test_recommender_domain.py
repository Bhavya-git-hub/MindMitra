"""The recommendation engine's pure rules: what each problem area looks like in a student's
records, what is offered for it, and how a student's feedback changes what comes next.

Every record here is synthetic.
"""

import dataclasses
import datetime as dt
import uuid

import pytest

from app.domain.wellness.recommender import learning, needs, ranking, signals
from app.domain.wellness.recommender.catalog import (
    BY_KEY,
    CATALOG,
    COUNSELLING,
    MUTABLE_AREAS,
)

TODAY = dt.date(2026, 10, 12)
NOW = dt.datetime(2026, 10, 12, 9, 0, tzinfo=dt.UTC)


def _days(n: int = 10, **kw: object) -> list[signals.Day]:
    return [
        signals.Day(day=TODAY - dt.timedelta(days=i), **kw)  # type: ignore[arg-type]
        for i in range(n)
    ]


def _signals(days: list[signals.Day], **ctx: object) -> signals.Signals:
    return signals.build(days, signals.Context(today=TODAY, **ctx))  # type: ignore[arg-type]


def _resource(*tags: str, kind: str = "article", minutes: int | None = 5) -> ranking.ResourceOption:
    return ranking.ResourceOption(uuid.uuid4(), "R " + "-".join(tags), kind, tags, minutes, "en")


# one vetted resource for every idea in the catalog
LIBRARY = [_resource(*iv.tags) for iv in CATALOG if iv.tags and iv.needs_resource]
LIBRARY.append(_resource("counselling", "support", "campus", kind="service", minutes=None))


def _keys(
    days: list[signals.Day],
    *,
    prefs: ranking.Preferences | None = None,
    past: list[ranking.Past] | None = None,
    responses: list[learning.Response] | None = None,
    options: list[ranking.ResourceOption] | None = None,
    **ctx: object,
) -> list[str]:
    picks = ranking.rank(
        _signals(days, **ctx),
        prefs or ranking.Preferences(),
        past or [],
        responses or [],
        LIBRARY if options is None else options,
        NOW,
    )
    return [p.intervention.key for p in picks]


# ---- problem areas map to their non-medical interventions ----------------------------------


def test_academic_burnout_gets_planning_breaks_and_counselling() -> None:
    days = _days(energy=1, stress=5, stressors=("exams", "deadlines"), mood=3)
    keys = _keys(days, credits=24)
    assert {"study_planning", "workload_planning", "scheduled_breaks"} <= set(keys)
    assert "counselling_academic" in keys


def test_career_anxiety_gets_placement_help_mock_interviews_and_mentoring() -> None:
    days = _days(stress=4, stressors=("career",), emotions=("anxious",), mood=3)
    keys = _keys(days, year_of_study=4)
    assert {"placement_resources", "mock_interviews", "career_mentoring"} <= set(keys)


def test_social_isolation_gets_clubs_peers_and_social_resources() -> None:
    days = _days(mood=2, emotions=("lonely",), stress=3)
    keys = _keys(days)
    assert {"join_a_club", "peer_activities", "social_resources"} <= set(keys)


def test_sleep_disruption_gets_hygiene_schedule_and_relaxation() -> None:
    days = [
        signals.Day(
            day=TODAY - dt.timedelta(days=i),
            sleep_minutes=300,
            sleep_quality=2,
            bedtime_hour=2.5 + (i % 3) * 1.0,
            mood=3,
        )
        for i in range(10)
    ]
    keys = _keys(days)
    assert {"sleep_hygiene", "sleep_schedule", "relaxation_wind_down"} <= set(keys)


def test_a_settled_fortnight_gets_nothing_to_do() -> None:
    days = _days(mood=4, energy=4, stress=2, sleep_minutes=450, sleep_quality=4, bedtime_hour=23.0)
    goal = {"mindfulness"}
    assert _keys(days, active_goal_categories=frozenset(goal)) == []


def test_too_few_check_ins_means_only_a_nudge_never_wellbeing_ideas() -> None:
    days = _days(2, mood=1, stress=5, energy=1, emotions=("lonely",), stressors=("exams",))
    keys = _keys(days)
    assert set(keys) <= {"set_a_goal", "check_in_nudge"}


def test_a_gap_in_check_ins_gets_a_nudge() -> None:
    days = [signals.Day(day=TODAY - dt.timedelta(days=5 + i), mood=3) for i in range(5)]
    assert "check_in_nudge" in _keys(days)


def test_indicators_alone_can_point_at_isolation() -> None:
    keys = _keys(_days(mood=3), indicators={"social_isolation": "elevated"})
    assert "join_a_club" in keys


def test_one_indicator_is_not_enough_for_burnout_without_other_evidence() -> None:
    keys = _keys(_days(mood=3), indicators={"burnout_risk": "elevated"})
    assert "study_planning" not in keys
    keys = _keys(_days(mood=3, energy=2), indicators={"burnout_risk": "elevated"})
    assert "study_planning" in keys


def test_a_low_indicator_band_adds_nothing() -> None:
    days = _days(mood=3, stress=2)
    keys = _keys(
        days,
        indicators={"burnout_risk": "low", "stress_level": "low"},
        active_goal_categories=frozenset({"sleep"}),
    )
    assert keys == []


# ---- counselling is the next step up, not the first ----------------------------------------


def test_counselling_only_appears_when_the_need_is_high() -> None:
    mild = _days(energy=3, stress=3, stressors=("exams",), mood=3)
    assert "counselling_academic" not in _keys(mild)


def test_one_signal_alone_does_not_bring_up_counselling() -> None:
    only_exams = _days(energy=4, stress=2, stressors=("exams", "deadlines", "workload"), mood=4)
    keys = _keys(only_exams, active_goal_categories=frozenset({"sleep"}))
    assert "study_planning" in keys
    assert "counselling_academic" not in keys


def test_counselling_comes_first_when_the_need_is_very_high() -> None:
    days = _days(
        energy=1, stress=5, stressors=("exams", "deadlines", "workload"), mood=2, sleep_minutes=270
    )
    picks = ranking.rank(
        _signals(days, credits=24, indicators={"burnout_risk": "elevated"}),
        ranking.Preferences(),
        [],
        [],
        LIBRARY,
        NOW,
    )
    assert picks[0].intervention.family == COUNSELLING


def test_only_one_counselling_suggestion_at_a_time() -> None:
    days = _days(
        energy=1, stress=5, stressors=("exams", "career"), emotions=("lonely", "anxious"), mood=1
    )
    picks = ranking.rank(
        _signals(days, credits=24, year_of_study=4), ranking.Preferences(), [], [], LIBRARY, NOW
    )
    assert sum(p.intervention.family == COUNSELLING for p in picks) == 1


def test_a_student_can_switch_counselling_off() -> None:
    days = _days(energy=1, stress=5, stressors=("exams",), mood=1)
    keys = _keys(days, prefs=ranking.Preferences(muted=frozenset({"counselling"})))
    assert not any(BY_KEY[k].family == COUNSELLING for k in keys)


def test_a_low_wellbeing_check_is_enough_to_offer_a_conversation() -> None:
    days = _days(mood=3)
    keys = _keys(days, assessment_band="lower")
    assert "counselling_general" in keys


# ---- limits and variety --------------------------------------------------------------------


def test_the_list_is_short_and_varied() -> None:
    days = _days(
        energy=1,
        stress=5,
        mood=1,
        sleep_minutes=240,
        sleep_quality=1,
        stressors=("exams", "career", "sleep"),
        emotions=("lonely", "anxious"),
    )
    picks = ranking.rank(
        _signals(days, credits=24, year_of_study=4), ranking.Preferences(), [], [], LIBRARY, NOW
    )
    assert len(picks) <= ranking.MAX_OPEN
    areas: dict[str, int] = {}
    for p in picks:
        if p.intervention.family is None:
            areas[p.intervention.area] = areas.get(p.intervention.area, 0) + 1
    assert max(areas.values()) <= ranking.MAX_PER_AREA


def test_an_idea_with_no_vetted_resource_is_not_offered() -> None:
    days = _days(mood=2, emotions=("lonely",), stress=3)
    assert "join_a_club" not in _keys(days, options=[])


def test_muted_areas_are_left_alone() -> None:
    days = _days(mood=2, emotions=("lonely",), stress=3)
    keys = _keys(days, prefs=ranking.Preferences(muted=frozenset({"social_isolation"})))
    assert not any(BY_KEY[k].area == "social_isolation" for k in keys)


def test_every_pick_says_why_in_plain_words() -> None:
    days = _days(mood=2, emotions=("lonely",), stress=3)
    picks = ranking.rank(_signals(days), ranking.Preferences(), [], [], LIBRARY, NOW)
    assert picks
    for p in picks:
        assert p.rationale
        if p.intervention.area != "engagement":
            assert p.rationale.startswith("Lately,")
        assert 0.0 < p.score <= 1.0


def test_goals_make_a_matching_idea_a_better_fit() -> None:
    days = _days(mood=3, energy=2, stress=4, stressors=("exams",))
    plain = {
        p.intervention.key: p.score
        for p in ranking.rank(_signals(days), ranking.Preferences(), [], [], LIBRARY, NOW)
    }
    goal = {
        p.intervention.key: p.score
        for p in ranking.rank(
            _signals(days, active_goal_categories=frozenset({"academic_balance"})),
            ranking.Preferences(),
            [],
            [],
            LIBRARY,
            NOW,
        )
    }
    assert goal["study_planning"] >= plain["study_planning"]


# ---- preferences ---------------------------------------------------------------------------


def test_a_preferred_format_wins_the_resource_choice() -> None:
    video = _resource("breaks", "movement", kind="video")
    article = _resource("breaks", "movement", kind="article")
    days = _days(energy=1, stress=5, stressors=("exams",))
    picks = ranking.rank(
        _signals(days),
        ranking.Preferences(formats=frozenset({"video"})),
        [],
        [],
        [article, video],
        NOW,
    )
    breaks = next(p for p in picks if p.intervention.key == "scheduled_breaks")
    assert breaks.resource == video


def test_a_time_limit_steers_away_from_long_resources() -> None:
    short = _resource("breaks", "movement", minutes=5)
    long = _resource("breaks", "movement", minutes=60)
    days = _days(energy=1, stress=5, stressors=("exams",))
    picks = ranking.rank(
        _signals(days), ranking.Preferences(max_minutes=10), [], [], [long, short], NOW
    )
    breaks = next(p for p in picks if p.intervention.key == "scheduled_breaks")
    assert breaks.resource == short


# ---- feedback changes what comes next ------------------------------------------------------


def _past(
    key: str,
    *,
    status: str = "dismissed",
    days_ago: int = 1,
    rating: str | None = None,
    reason: str | None = None,
    resource_id: uuid.UUID | None = None,
) -> ranking.Past:
    at = NOW - dt.timedelta(days=days_ago)
    return ranking.Past(
        key,
        resource_id,
        at,
        status,
        at + dt.timedelta(days=14),
        at if status in ("completed", "dismissed") else None,
        rating,
        reason,
        at if rating else None,
    )


def _response(key: str, kind: learning.Kind, **kw: object) -> learning.Response:
    return learning.Response(
        kind=kind,
        at=NOW - dt.timedelta(days=3),
        intervention_key=key,
        resource_format="article",
        resource_id=None,
        tags=BY_KEY[key].tags,
        **kw,  # type: ignore[arg-type]
    )


BURNED_OUT = _days(energy=1, stress=5, stressors=("exams", "deadlines"), mood=3)


def test_an_open_suggestion_is_not_repeated() -> None:
    open_one = _past("study_planning", status="pending")
    assert "study_planning" not in _keys(BURNED_OUT, past=[open_one])


def test_a_not_helpful_idea_stays_away_for_a_while_then_returns() -> None:
    rated = _past("study_planning", days_ago=3, rating="not_helpful")
    assert "study_planning" not in _keys(BURNED_OUT, past=[rated])
    old = _past("study_planning", days_ago=60, rating="not_helpful")
    # back after the wait, but only as far as one unhelpful rating lowers it
    assert "study_planning" in _keys(BURNED_OUT, past=[old], responses=[])


def test_not_now_comes_back_sooner_than_not_relevant() -> None:
    now_reason = _past("study_planning", days_ago=10, rating="not_helpful", reason="not_now")
    other = _past("study_planning", days_ago=10, rating="not_helpful", reason="not_relevant")
    assert "study_planning" in _keys(BURNED_OUT, past=[now_reason])
    assert "study_planning" not in _keys(BURNED_OUT, past=[other])


def test_a_completed_idea_rests_before_it_is_offered_again() -> None:
    done = _past("scheduled_breaks", status="completed", days_ago=5)
    assert "scheduled_breaks" not in _keys(BURNED_OUT, past=[done])
    long_ago = _past("scheduled_breaks", status="completed", days_ago=40)
    assert "scheduled_breaks" in _keys(BURNED_OUT, past=[long_ago])


def test_no_feedback_means_no_opinion() -> None:
    aff = learning.Affinity([], NOW)
    assert aff.idea("study_planning") == 1.0
    assert aff.of_resource(uuid.uuid4(), "article", ("planning",)) == 1.0


def test_helpful_raises_and_not_helpful_lowers_an_idea() -> None:
    up = learning.Affinity([_response("study_planning", "helpful")] * 3, NOW)
    down = learning.Affinity([_response("study_planning", "not_helpful")] * 3, NOW)
    assert up.idea("study_planning") > 1.4
    assert down.idea("study_planning") < 0.5
    assert learning.MULTIPLIER_MIN <= down.idea("study_planning")
    assert up.idea("study_planning") <= learning.MULTIPLIER_MAX


def test_helpful_feedback_moves_an_idea_up_the_list() -> None:
    def order(responses: list[learning.Response]) -> list[str]:
        return _keys(BURNED_OUT, responses=responses)

    baseline = order([])
    liked = order([_response("scheduled_breaks", "helpful")] * 3)
    assert liked.index("scheduled_breaks") <= baseline.index("scheduled_breaks")
    disliked = order([_response("study_planning", "not_helpful")] * 3)
    assert "study_planning" not in disliked or disliked.index("study_planning") >= baseline.index(
        "study_planning"
    )


def test_wrong_format_blames_the_format_not_the_idea() -> None:
    aff = learning.Affinity(
        [_response("study_planning", "not_helpful", reason="wrong_format")] * 3, NOW
    )
    assert aff.idea("study_planning") == 1.0
    assert aff.of_resource(uuid.uuid4(), "article", ()) < 1.0
    assert aff.of_resource(uuid.uuid4(), "video", ()) == 1.0


@pytest.mark.parametrize("reason", ["already_doing_this", "not_now"])
def test_some_reasons_count_against_nothing(reason: str) -> None:
    aff = learning.Affinity([_response("study_planning", "not_helpful", reason=reason)] * 3, NOW)
    assert aff.idea("study_planning") == 1.0
    assert aff.of_resource(uuid.uuid4(), "article", ("planning",)) == 1.0


def test_old_feedback_counts_for_less() -> None:
    recent = _response("study_planning", "not_helpful")
    stale = dataclasses.replace(recent, at=NOW - dt.timedelta(days=240))
    assert learning.Affinity([stale], NOW).idea("study_planning") > learning.Affinity(
        [recent], NOW
    ).idea("study_planning")


def test_finishing_counts_for_less_than_saying_helpful() -> None:
    done = learning.Affinity([_response("study_planning", "completed")], NOW)
    said = learning.Affinity([_response("study_planning", "helpful")], NOW)
    assert 1.0 < done.idea("study_planning") < said.idea("study_planning")


# ---- the catalog stays non-medical ---------------------------------------------------------

FORBIDDEN = (
    "depress",
    "disorder",
    "diagnos",
    "medicat",
    "prescri",
    "dose",
    "dosage",
    "therapy for",
    "treat",
    "cure",
    "symptom",
    "supplement",
    "you have ",
    "psychiatr",
    "illness",
    "anxiety attack",
)


def test_the_catalog_never_strays_into_medical_territory() -> None:
    for iv in CATALOG:
        text = f"{iv.title} {iv.why}".lower()
        assert not [w for w in FORBIDDEN if w in text], iv.key
        assert iv.why.endswith("."), iv.key


def test_every_area_has_at_least_one_way_forward() -> None:
    for area in MUTABLE_AREAS:
        if area == COUNSELLING:
            continue
        assert any(iv.area == area for iv in CATALOG), area


def test_generated_rationales_stay_non_medical_for_the_worst_case() -> None:
    days = _days(
        energy=1,
        stress=5,
        mood=1,
        sleep_minutes=200,
        sleep_quality=1,
        stressors=("exams", "career", "sleep", "relationships"),
        emotions=("lonely", "anxious"),
    )
    sig = _signals(days, credits=24, year_of_study=4, assessment_band="lower")
    sig = dataclasses.replace(
        sig,
        indicators={
            "burnout_risk": "elevated",
            "career_anxiety": "elevated",
            "social_isolation": "elevated",
            "sleep_lifestyle_risk": "elevated",
            "stress_level": "elevated",
        },
    )
    picks = ranking.rank(sig, ranking.Preferences(), [], [], LIBRARY, NOW)
    assert picks
    for p in picks:
        low = p.rationale.lower()
        assert not [w for w in FORBIDDEN if w in low], p.rationale


# ---- the numbers behind the needs ----------------------------------------------------------


def test_ramp_clamps_and_flips() -> None:
    assert signals.ramp(5.0, 2.5, 4.5) == 1.0
    assert signals.ramp(1.0, 2.5, 4.5) == 0.0
    assert signals.ramp(6.25, 7.0, 5.5) == pytest.approx(0.5)
    assert signals.ramp(None, 0, 1) is None


def test_missing_data_is_left_out_not_guessed() -> None:
    sig = _signals(_days(mood=3))  # no sleep, stress or energy answers at all
    result = needs.assess(sig)
    assert result["sleep_disruption"].score == 0.0
    assert result["academic_burnout"].score == 0.0


def test_bedtime_spread_treats_midnight_as_close_to_eleven_thirty() -> None:
    days = [
        signals.Day(day=TODAY - dt.timedelta(days=i), bedtime_hour=23.5 if i % 2 else 0.5)
        for i in range(8)
    ]
    sd = _signals(days).bedtime_sd
    assert sd is not None
    assert sd < 1.0

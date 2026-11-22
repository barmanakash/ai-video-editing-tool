"""Phase 4 tests (Qwen editing planner + validation). No FFmpeg or Ollama needed.

Run:  python -m pytest -q tests/test_phase4.py
"""
import json

import pytest

from app.agents.editing_agent import (
    PlannerContext,
    build_user_prompt,
    generate_plan,
    heuristic_plan,
    parse_json_object,
    repair_plan,
)
from app.config import settings
from app.engine.plan_schema import PlanValidationError, effective_duration, validate_plan
from app.services.ollama_service import OllamaError

SOURCES = {
    "aaaaaaaaaaaa": {"duration_seconds": 120.0, "has_audio": True, "path": "x/a.mp4", "name": "gameplay_01.mp4"},
    "bbbbbbbbbbbb": {"duration_seconds": 90.0, "has_audio": False, "path": "x/b.mp4", "name": "gameplay_02.mp4"},
}


def _analysis(vid, peaks):
    return {"video_id": vid, "estimated_highlights": [
        {"id": f"h{i}", "kind": "estimated_highlight", "start": p - 4, "end": p + 5, "peak_time": p,
         "score": s, "reasons": ["motion", "audio"], "confidence": "estimate"}
        for i, (p, s) in enumerate(peaks, 1)
    ]}


def _ctx(**kw):
    base = dict(
        instructions="Find the best fights, add smooth transitions and slow motion for big moments",
        sources=SOURCES,
        analyses={
            "aaaaaaaaaaaa": _analysis("aaaaaaaaaaaa", [(30.0, 0.9), (70.0, 0.6), (100.0, 0.5)]),
            "bbbbbbbbbbbb": _analysis("bbbbbbbbbbbb", [(20.0, 0.8), (60.0, 0.4)]),
        },
        profile=None,
        output={"format": "youtube", "quality": "test", "fit": "crop"},
        target_duration=30.0,
        audio={"use_uploaded_music": False, "music_path": None, "music_volume": 0.7},
    )
    base.update(kw)
    return PlannerContext(**base)


GOOD_REPLY = json.dumps({
    "style": "fast_paced_action",
    "clips": [
        {"source": "v1", "start": 26.0, "end": 34.0, "speed": 1.0, "effect": "none"},
        {"source": "v2", "start": 16.0, "end": 22.0, "speed": 0.5, "effect": "slow_motion"},
        {"source": "v1", "start": 66.0, "end": 74.0, "speed": 1.0, "effect": "zoom_in"},
    ],
    "transitions": ["cut", "crossfade"],
    "color": {"brightness": 0.0, "contrast": 1.1, "saturation": 1.1},
})


# ------------------------------------------------------------ parsing / prompt
def test_parse_json_variants():
    assert parse_json_object('{"a": 1}') == {"a": 1}
    assert parse_json_object('```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_json_object('Sure! Here it is: {"a": 1} Hope that helps') == {"a": 1}
    for bad in ("", "no json", "[1, 2]", '{"a": '):
        with pytest.raises(ValueError):
            parse_json_object(bad)


def test_prompt_uses_short_aliases_and_stays_small():
    ctx = _ctx()
    prompt = build_user_prompt(ctx)
    data = json.loads(prompt)
    assert [v["id"] for v in data["videos"]] == ["v1", "v2"]
    assert "aaaaaaaaaaaa" not in prompt and "x/a.mp4" not in prompt  # no real ids or paths
    assert len(prompt) < 3500
    assert "rejected" in build_user_prompt(ctx, feedback="bad times")


# ------------------------------------------------------------------- repair
def test_repair_fixes_common_model_mistakes():
    ctx = _ctx()
    raw = {
        "style": "x",
        "clips": [
            {"source": "v1", "start": 40.0, "end": 30.0, "speed": 1.0, "effect": "slow_motion"},   # swapped + wrong speed
            {"source": "V2", "start": 10, "end": 9999, "speed": 9, "effect": "explode"},           # clamp + bad effect
            {"source": "nope", "start": 1, "end": 5},                                              # unknown source
            {"source": "v1", "start": 30.0, "end": 40.0},                                          # duplicate of first
            "garbage",
        ],
        "transitions": ["fade", "wipe", "cut", "cut", "cut"],
    }
    part, notes = repair_plan(raw, ctx)
    plan = validate_plan({**part, "clips": part["clips"]}, SOURCES)
    assert [c["source"] for c in plan["clips"]] == ["aaaaaaaaaaaa", "bbbbbbbbbbbb"]
    first = plan["clips"][0]
    assert (first["start"], first["end"]) == (30.0, 40.0) and first["speed"] == 0.5
    second = plan["clips"][1]
    assert second["end"] <= 90.0 and second["speed"] == 4.0   # speed 9 clamped to the maximum
    assert second["effect"] == "speed_up"                      # unknown effect dropped, then inferred from speed
    assert second["end"] - second["start"] <= settings.max_clip_seconds
    assert plan["transitions"] == ["crossfade"]           # exactly one join
    assert any("unknown source" in n for n in notes)


def test_repair_drops_clips_to_stay_near_target():
    ctx = _ctx(target_duration=10.0)
    raw = {"clips": [{"source": "v1", "start": i * 10.0, "end": i * 10.0 + 8.0} for i in range(6)], "transitions": []}
    part, _ = repair_plan(raw, ctx)
    assert sum(effective_duration(c) for c in part["clips"]) <= 10.0 * 1.3 + 8.0
    assert len(part["clips"]) < 6


# -------------------------------------------------------------- generate_plan
def test_good_reply_is_used_as_is():
    plan, meta = generate_plan(_ctx(), llm=lambda s, u: GOOD_REPLY)
    assert meta["mode"] == "llm" and meta["attempts"] == 1
    assert len(plan["clips"]) == 3 and plan["transitions"] == ["cut", "crossfade"]
    assert plan["clips"][1]["effect"] == "slow_motion"
    assert plan["color"]["contrast"] == 1.1


def test_model_cannot_control_output_or_paths(tmp_path):
    music = tmp_path / "song.mp3"
    music.write_bytes(b"x")
    evil = json.loads(GOOD_REPLY)
    evil["output"] = {"format": "instagram", "quality": "full"}
    evil["audio"] = {"use_uploaded_music": True, "music_path": "C:\\Windows\\system32\\evil.mp3"}
    evil["clips"][0]["source"] = "v1; rm -rf /"
    ctx = _ctx(audio={"use_uploaded_music": True, "music_path": str(music), "music_volume": 0.5})
    plan, meta = generate_plan(ctx, llm=lambda s, u: json.dumps(evil))
    assert plan["output"]["format"] == "youtube" and plan["output"]["quality"] == "test"
    assert plan["audio"]["music_path"] == str(music.resolve())
    assert "evil" not in json.dumps(plan) and "rm -rf" not in json.dumps(plan)
    assert meta["mode"] == "llm_repaired"


def test_retry_after_invalid_json_then_success():
    replies = iter(["I think you should cut the fights.", GOOD_REPLY])
    seen = []

    def llm(system, user):
        seen.append(user)
        return next(replies)

    plan, meta = generate_plan(_ctx(), llm=llm)
    assert meta["attempts"] == 2 and meta["mode"] == "llm"
    assert "rejected" in seen[1] and "not valid JSON" in seen[1]


def test_ollama_down_uses_fallback_and_says_so():
    def llm(system, user):
        raise OllamaError("connection refused")

    plan, meta = generate_plan(_ctx(), llm=llm)
    assert meta["mode"] == "fallback"
    assert any("Ollama unavailable" in w for w in meta["warnings"])
    validate_plan(plan, SOURCES)


def test_two_bad_replies_use_fallback():
    plan, meta = generate_plan(_ctx(), llm=lambda s, u: '{"clips": []}')
    assert meta["mode"] == "fallback" and meta["attempts"] == 2
    assert plan["clips"]


def test_use_llm_false_never_calls_model():
    def llm(system, user):
        raise AssertionError("must not be called")

    plan, meta = generate_plan(_ctx(), use_llm=False, llm=llm)
    assert meta["mode"] == "fallback" and meta["attempts"] == 0


# ----------------------------------------------------------------- fallback
def test_fallback_plan_is_valid_and_follows_instructions():
    ctx = _ctx()
    part, notes = heuristic_plan(ctx)
    plan = validate_plan(
        {"style": part["style"], "clips": part["clips"], "transitions": part["transitions"]}, SOURCES)
    total = sum(effective_duration(c) for c in plan["clips"])
    assert 20 <= total <= 38
    assert any(c["effect"] == "speed_ramp" and c["speed"] < 1 for c in plan["clips"])   # "slow motion" requested -> eased ramp
    assert set(plan["transitions"]) == {"crossfade"}                                      # "smooth" requested
    # builds up to the strongest moment: the best highlight (video a, ~30 s) is the speed ramp and comes last
    assert plan["clips"][-1]["effect"] == "speed_ramp"
    assert 26 <= plan["clips"][-1]["start"] <= 34
    assert plan["clips"][-1]["peak"] == pytest.approx(30.0, abs=0.01)
    from app.agents.editing_agent import assemble
    assembled = validate_plan(assemble(ctx, part), SOURCES)             # defaults for a pro look
    assert assembled["color"]["preset"] == "cinematic" and assembled["fx"]["punch"] == "cuts"


def test_fallback_without_any_highlights_samples_videos():
    ctx = _ctx(analyses={})
    part, notes = heuristic_plan(ctx)
    assert any("no highlight analysis" in n for n in notes)
    plan = validate_plan({"clips": part["clips"], "transitions": part["transitions"]}, SOURCES)
    assert {c["source"] for c in plan["clips"]} == set(SOURCES)


def test_fallback_uses_reference_style_hints():
    profile = {"planner_hints": {"clip_length_seconds": {"min": 0.5, "target": 1.0, "max": 2.0},
                                 "transition_mix": {"cut": 0.2, "fade": 0.0, "flash": 0.8},
                                 "use_slow_motion": False, "use_zoom_punch_ins": True}}
    ctx = _ctx(profile=profile, instructions="make a montage")
    part, _ = heuristic_plan(ctx)
    plan = validate_plan({"clips": part["clips"], "transitions": part["transitions"]}, SOURCES)
    assert all(effective_duration(c) <= 3.01 for c in plan["clips"])     # short clips (target 1.0 s x 1.5, min 2.0)
    assert set(plan["transitions"]) == {"fadewhite"}
    assert any(c["effect"] == "zoom_in" for c in plan["clips"])
    assert not any(c["effect"] == "slow_motion" for c in plan["clips"])


# --------------------------------------------------------- schema safety net
def test_schema_rejects_unsafe_or_wrong_plans():
    ok = {"clips": [{"source": "aaaaaaaaaaaa", "start": 1, "end": 5}]}
    validate_plan(ok, SOURCES)
    bad_plans = [
        {"clips": []},
        {"clips": [{"source": "../../etc/passwd", "start": 1, "end": 5}]},
        {"clips": [{"source": "aaaaaaaaaaaa", "start": 1, "end": 5, "effect": "$(calc)"}]},
        {"clips": [{"source": "aaaaaaaaaaaa", "start": 1, "end": 5, "speed": 99}]},
        {"clips": [{"source": "aaaaaaaaaaaa", "start": 1, "end": 500}]},
        {"clips": [{"source": "aaaaaaaaaaaa", "start": 1, "end": 5}], "audio": {"use_uploaded_music": True, "music_path": "nope.mp3"}},
        {"clips": [{"source": "aaaaaaaaaaaa", "start": 1, "end": 5}], "output": {"format": "tiktok"}},
    ]
    for p in bad_plans:
        with pytest.raises(PlanValidationError):
            validate_plan(p, SOURCES)
    normalised = validate_plan({**ok, "extra": "rm -rf", "clips": [{**ok["clips"][0], "ffmpeg_args": "-f evil"}]}, SOURCES)
    assert "extra" not in normalised and "ffmpeg_args" not in normalised["clips"][0]
    assert normalised["audio"]["sync_cuts_to_music"] is True


# ----------------------------------------------------------------- API flow
@pytest.fixture()
def client(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    pytest.importorskip("scenedetect")
    from fastapi.testclient import TestClient

    monkeypatch.setattr(settings, "data_dir", tmp_path / "data")
    monkeypatch.setattr(settings, "outputs_dir", tmp_path / "outputs")
    settings.ensure_dirs()
    from app.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture()
def seeded(tmp_path):
    """Two registered gameplay videos (dummy files) with saved analyses. No FFmpeg needed."""
    from app.services import analysis_service as an
    from app.services import file_service as fs

    ids = {}
    for vid, name, dur, audio in (("aaaaaaaaaaaa", "gameplay_01.mp4", 120.0, True), ("bbbbbbbbbbbb", "gameplay_02.mp4", 90.0, False)):
        f = tmp_path / name
        f.write_bytes(b"not a real video")
        fs.save_record({
            "id": vid, "role": "gameplay", "original_name": name, "path": str(f), "source": "local",
            "created_at": fs.utc_now(), "thumbnails": [], "scenes": None,
            "metadata": {"duration_seconds": dur, "video": {"width": 1280, "height": 720, "fps": 30.0},
                         "audio": {"codec": "aac"} if audio else None},
        })
        an.save_gameplay({**_analysis(vid, [(30.0, 0.9), (70.0, 0.6)]), "source": {"original_name": name}, "created_at": fs.utc_now()})
        ids[name] = vid
    return ids


def test_plan_api_flow_with_mocked_qwen(client, seeded, monkeypatch):
    monkeypatch.setattr("app.agents.editing_agent.chat_json", lambda s, u: GOOD_REPLY)
    body = {"instructions": "Best fights with slow motion", "gameplay_ids": ["aaaaaaaaaaaa", "bbbbbbbbbbbb"],
            "target_duration": 25, "format": "instagram", "quality": "test"}
    r = client.post("/plans/generate", json=body)
    assert r.status_code == 200, r.text
    rec = r.json()
    assert rec["status"] == "draft" and rec["planner"]["mode"] == "llm"
    assert rec["plan"]["output"]["format"] == "instagram"
    assert [c["source"] for c in rec["plan"]["clips"]] == ["aaaaaaaaaaaa", "bbbbbbbbbbbb", "aaaaaaaaaaaa"]
    pid = rec["id"]

    assert client.get("/plans").json()["count"] == 1
    assert client.get(f"/plans/{pid}").json()["id"] == pid

    # The user edits the plan: make the first clip shorter, drop the last clip.
    plan = rec["plan"]
    plan["clips"] = plan["clips"][:2]
    plan["transitions"] = ["crossfade"]
    plan["clips"][0]["end"] = plan["clips"][0]["start"] + 4
    r = client.put(f"/plans/{pid}", json=plan)
    assert r.status_code == 200, r.text
    assert len(r.json()["plan"]["clips"]) == 2 and r.json()["planner"]["edited_by_user"] is True

    # An invalid edit is rejected with every problem listed
    plan["clips"][0]["source"] = "ffffffffffff"
    r = client.put(f"/plans/{pid}", json=plan)
    assert r.status_code == 422 and "not a known gameplay video" in r.json()["detail"]

    assert client.delete(f"/plans/{pid}").status_code == 200
    assert client.get(f"/plans/{pid}").status_code == 404


def test_plan_api_falls_back_when_ollama_is_down(client, seeded, monkeypatch):
    def down(system, user):
        raise OllamaError("connection refused")

    monkeypatch.setattr("app.agents.editing_agent.chat_json", down)
    r = client.post("/plans/generate", json={"instructions": "make a montage", "gameplay_ids": ["aaaaaaaaaaaa"]})
    assert r.status_code == 200, r.text
    assert r.json()["planner"]["mode"] == "fallback" and r.json()["plan"]["clips"]


def test_plan_api_input_errors(client, seeded):
    def post(**kw):
        body = {"instructions": "make a montage", "gameplay_ids": ["aaaaaaaaaaaa"], **kw}
        return client.post("/plans/generate", json=body)

    assert post(gameplay_ids=["cccccccccccc"]).status_code == 404       # not registered
    assert post(gameplay_ids=[]).status_code == 400                     # nothing selected
    assert post(format="tiktok", use_llm=False).status_code == 422      # bad format rejected by validator
    assert post(music_path="C:\\nope\\x.mp3", use_llm=False).status_code == 422
    assert post(target_duration=1).status_code == 422                   # request model limit
    assert client.get("/plans/zzzz").status_code == 404

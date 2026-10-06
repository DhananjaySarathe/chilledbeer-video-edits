import json

import pytest

from shorts.gfx.library import build_page, check_params, load_library
from shorts.gfx.scenes import caption_chunks, snap_to_cuts, snap_to_frames, split_by_mode, validate_visuals
from shorts.gfx.timeline import source_ranges, source_to_output, word_timeline
from shorts.render.graph import filter_graph
from shorts.schemas import AudioSpec, CaptionPage, CaptionWord, EditFile, OutputSpec, Scene, Segment, Visuals
from tests.factories import make_captions


def edit_two_segments():
    pages = [CaptionPage(start=0.0, end=0.5, words=[CaptionWord(text="HI", start=0.0, end=0.4)])]
    return EditFile(source="/abs/in.mp4", source_frames=600, output=OutputSpec(fps=30),
                    segments=[Segment(in_frame=30, out_frame=90, first_word=0, last_word=1),
                              Segment(in_frame=150, out_frame=240, first_word=2, last_word=3)],
                    captions=make_captions(pages), audio=AudioSpec(source_integrated=-20.0), duration=5.0)


def test_library_loads_and_skips_unfinished_templates(tmp_path):
    lib = load_library()
    assert {"title_behind", "stat_chart", "chat_thread", "captions_box"} <= set(lib)
    assert lib["captions_box"].meta.internal
    (tmp_path / "half_done").mkdir()
    (tmp_path / "half_done" / "meta.json").write_text(json.dumps({"id": "half_done"}))
    skipped = {}
    assert load_library(tmp_path, skipped) == {} and "half_done" in skipped


def test_check_params():
    meta = load_library()["stat_chart"].meta
    assert check_params(meta, {"to": 12.5}) == []
    assert any("required" in p for p in check_params(meta, {}))
    assert any("should be number" in p for p in check_params(meta, {"to": "lots"}))
    assert any("unknown params" in p for p in check_params(meta, {"to": 1, "colour": "red"}))


def test_build_page_injects_params_theme_and_runtime(tmp_path):
    tpl = load_library()["stat_chart"]
    html = build_page(tpl, {"to": 3.0}, 2.0, tmp_path / "p.html", theme={"accent": "#00AAFF"}).read_text()
    assert '"to": 3.0' in html and '"duration": 2000' in html and "--accent:#00AAFF;" in html
    assert "runtime.js" in html and "theme.css" in html and 'class="kind-fullscreen"' in html


def test_validate_visuals_catches_overlaps_and_bad_params():
    lib = load_library()
    vis = Visuals(scenes=[Scene(id="a", template="stat_chart", start=0, end=2.5, params={"to": 3}),
                          Scene(id="b", template="chat_thread", start=2.0, end=4.5,
                                params={"messages": [{"from": "me", "text": "hi"}]}),
                          Scene(id="c", template="nope", start=4.0, end=5.0)])
    problems = " ".join(validate_visuals(vis, lib, 10.0))
    assert "both full-screen" in problems and "unknown template" in problems
    assert validate_visuals(Visuals(scenes=[vis.scenes[0]]), lib, 10.0) == []


def test_source_ranges_follow_the_cuts():
    e = edit_two_segments()                      # out 0-2 s = src frames 30-90, out 2-5 s = src 150-240
    assert source_ranges(e, 1.0, 3.0) == [(60, 30), (150, 30)]
    assert source_ranges(e, 0.0, 1.0) == [(30, 30)]


def test_caption_chunks_split_on_page_boundaries_with_relative_times():
    pages = [{"start": float(k), "end": k + 0.9, "dark": False, "words": [{"text": "w", "start": float(k), "end": k + 0.9}]}
             for k in range(20)]
    chunks = caption_chunks(pages, limit=8.0)
    assert len(chunks) == 3 and chunks[1][0] == 8.0
    assert chunks[1][2][0]["start"] == 0.0 and chunks[1][2][0]["words"][0]["start"] == 0.0


def test_graph_overlays_scenes_and_mixes_sound():
    e = edit_two_segments()
    overlays = [{"mov": "/abs/a.mov", "start": 1.25}, {"mov": "/abs/b.mov", "start": 3.0}]
    sfx = [{"at": 1.25, "name": "whoosh", "gain_db": -16}, {"at": 3.0, "name": "whoosh", "gain_db": -18},
           {"at": 3.1, "name": "pop", "gain_db": -12}]
    g = filter_graph(e, "final", None, overlays, sfx, subtitles=False)
    assert "[1:v]setpts=PTS-STARTPTS+1.250000/TB,format=yuva420p,tpad=stop=1:stop_mode=add:color=black@0.0[g0]" in g
    assert "[vc][g0]overlay=eof_action=pass:format=auto[o0]" in g and "[o1]null[vo]" in g
    assert "[3:a]asplit=2[x0_0][x0_1]" in g and "adelay=1250|1250,volume=-16dB" in g and "[4:a]aresample" in g
    assert "amix=inputs=4:normalize=0:duration=first" in g and "subtitles=" not in g
    with pytest.raises(AssertionError):
        assert "scale=540:960" in g
    assert "scale=540:960:flags=bilinear,format=yuva420p,tpad" in filter_graph(e, "preview", None, overlays, None, False)


def test_caption_pages_split_where_a_scene_hides_or_darkens_them():
    def w(text, a, b):
        return {"text": text, "start": a, "end": b}
    pages = [{"start": 5.9, "end": 6.6, "words": [w("a", 5.9, 6.0), w("startup", 6.0, 6.3), w("which", 6.36, 6.5)]},
             {"start": 7.5, "end": 8.4, "words": [w("it", 7.6, 7.7), w("can", 7.7, 7.9), w("edit", 8.0, 8.3)]}]
    spans = [(3.2, 6.36, "dark"), (6.36, 7.96, "hide"), (7.96, 9.8, "dark")]

    def mode_at(t):
        return next((m for a, b, m in spans if a <= t < b), "show")
    out = split_by_mode(pages, mode_at, [3.2, 6.36, 7.96, 9.8])
    assert [[x["text"] for x in p["words"]] for p in out] == [["a", "startup"], ["edit"]]
    assert out[0]["end"] == 6.36 and out[0]["dark"]          # never lingers over the logo scene
    assert out[1]["start"] == 8.0 and out[1]["end"] == 8.4    # appears with its first word, after the logo


def test_word_timeline_reads_like_the_captions_and_source_times_map_to_the_edit():
    from shorts.schemas import Analysis
    e = edit_two_segments()                      # src 1-3 s -> out 0-2 s, src 5-8 s -> out 2-5 s
    words = [{"text": t, "start": a, "end": b} for t, a, b in
             [("So", 1.1, 1.3), ("dyn", 1.4, 1.7), ("be,", 5.2, 5.5), ("ok.", 5.6, 5.9)]]
    fake = Analysis.model_construct(words=[type("W", (), w)() for w in words])
    tl = word_timeline(e, fake, {1: "din", 2: "", 3: "theek"})
    assert [w["text"] for w in tl] == ["So", "din", "theek."]
    assert source_to_output(e, 1.5) == 0.5 and source_to_output(e, 4.0) == 2.0 and source_to_output(e, 6.0) == 3.0


def test_music_is_looped_levelled_ducked_under_speech_and_mixed():
    from shorts.render.graph import build_cmd, duck_expr, speech_spans
    e = edit_two_segments()                      # one caption word at 0.0-0.4 s
    assert speech_spans(e) == [(0.0, 0.4)]
    assert duck_expr([], 6) == "1" and duck_expr([(1, 2)], 0) == "1"
    expr = duck_expr([(1.0, 2.0), (5.0, 6.0)], 6.0)
    assert expr.startswith("1-0.4988*max(") and "clip(min((t-0.750)/0.25,(2.250-t)/0.25),0,1)" in expr
    music = {"file": "/abs/song.mp3", "gain_db": -9.5, "duck_db": 6.0, "start": 12.0, "fade_in": 0.4, "fade_out": 1.5}
    cmd = build_cmd("ffmpeg", e, "out.mp4", music=music)
    i = cmd.index("/abs/song.mp3")
    assert cmd[i - 5:i] == ["-stream_loop", "-1", "-ss", "12", "-i"]
    g = cmd[cmd.index("-filter_complex") + 1]
    assert "[1:a]aresample=48000" in g and "atrim=duration=5.000" in g and "volume=-9.50dB" in g
    assert "afade=t=out:st=3.500:d=1.5" in g and "[ac][mus]amix=inputs=2:normalize=0" in g and "[amx]loudnorm" in g


def test_scenes_snap_to_whole_frames_so_back_to_back_scenes_leave_no_gap():
    vis = Visuals(scenes=[Scene(id="a", template="stat_chart", start=31.72, end=33.59, params={"to": 1}),
                          Scene(id="b", template="stat_chart", start=33.59, end=37.63, params={"to": 1})])
    a, b = snap_to_frames(vis, 30).scenes
    assert (a.start * 30, a.end * 30, b.start * 30) == (952, 1008, 1008)
    assert round((a.end - a.start) * 30) == 56 and a.end == b.start


def test_scene_edges_move_onto_nearby_cuts_and_stay_together():
    vis = Visuals(scenes=[Scene(id="a", template="badge_pop", start=41.73, end=43.28, params={"text": "x"}),
                          Scene(id="b", template="section_card", start=43.28, end=45.84, params={"title": "x"})])
    a, b = snap_to_cuts(vis, [33.53, 43.23, 45.03]).scenes
    assert (a.start, a.end, b.start, b.end) == (41.73, 43.23, 43.23, 45.84)


def test_grade_and_voice_polish_are_in_the_graph_when_asked():
    e = edit_two_segments()
    plain = filter_graph(e, "final", None, None, None, subtitles=False)
    assert "eq=contrast" not in plain and "afftdn" not in plain
    e2 = e.model_copy(update={"output": e.output.model_copy(update={"grade": 0.5}),
                              "audio": e.audio.model_copy(update={"clean": True})})
    g = filter_graph(e2, "final", None, None, None, subtitles=False)
    assert "[vc]eq=contrast=1.040:saturation=1.080" in g and "[vg]null[vo]" in g
    assert g.count("setpts=PTS-STARTPTS,unsharp=5:5:0.23:5:5:0") == 2    # per segment now (scaled with the zoom: test_graph)
    assert "[ac]highpass=f=80,afftdn" in g and "[acl]loudnorm" in g
    assert "unsharp" not in filter_graph(e2, "preview", None, None, None, subtitles=False)


def test_zoom_cut_joins_get_no_audio_fade():
    from shorts.schemas import Segment
    e = edit_two_segments()
    joined = e.model_copy(update={"segments": [Segment(in_frame=30, out_frame=90, first_word=0, last_word=1),
                                               Segment(in_frame=90, out_frame=240, first_word=2, last_word=3)]})
    g = filter_graph(joined, "final", None, None, None, subtitles=False)
    a0 = next(p for p in g.split(";") if p.endswith("[a0]"))
    a1 = next(p for p in g.split(";") if p.endswith("[a1]"))
    assert "afade=t=in" in a0 and "afade=t=out" not in a0 and "afade=t=in" not in a1 and "afade=t=out" in a1

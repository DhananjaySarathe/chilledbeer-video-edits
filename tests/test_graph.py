import pytest

from shorts.render.graph import (audio_chain, build_cmd, build_measure_cmd, filter_graph, input_runs, inputs,
                                 parse_loudnorm, sharpen_amount, video_chain)
from shorts.schemas import AudioSpec, CaptionPage, CaptionWord, EditFile, OutputSpec, Segment
from tests.factories import make_captions

MEASURED = {"input_i": "-20.1", "input_tp": "-3.2", "input_lra": "4.0", "input_thresh": "-30.5",
            "target_offset": "0.1"}


def seg(a, b, **kw):
    return Segment(in_frame=a, out_frame=b, first_word=0, last_word=0, **kw)


def edit_of(segs):
    pages = [CaptionPage(start=0.0, end=0.5, words=[CaptionWord(text="HI", start=0.0, end=0.4)])]
    return EditFile(source="/abs/in.mp4", source_frames=2000, output=OutputSpec(fps=30), segments=segs,
                    captions=make_captions(pages), audio=AudioSpec(source_integrated=-20.0),
                    duration=sum(s.out_frame - s.in_frame for s in segs) / 30)


def tiny_edit():
    return edit_of([seg(0, 30), seg(60, 90, zoom=1.08, crop=[1000, 1778, 40, 22])])


def test_forward_segments_share_one_input():
    assert input_runs(tiny_edit()) == [[0, 1]]
    args = inputs(tiny_edit())
    assert args.count("-i") == 1 and args.count("-hwaccel") == 1
    assert args[args.index("-ss") + 1] == "0.000000" and args[args.index("-t") + 1] == "3.066667"


def test_a_segment_that_jumps_back_gets_its_own_input():
    e = edit_of([seg(60, 90), seg(0, 30), seg(40, 55)])
    assert input_runs(e) == [[0], [1, 2]]
    args = inputs(e)
    assert [args[i + 1] for i, a in enumerate(args) if a == "-ss"] == ["1.991666", "0.000000"]


def test_inputs_without_hardware_decoding_and_audio_only():
    assert "-hwaccel" not in inputs(tiny_edit(), hw=False)
    args = inputs(tiny_edit(), audio_only=True)
    assert args.count("-vn") == 1 and "-hwaccel" not in args


def test_video_chains_count_frames_from_the_run_start():
    e = tiny_edit()
    assert video_chain("[r0v1]", 1, e.segments[1], 0, preview=False) == (
        "[r0v1]trim=start_frame=60:end_frame=90,setpts=PTS-STARTPTS,crop=1000:1778:40:22,"
        "scale=1080:1920:flags=lanczos,setsar=1,format=yuv420p[v1]")
    assert video_chain("[0:v]", 0, seg(100, 130), 100, preview=True) == (
        "[0:v]trim=start_frame=0:end_frame=30,setpts=PTS-STARTPTS,scale=540:960:flags=bilinear,setsar=1,"
        "format=yuv420p[v0]")


def test_sharpening_follows_the_scale_and_the_zoom():
    e = tiny_edit()
    assert video_chain("[r0v1]", 1, e.segments[1], 0, preview=False, grade=0.5).endswith(
        "crop=1000:1778:40:22,scale=1080:1920:flags=lanczos,unsharp=5:5:0.26:5:5:0,setsar=1,format=yuv420p[v1]")
    assert "unsharp=5:5:0.23:" in video_chain("[0:v]", 0, seg(0, 30), 0, preview=False, grade=0.5)
    assert "unsharp" not in video_chain("[0:v]", 0, seg(0, 30), 0, preview=True, grade=0.5)
    assert sharpen_amount(0.5, 1.3) == pytest.approx(0.36) and sharpen_amount(1.0, 1.45) == 0.6


def test_audio_chain_trims_by_timestamp_from_the_seek_point():
    assert audio_chain("[0:a]", 1, seg(60, 90), 30, 0.0, 0.01) == (
        "[0:a]aresample=48000,atrim=start=2.000000:end=3.000000,asetpts=PTS-STARTPTS,"
        "afade=t=in:d=0.01,afade=t=out:st=0.990000:d=0.01[a1]")
    assert "atrim=start=0.008334:end=1.008334" in audio_chain("[1:a]", 0, seg(60, 90), 30, 1.991666, 0.01)


def test_filter_graph_splits_each_run_and_concats():
    g = filter_graph(tiny_edit(), "final", MEASURED)
    assert "[0:v]split=2[r0v0][r0v1]" in g and "[0:a]asplit=2[r0a0][r0a1]" in g
    assert "[v0][a0][v1][a1]concat=n=2:v=1:a=1[vc][ac]" in g
    assert "[vc]subtitles=filename=captions.ass:fontsdir=fonts[vo]" in g
    assert "loudnorm=I=-14:TP=-1:LRA=11:measured_I=-20.1" in g and "linear=true" in g
    assert "volume=6.0dB,alimiter=limit=0.891:level=false" in filter_graph(tiny_edit(), "preview")


def test_measure_command_is_audio_only():
    cmd = build_measure_cmd("ffmpeg", tiny_edit())
    graph = cmd[cmd.index("-filter_complex") + 1]
    assert "[v0]" not in graph and "[a0][a1]concat=n=2:v=0:a=1[ac]" in graph and "print_format=json" in graph


def test_commands_pick_the_encoder():
    e = tiny_edit()
    assert "h264_videotoolbox" in build_cmd("ffmpeg", e, "p.mp4", "preview")
    assert "libx264" in build_cmd("ffmpeg", e, "f.mp4", "max", MEASURED)


def test_parse_loudnorm():
    err = ('noise\n[Parsed_loudnorm_1 @ 0x1]\n{\n\t"input_i" : "-19.62",\n\t"input_tp" : "-2.40",\n'
           '\t"input_lra" : "5.10",\n\t"input_thresh" : "-29.90",\n\t"output_i" : "-14.02",\n'
           '\t"target_offset" : "0.02"\n}\n')
    assert parse_loudnorm(err) == {"input_i": "-19.62", "input_tp": "-2.40", "input_lra": "5.10",
                                   "input_thresh": "-29.90", "target_offset": "0.02"}


def test_speed_is_applied_to_the_finished_picture_and_mix():
    e = tiny_edit()
    e.output.speed = 1.1
    g = filter_graph(e, "final", MEASURED)
    assert "fonts[vs];[vs]setpts=PTS/1.1[vo]" in g
    assert "atempo=1.1[asp];[asp]loudnorm=" in g
    assert "atempo=1.1[asp];[asp]loudnorm=" in build_measure_cmd("ffmpeg", e)[-6]
    assert "atempo" not in filter_graph(tiny_edit(), "final", MEASURED)


def test_a_cold_open_segment_may_repeat_later_footage():
    from shorts.plan.validate import validate_edit
    e = edit_of([seg(60, 90), seg(0, 30), seg(40, 70)])
    assert any("overlaps" in p for p in validate_edit(e))
    e.cold_open = 1
    assert not any("overlaps" in p for p in validate_edit(e))


def test_music_can_enter_late_and_drop_out_for_a_beat():
    from shorts.render.graph import _music_chain, drop_expr
    parts = []
    music = {"gain_db": -3.0, "duck_db": 4.0, "fade_in": 0.4, "fade_out": 1.5, "enter": 2.5, "drops": [[1.0, 1.4]]}
    ten = edit_of([seg(0, 300)])                              # 10 s, so the entry is not clamped
    _music_chain(parts, "am", ten, music, 3)
    chain = parts[0]
    assert "adelay=2500|2500,atrim=duration=" in chain and "afade=t=in:st=2.500" in chain
    assert drop_expr([[1.0, 1.4]]) == "1-clip(min((t-1.000)/0.05,(1.400-t)/0.05),0,1)" and "volume='1-clip(" in chain
    parts = []
    _music_chain(parts, "am", ten, {**music, "enter": 0.0, "drops": []}, 3)
    assert "adelay" not in parts[0] and "afade=t=in:st=0.000" in parts[0]

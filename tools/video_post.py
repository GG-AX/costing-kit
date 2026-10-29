"""영상 다듬기 — 생성 비용 0, ffmpeg만. 결과는 board/media/video/에 쓰고 run 폴더 원본은 그대로 둔다. 작업 폴더에서 실행.

  python3 video_post.py turn <앞→뒤 run> <뒤→앞 run> <스타일> <키> [--duration S]  → <스타일>_<키>_loop.mp4 (턴 한 바퀴)
  python3 video_post.py loop <run> <스타일> <키> [--duration S]                     → <스타일>_<키>_loop.mp4 (같은 컷→같은 컷, 크롭만)
  python3 video_post.py motion <run> <스타일> <from> <to> [--face F|B]              → <스타일>_m_<F|B>_<from>_<to>.mp4 (켜는 방향만)
  python3 video_post.py strip <run> [--every 0.25]                                  → work/strip_<run>.jpg (중간 프레임 띠 — 검수용)
  python3 video_post.py --self-test

- 키 = base 또는 o+옵션 번호(정렬, 예 o13). motion의 to = from + 옵션 1개(끄기 모션은 만들지 않음 — 끌 때는 화면이 블러 전환).
- --duration: 한 스타일의 _loop.mp4 길이를 같게(lint가 0.1초 넘게 다르면 ERR). 고르게 늘이고 줄임.
- 결과가 입력보다 새것이면 건너뜀(--force로 다시. --duration을 주면 늘 다시 만듦).
- 덧대 올린 영상은 run.json crop_to 비율로 가운데를 잘라냄(run.py가 위아래를 같은 만큼 덧댐).
- turn: 두 편을 1배속으로 잇고, 거의 안 움직이는 장면이 이어지면 처음 0.5초 + 끝 1장만 남긴다
  (9월 영상 보드 턴 도구 원속 — 계단·곡선 배속은 사용자가 "튄다"로 거부). 2패스: 회색 축소본으로 고를 장면을 정하고 → ffmpeg가 원본에서 골라 1번 인코딩
  (전 프레임을 메모리에 올리지 않음).
- strip: 시작·끝만 보면 중간에 신발이 바뀌어도 모른다(10/19 run 010) — 0.25초 간격 띠를 직접 본다.
- 만든 파일은 원본 run.json의 "post"에 적는다(lint가 board/media ↔ 확정 run 대조에 씀).
"""
import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from fractions import Fraction
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import die, save_atomic, write_atomic  # noqa: E402

ROOT = Path.cwd().resolve()
STILL_KEEP_SEC = 0.5
STILL_DIFF = 0.6  # 이웃 장면 평균 차(0~255 회색)가 이보다 작으면 "서 있음"
GW, GH = 136, 204  # 분석용 회색 축소본 크기
NAME = re.compile(r"^[A-Za-z0-9-]+$")
KEY = re.compile(r"^(base|o[1-9]+)$")


def tool(name):
    exe = shutil.which(name)
    if not exe:
        die(f"{name} 없음 — 맥 `brew install ffmpeg`, 윈도우 `winget install Gyan.FFmpeg`")
    return exe


def opts(key):
    """키 → 옵션 번호 집합. 잘못된 키(정렬 안 됨·중복 포함)는 die."""
    if not KEY.match(key):
        die(f"키 {key!r}: base 또는 o+옵션 번호(예 o1, o13)")
    if key == "base":
        return set()
    d = key[1:]
    if list(d) != sorted(set(d)):
        die(f"키 {key!r}: 옵션 번호는 작은 것부터 한 번씩(예 o13, o31·o11 아님)")
    return set(d)


def check_motion(frm, to):
    a, b = opts(frm), opts(to)
    if not (a < b and len(b - a) == 1):
        die(f"motion {frm}→{to}: to는 from에 옵션 1개를 더한 키여야 함(켜는 방향만, 예 base→o1, o1→o13)")


def check_name(c):
    if not NAME.match(c):
        die(f"스타일 {c!r}: 영문·숫자·- 만")


def load_run(no):
    hits = sorted((ROOT / "runs").glob(f"{str(no).zfill(3)}_*/run.json"))
    if not hits:
        die(f"run {no} 없음")
    run = json.loads(hits[0].read_text(encoding="utf-8"))
    mp4 = [f for f in (run.get("outputs") or {}).values() if f.endswith(".mp4")]
    if run.get("status") != "completed" or not mp4:
        die(f"run {no}: 완료된 mp4 없음")
    return hits[0], run, hits[0].parent / mp4[0]


def crop_ratio(run):
    """run.json crop_to "w:h" → h/w, 없으면 None."""
    w, h = (float(x) for x in run.get("crop_to", "0:0").split(":"))
    return h / w if w and h else None


def crop_filter(run):
    r = crop_ratio(run)
    return f"crop=w=iw:h='min(ih,trunc(iw*{r:.6f}/2)*2)'" if r else "null"


def probe(src):
    """(가로, 세로, fps 문자열 예 '24/1')."""
    r = subprocess.run([tool("ffprobe"), "-v", "error", "-select_streams", "v:0", "-show_entries",
                        "stream=width,height,r_frame_rate", "-of", "json", str(src)], capture_output=True, text=True)
    s = (json.loads(r.stdout or "{}").get("streams") or [None])[0]
    if r.returncode or not s:
        die(f"{src}: ffprobe 실패")
    return s["width"], s["height"], s["r_frame_rate"]


def raw(src, vf, w, h, pix):
    """ffmpeg로 축소 프레임만 받아 (n, h, w[, 3]) 배열 — 원본 크기 프레임은 메모리에 올리지 않음."""
    import numpy as np
    r = subprocess.run([tool("ffmpeg"), "-v", "error", "-i", str(src), "-vf", f"{vf},scale={w}:{h}", "-f", "rawvideo",
                        "-pix_fmt", pix, "-"], capture_output=True)
    if r.returncode or not r.stdout:
        die(f"{src}: 프레임을 못 읽음 {r.stderr.decode('utf-8', 'replace')[:200]}")
    a = np.frombuffer(r.stdout, np.uint8)
    return a.reshape(-1, h, w) if pix == "gray" else a.reshape(-1, h, w, 3)


def note_post(path, run, out):
    run["post"] = sorted(set(run.get("post", [])) | {out.relative_to(ROOT).as_posix()})
    write_atomic(path, json.dumps(run, ensure_ascii=False, indent=1))


def fresh(outs, ins):
    return all(o.exists() for o in outs) and min(o.stat().st_mtime for o in outs) >= max(i.stat().st_mtime for i in ins)


def encode(srcs, graph, out, fps):
    """filter_complex의 [v]를 out으로 1회 인코딩. 임시 파일 → os.replace."""
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(".tmp_" + out.name)
    cmd = [tool("ffmpeg"), "-y", "-v", "error", *[x for s in srcs for x in ("-i", str(s))], "-filter_complex", graph,
           "-map", "[v]", "-r", fps, "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p", "-an", str(tmp)]
    if subprocess.run(cmd).returncode:
        tmp.unlink(missing_ok=True)
        die(f"ffmpeg 실패 → {out.name}")
    tmp.replace(out)


def keep_frames(diffs, fps):
    """diffs[i] = 장면 i와 i-1의 차. 정지 구간은 처음 0.5초 + 마지막 1장만, 끝 장면(확정 스틸)은 항상 남김."""
    keep, i, n = [], 0, len(diffs)
    keep_n = max(1, int(STILL_KEEP_SEC * fps))
    while i < n:
        if i == 0 or diffs[i] >= STILL_DIFF:
            keep.append(i)
            i += 1
            continue
        j = i
        while j < n and diffs[j] < STILL_DIFF:
            j += 1
        span = list(range(i, j))
        keep += span[:keep_n] + ([span[-1]] if len(span) > keep_n else [])
        i = j
    if keep[-1] != n - 1:
        keep.append(n - 1)
    return keep


def spans(keep):
    """[0,1,2,5,6] → [(0,2),(5,6)] — select 식을 짧게."""
    out = []
    for k in keep:
        if out and out[-1][1] == k - 1:
            out[-1][1] = k
        else:
            out.append([k, k])
    return out


def media(name):
    return ROOT / "board/media/video" / name


def turn(a_no, b_no, c, key, force=False, duration=None):
    check_name(c)
    opts(key)
    pa, ra, va = load_run(a_no)
    pb, rb, vb = load_run(b_no)
    out = media(f"{c}_{key}_loop.mp4")
    if not force and not duration and fresh([out], [va, vb]):
        print(f"건너뜀(최신): {out.relative_to(ROOT).as_posix()}")
        return out
    import numpy as np
    fps = probe(va)[2]
    f = float(Fraction(fps))
    # 1패스: 회색 축소본으로 남길 장면 고르기
    g = np.concatenate([raw(va, crop_filter(ra), GW, GH, "gray"), raw(vb, crop_filter(rb), GW, GH, "gray")[1:]]).astype(np.float32)
    diffs = [99.0] + np.abs(np.diff(g, axis=0)).mean(axis=(1, 2)).tolist()
    keep = keep_frames(diffs, f)
    k = duration * f / len(keep) if duration else 1.0
    sel = "+".join(f"between(n\\,{s}\\,{e})" for s, e in spans(keep))
    # 2패스: 원본에서 크롭 → 이어 붙여(이음매 한 장 겹침 제거) → 고른 장면만 → (길이 맞춤) 1회 인코딩
    graph = (f"[0:v]{crop_filter(ra)},setpts=PTS-STARTPTS[a];[1:v]{crop_filter(rb)},trim=start_frame=1,setpts=PTS-STARTPTS[b];"
             f"[a][b]concat=n=2:v=1:a=0[c];[c]select={sel},setpts=N*{k:.6f}/({f:.6f}*TB)[v]")
    encode([va, vb], graph, out, fps)
    note_post(pa, ra, out)
    note_post(pb, rb, out)
    print(f"{out.relative_to(ROOT).as_posix()} — {len(g)}장 → {len(keep)}장 ({len(keep) * k / f:.2f}초"
          + (f", --duration으로 ×{k:.3f}" if duration else ", 1배") + ")")
    return out


def single(no, out, force, duration=None):
    """크롭(+길이 맞춤)만 하는 1편 → out."""
    path, run, src = load_run(no)
    if not force and not duration and fresh([out], [src]):
        print(f"건너뜀(최신): {out.relative_to(ROOT).as_posix()}")
        return out
    fps = probe(src)[2]
    vf = crop_filter(run)
    if duration:
        n = len(raw(src, vf, 8, 8, "gray"))  # 프레임 수(작게 디코딩)
        vf += f",setpts=N*{duration * float(Fraction(fps)) / n:.6f}/({float(Fraction(fps)):.6f}*TB)"
    encode([src], f"[0:v]{vf}[v]", out, fps)
    note_post(path, run, out)
    print(f"{out.relative_to(ROOT).as_posix()} — 크롭{'·길이 ' + str(duration) + '초' if duration else ''} 1회 인코딩")
    return out


def loop(no, c, key, force=False, duration=None):
    check_name(c)
    opts(key)
    return single(no, media(f"{c}_{key}_loop.mp4"), force, duration)


def motion(no, c, frm, to, face="F", force=False):
    check_name(c)
    if face not in ("F", "B"):
        die("--face는 F 또는 B")
    check_motion(frm, to)
    return single(no, media(f"{c}_m_{face}_{frm}_{to}.mp4"), force)


def strip(no, every=0.25):
    """중간 프레임 띠 — every초 간격, 8칸씩 줄바꿈 → work/strip_<run>.jpg"""
    from PIL import Image
    _, run, src = load_run(no)
    w, h, fps = probe(src)
    r = crop_ratio(run)
    ch = min(h, int(w * r) // 2 * 2) if r else h
    tw, th = 240, round(ch * 240 / w / 2) * 2
    frames = raw(src, crop_filter(run), tw, th, "rgb24")
    step = max(1, round(every * float(Fraction(fps))))
    picks = list(range(0, len(frames), step))
    if picks[-1] != len(frames) - 1:
        picks.append(len(frames) - 1)
    cols = 8
    sheet = Image.new("RGB", (cols * tw, -(-len(picks) // cols) * th), "white")
    for n, i in enumerate(picks):
        sheet.paste(Image.fromarray(frames[i]), ((n % cols) * tw, (n // cols) * th))
    out = ROOT / "work" / f"strip_{str(no).zfill(3)}.jpg"
    save_atomic(sheet, out, quality=85)
    print(f"{out.relative_to(ROOT).as_posix()} — {len(picks)}칸({every}초 간격). 신발·다리·소품이 중간에 바뀌지 않는지 본다")
    return out


def self_test():
    still = [99.0] + [0.1] * 59 + [5.0] * 30 + [0.1] * 60  # 정지 2.5초 · 회전 1.25초 · 정지 2.5초 (24fps)
    k = keep_frames(still, 24)
    assert k[0] == 0 and k[-1] == len(still) - 1, "첫·끝 장면(확정 스틸)은 남아야"
    assert all(i in k for i in range(60, 90)), "움직이는 장면은 모두 남아야"
    assert len(k) == 1 + 12 + 1 + 30 + 12 + 1, len(k)
    assert spans([0, 1, 2, 5, 7, 8]) == [[0, 2], [5, 5], [7, 8]]
    for frm, to in (("base", "o1"), ("o1", "o13"), ("o3", "o13"), ("o12", "o123")):
        check_motion(frm, to)
    for frm, to in (("base", "o12"), ("o1", "o2"), ("o1", "o1"), ("o13", "o1"), ("o2", "o21"), ("base", "x1"), ("o1", "o11")):
        try:
            check_motion(frm, to)
            raise AssertionError(f"잘못된 motion {frm}→{to}을 받음")
        except SystemExit:
            pass
    msg = "프레임 선택 · motion 이름 검사 통과"
    if shutil.which("ffmpeg") and shutil.which("ffprobe"):
        global ROOT
        with tempfile.TemporaryDirectory() as t:
            ROOT = Path(t, "작업 폴더").resolve()
            for no, src in (("001", "testsrc"), ("002", "testsrc2")):
                d = ROOT / "runs" / f"{no}_S_k"
                d.mkdir(parents=True)
                subprocess.run([tool("ffmpeg"), "-v", "error", "-f", "lavfi", "-i", f"{src}=size=320x560:rate=24:duration=2",
                                "-pix_fmt", "yuv420p", str(d / "out.mp4")], check=True)
                (d / "run.json").write_text(json.dumps({"no": no, "status": "completed", "outputs": {"v": "out.mp4"},
                                                        "crop_to": "2:3"}), encoding="utf-8")
            dur = lambda p: float(subprocess.run([tool("ffprobe"), "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                                                  str(p)], capture_output=True, text=True).stdout)
            size = lambda p: probe(p)[:2]
            o = turn("001", "002", "S", "base")
            assert size(o) == (320, 480), size(o)
            assert abs(dur(turn("001", "002", "S", "o1", duration=3.0)) - 3.0) < 0.1
            assert abs(dur(loop("002", "S", "o13", duration=3.0)) - 3.0) < 0.1
            m = motion("001", "S", "base", "o1", "B")
            assert m.name == "S_m_B_base_o1.mp4" and size(m) == (320, 480)
            assert strip("001").exists()
            assert "board/media/video/S_m_B_base_o1.mp4" in json.loads((ROOT / "runs/001_S_k/run.json").read_text(encoding="utf-8"))["post"]
            before = m.stat().st_mtime
            motion("001", "S", "base", "o1", "B")  # 두 번째는 건너뜀
            assert m.stat().st_mtime == before
            assert not list((ROOT / "board/media/video").glob(".tmp_*"))
        msg += " · ffmpeg turn(2패스)/--duration/loop/motion/strip/건너뜀 통과"
    else:
        msg += " · ffmpeg 없음 — 인코딩 시험은 건너뜀"
    print("self-test " + msg)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("mode", nargs="?", choices=["turn", "loop", "motion", "strip"])
    ap.add_argument("args", nargs="*")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--duration", type=float, help="turn·loop 길이(초) — 한 스타일의 턴 영상 길이를 같게")
    ap.add_argument("--face", default="F", help="motion: F 또는 B")
    ap.add_argument("--every", type=float, default=0.25)
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()
    if a.self_test:
        return self_test()
    if a.mode == "turn" and len(a.args) == 4:
        return turn(*a.args, a.force, a.duration)
    if a.mode == "loop" and len(a.args) == 3:
        return loop(*a.args, a.force, a.duration)
    if a.mode == "motion" and len(a.args) == 4:
        return motion(*a.args, a.face, a.force)
    if a.mode == "strip" and len(a.args) == 1:
        return strip(a.args[0], a.every)
    ap.error("turn <앞→뒤 run> <뒤→앞 run> <스타일> <키> · loop <run> <스타일> <키> · "
             "motion <run> <스타일> <from> <to> [--face F|B] · strip <run>")


if __name__ == "__main__":
    main()

"""앞|뒤 한 장(4:3, 왼쪽 앞·오른쪽 뒤) 결과를 반으로 나눠 board/media/img/<스타일>_<키>_F.jpg · _B.jpg로. 확정 컷에만 쓴다.

  python3 split_fb.py <run 번호> [--view FB]   run의 결과 중 보기 이름이 FB인 파일(없으면 첫 이미지)
  python3 split_fb.py --self-test

shot_base·shot_option 프롬프트는 "같은 사람 둘, 같은 크기, 한 바닥선, 왼쪽 앞·오른쪽 뒤"라 반으로 자르면 각각 2:3이 된다.
원본 해상도 JPEG(q95) — 화면용 축소는 single_file이 한다.
만든 파일은 run.json "post"에 적는다(lint가 board/media ↔ 확정 run 대조에 씀). 원본은 run 폴더에 그대로.
"""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import save_atomic, write_atomic  # noqa: E402

ROOT = Path.cwd().resolve()


def split(no, view="FB"):
    from PIL import Image
    hits = sorted((ROOT / "runs").glob(f"{str(no).zfill(3)}_*/run.json"))
    if not hits:
        raise SystemExit(f"split_fb: run {no} 없음")
    path = hits[0]
    run = json.loads(path.read_text(encoding="utf-8"))
    outs = run.get("outputs") or {}
    src = outs.get(view) or next((f for f in outs.values() if f.endswith((".png", ".jpg", ".webp"))), None)
    if not src:
        raise SystemExit(f"split_fb: run {no}에 이미지 결과 없음")
    im = Image.open(path.parent / src).convert("RGB")
    if abs(im.width / im.height - 4 / 3) > 0.03:
        print(f"split_fb: 경고 — {src}가 4:3이 아님({im.width}x{im.height})", file=sys.stderr)
    half = im.width // 2
    made = []
    for side, box in (("F", (0, 0, half, im.height)), ("B", (half, 0, half * 2, im.height))):
        out = ROOT / "board/media/img" / f"{run['style']}_{run['key']}_{side}.jpg"
        save_atomic(im.crop(box), out, quality=95)
        made.append(out.relative_to(ROOT).as_posix())
    run["post"] = sorted(set(run.get("post", [])) | set(made))
    write_atomic(path, json.dumps(run, ensure_ascii=False, indent=1))
    print(" · ".join(made))
    return made


def self_test():
    global ROOT
    from PIL import Image
    with tempfile.TemporaryDirectory() as t:
        ROOT = Path(t, "작업").resolve()
        d = ROOT / "runs/001_S_base"
        d.mkdir(parents=True)
        im = Image.new("RGB", (400, 300), "red")
        im.paste((0, 0, 255), (200, 0, 400, 300))
        im.save(d / "out.png")
        (d / "run.json").write_text(json.dumps({"no": "001", "style": "S", "key": "base", "outputs": {"FB": "out.png"}}), encoding="utf-8")
        made = split("1")
        f, b = (Image.open(ROOT / m) for m in made)
        assert f.size == b.size == (200, 300) and f.getpixel((5, 5))[0] > 240 and b.getpixel((5, 5))[2] > 240
        assert json.loads((d / "run.json").read_text(encoding="utf-8"))["post"] == ["board/media/img/S_base_B.jpg", "board/media/img/S_base_F.jpg"]
    print("self-test 통과 — 4:3 → 2:3 두 장(board/media/img/*.jpg), run.json post 기록")


if __name__ == "__main__":
    a = sys.argv[1:]
    if "--self-test" in a:
        self_test()
    elif a and a[0] not in ("-h", "--help"):
        split(a[0], a[a.index("--view") + 1] if "--view" in a else "FB")
    else:
        raise SystemExit(__doc__)

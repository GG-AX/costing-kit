"""보드 → 공유용 단일 HTML 두 판. 키트 engine/ + 작업 폴더 board/data.js + board/media/ 를 한 파일에.

  python3 single_file.py            → board/v<N>_motion.html · board/v<N>_still.html (N = 다음 번호)
  python3 single_file.py --draft    → board/draft_motion.html · draft_still.html (검수용, 덮어씀 — 버전 번호를 쓰지 않음)
  python3 single_file.py --self-test

motion 판 = 턴 영상 두 칸 동기 + 켜기 모션. still 판 = 양쪽 정지 컷 + 앞뒤 버튼, 영상을 넣지 않아 가볍다.
내장하는 것은 data.js가 가리키는 것뿐(이름 규칙에 맞는 c·키, 로고, 디테일) — 나머지는 경고만.
정지 컷·디테일은 긴 변 1200px JPEG q85, 칩은 88px로 메모리에서 줄인다(board/media 원본은 그대로).
"""
import base64
import io
import json
import re
import sys
from itertools import combinations
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import die, tmpdir, write_atomic  # noqa: E402

ENGINE = Path(__file__).resolve().parent.parent / "engine"
TAGS = ('<link rel="stylesheet" href="engine.css">', '<script src="data.js"></script>', '<script src="engine.js"></script>')
KEY = r"(?:base|o[1-9]+)"
PAT = {  # media 안 경로 → (c, 키들)
    "img": re.compile(rf"img/(?P<c>[A-Za-z0-9-]+)_(?P<k>{KEY})_[FB]\.(?:jpg|jpeg|png)"),
    "loop": re.compile(rf"video/(?P<c>[A-Za-z0-9-]+)_(?P<k>{KEY})_loop\.mp4"),
    "mot": re.compile(rf"video/(?P<c>[A-Za-z0-9-]+)_m_[FB]_(?P<k>{KEY})_(?P<k2>{KEY})\.mp4"),
    "chip": re.compile(r"chips/(?P<c>[A-Za-z0-9-]+)\.(?:jpg|jpeg|png)"),
}


def board(root):
    p = root / "board" / "data.js"
    if not p.exists():
        die("board/data.js가 없음 — 작업 폴더 루트에서 실행")
    m = re.fullmatch(r"window\.BOARD\s*=\s*(\{.*\})\s*;?", p.read_text(encoding="utf-8").strip(), re.S)
    if not m:
        die("board/data.js는 `window.BOARD = {…JSON…};` 형식이어야 함")
    return json.loads(m.group(1))


def keys_of(st, multi):
    n = len(st.get("o", []))
    sets = [()] + ([c for r in range(1, n + 1) for c in combinations(range(1, n + 1), r)] if multi else [(i,) for i in range(1, n + 1)])
    return {"base" if not s else "o" + "".join(map(str, s)) for s in sets}


def wanted(data):
    """data.js가 쓸 수 있는 media 경로인지 판정하는 함수 + 꼭 있어야 하는 명시 경로."""
    multi = data.get("select") == "multi"
    keys = {st["c"]: keys_of(st, multi) for st in data.get("styles", [])}
    explicit = {p for p in ((data.get("brand") or {}).get("logo"), data.get("creditLogo")) if p}
    for st in data.get("styles", []):
        if st.get("logo"):
            explicit.add(st["logo"])
        for o in st.get("o", []):
            d = o.get("detail") or {}
            explicit |= {d[k] for k in ("before", "after", "img") if d.get(k)}

    def ok(rel):
        if rel in explicit:
            return True
        for m in (P.fullmatch(rel) for P in PAT.values()):
            if m:
                ks = keys.get(m["c"])
                return ks is not None and all(m.groupdict().get(k) in ks for k in ("k", "k2") if m.groupdict().get(k))
        return False
    return ok, explicit


def encode(path, rel):
    """내장할 바이트와 MIME. 이미지는 줄여서 JPEG(로고만 원본 그대로)."""
    ext = path.suffix.lower()
    if ext == ".mp4":
        return "video/mp4", path.read_bytes()
    from PIL import Image
    if rel.startswith(("img/", "detail/", "chips/")):
        im = Image.open(path)
        if im.mode in ("RGBA", "LA", "P"):  # 투명 PNG를 그냥 RGB로 바꾸면 바탕이 검게 된다 — 흰 바탕에 얹는다
            im = im.convert("RGBA")
            bg = Image.new("RGB", im.size, "white")
            bg.paste(im, mask=im.getchannel("A"))
            im = bg
        im = im.convert("RGB") if im.mode != "RGB" else im
        im.thumbnail((88, 88) if rel.startswith("chips/") else (1200, 1200), Image.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=85, optimize=True)
        return "image/jpeg", buf.getvalue()
    return {"png": "image/png", "svg": "image/svg+xml"}.get(ext[1:], "image/jpeg"), path.read_bytes()


def media(root, data, still):
    ok, explicit = wanted(data)
    base = root / "board" / "media"
    files, skipped = {}, []
    for p in sorted(base.rglob("*")) if base.is_dir() else []:
        if not p.is_file() or p.name.startswith("."):
            continue
        rel = p.relative_to(base).as_posix()
        if not ok(rel):
            skipped.append(rel)
            continue
        if still and rel.startswith("video/"):
            continue
        mime, raw = encode(p, rel)
        key = re.sub(r"\.(?:jpeg|png)$", ".jpg", rel) if rel.startswith(("img/", "chips/")) else rel  # 엔진은 .jpg 이름으로 찾는다
        files[key] = f"data:{mime};base64," + base64.b64encode(raw).decode()
    missing = sorted(explicit - set(files))
    if missing:
        die(f"data.js가 가리키는 파일이 board/media에 없음: {missing[:5]}")
    return files, skipped


def page(data, files, compare):
    html = (ENGINE / "index.html").read_text(encoding="utf-8")
    for t in TAGS:
        if html.count(t) != 1:
            die(f"engine/index.html에 `{t}`가 정확히 1번 있어야 함")
    js = lambda s: s.replace("</script", "<\\/script")
    html = html.replace(TAGS[0], "<style>\n" + (ENGINE / "engine.css").read_text(encoding="utf-8") + "</style>")
    html = html.replace(TAGS[1], "<script>window.M=" + json.dumps(files) + ';window.COMPARE="' + compare + '";\nwindow.BOARD=' +
                        js(json.dumps(data, ensure_ascii=False, indent=1)) + ";</script>")
    html = html.replace(TAGS[2], "<script>" + js((ENGINE / "engine.js").read_text(encoding="utf-8")) + "</script>")
    left = re.findall(r'(?:src|href)="(?!data:|#)[\w./-]+"', html)  # 정적 경로만(엔진 JS의 조합 경로는 M을 거침)
    if left:
        die(f"바깥 파일 참조가 남음 {left[:3]}")
    return html.replace("<title>Costing Option Review</title>", "<title>" + json.dumps(data.get("title") or "Costing Option Review")[1:-1] + "</title>")


def next_version(bd):
    nums = [int(m.group(1)) for p in bd.glob("v*_motion.html") if (m := re.fullmatch(r"v(\d+)_motion\.html", p.name))]
    return max(nums, default=0) + 1


def build(root=".", draft=False):
    root = Path(root)
    data = board(root)
    bd = root / "board"
    tag = "draft" if draft else f"v{next_version(bd)}"
    outs, skipped = [], []
    for compare in ("motion", "still"):
        files, skipped = media(root, data, compare == "still")
        out = bd / f"{tag}_{compare}.html"
        write_atomic(out, page(data, files, compare))
        outs.append(out)
        print(f"board/{out.name} — 파일 {len(files)}개, {out.stat().st_size / 1e6:.1f} MB")
    if skipped:
        print(f"경고: 화면이 쓰지 않아 넣지 않은 파일 {len(skipped)}개 — {', '.join(skipped[:6])}{' …' if len(skipped) > 6 else ''}", file=sys.stderr)
    return outs


def self_test():
    from PIL import Image
    tpl = Path(__file__).resolve().parent.parent / "template" / "board" / "data.js"
    with tmpdir() as t:
        root = Path(t) / "작업 폴더"
        (root / "board" / "media").mkdir(parents=True)
        data = json.loads(re.fullmatch(r"window\.BOARD\s*=\s*(\{.*\})\s*;?", tpl.read_text(encoding="utf-8").strip(), re.S).group(1))
        data["select"] = "multi"
        data["brand"]["logo"] = "logo.png"
        write_atomic(root / "board" / "data.js", "window.BOARD = " + json.dumps(data, ensure_ascii=False) + ";\n")
        m = root / "board" / "media"
        for rel in ("img/STYLE1_base_F.png", "img/STYLE1_o12_F.jpg", "img/STYLE1_o3_F.jpg", "img/OTHER_base_F.jpg",
                    "detail/STYLE1_o2_before.jpg", "detail/STYLE1_o2_after.jpg", "chips/STYLE1.jpg"):
            (m / rel).parent.mkdir(parents=True, exist_ok=True)
            Image.new("RGB", (1696, 2544), "#%06x" % (hash(rel) & 0xFFFFFF)).save(m / rel)  # 그림마다 달라야 중복 검사가 뜻이 있다
        Image.new("RGBA", (300, 60)).save(m / "logo.png")
        for rel in ("video/STYLE1_base_loop.mp4", "video/STYLE1_o1_loop.mp4", "video/STYLE1_m_F_base_o1.mp4", "video/STYLE1_m_F_o1_base.mp4"):
            (m / rel).parent.mkdir(parents=True, exist_ok=True)
            (m / rel).write_bytes(b"\0\0\0\x18ftypmp42")
        a = build(root)
        b = build(root)
        d = build(root, draft=True)
        assert [p.name for p in a + b + d] == ["v1_motion.html", "v1_still.html", "v2_motion.html", "v2_still.html",
                                               "draft_motion.html", "draft_still.html"], [p.name for p in a + b + d]
        mo, so = (p.read_text(encoding="utf-8") for p in a)
        M = lambda h: json.loads(re.search(r"window\.M=(\{.*?\});window\.COMPARE", h, re.S).group(1))
        km, ks = M(mo), M(so)
        assert "img/STYLE1_base_F.jpg" in km and "img/STYLE1_o12_F.jpg" in km      # png → jpg 이름, 조합 키
        assert "img/STYLE1_o3_F.jpg" not in km and "img/OTHER_base_F.jpg" not in km  # 옵션 3 없음 · 없는 스타일
        assert "video/STYLE1_m_F_o1_base.mp4" in km                                  # 이름 규칙은 맞음(끄기 모션은 엔진이 안 씀 — lint가 경고)
        assert not any(k.startswith("video/") for k in ks) and 'window.COMPARE="still"' in so
        assert km["detail/STYLE1_o2_before.jpg"].startswith("data:image/jpeg") and "logo.png" in km
        raw = base64.b64decode(km["img/STYLE1_base_F.jpg"].split(",", 1)[1])
        assert max(Image.open(io.BytesIO(raw)).size) == 1200
        assert mo.count(km["detail/STYLE1_o2_after.jpg"]) == 1                     # 같은 그림을 두 번 넣지 않는다
        assert 'src="engine.js"' not in mo and 'href="engine.css"' not in mo
        Image.new("RGBA", (40, 40), (0, 0, 0, 0)).save(m / "clear.png")
        assert Image.open(io.BytesIO(encode(m / "clear.png", "detail/clear.png")[1])).getpixel((0, 0)) == (255, 255, 255)  # 투명 → 흰 바탕
        (m / "detail/STYLE1_o2_after.jpg").unlink()
        try:
            build(root, draft=True)
            raise AssertionError("빠진 디테일을 못 잡음")
        except SystemExit:
            pass
    print("self-test 통과 — 두 판 · 버전 번호 · draft · 참조된 것만 · png→jpg 1200 · still 판 영상 없음 · 중복 없음 · 투명→흰 바탕 · 빠진 파일 중단")


if __name__ == "__main__":
    a = sys.argv[1:]
    if any(x in a for x in ("-h", "--help")):
        print(__doc__)
    elif "--self-test" in a:
        self_test()
    else:
        build(".", draft="--draft" in a)

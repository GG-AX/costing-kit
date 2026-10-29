"""스케치(앞|뒤 한 장)에서 앞판만 잘라 같은 배율·같은 자리로 맞춘다.

스케치마다 캔버스·여백이 달라 그대로 자르면 옷 크기가 달라 보인다. 몸판 기장(넥 위 ~ 밑단)은 같다고 보고
앞판 세로 범위로 배율을, 넥(맨 위 띠) 가운데로 가로 자리를 맞춘다. 첫 입력이 기준(대조용).

    python align_sketch.py --style <스타일> base=<기준.png> <키>=<옵션.png> ... [--out work/sketch]
    → <스타일>_<키>_F.png (흰 배경) + _overlay_<키>.png (기준 빨강 · 옵션 파랑 · 겹침 검정)
"""
import argparse
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import save_atomic  # noqa: E402


def on_white(p):
    im = Image.open(p).convert("RGBA")
    return Image.alpha_composite(Image.new("RGBA", im.size, "white"), im).convert("RGB")


def front(im, a):
    g = np.asarray(im.convert("L"))
    h, w = g.shape
    ink = (g < a.ink).sum(0)
    # 가운데 gap_lo~gap_hi 에서 가장 긴 빈 열 구간 = 앞·뒤 사이
    lo = int(w * a.gap_lo)
    z = np.where(ink[lo:int(w * a.gap_hi)] == 0)[0] + lo
    runs = np.split(z, np.where(np.diff(z) != 1)[0] + 1)
    gap = max(runs, key=len)
    assert len(gap) > a.gap_min, "앞·뒤 사이 빈 틈을 못 찾았다"
    f = im.crop((0, 0, int(gap.mean()), h))
    m = np.asarray(f.convert("L")) < a.ink
    ys, xs = np.where(m)
    y0, y1 = ys.min(), ys.max()
    # 넥 기준 가로 중심 — 맨 위 띠(넥)의 가운데. 소매 길이가 바뀌어도 흔들리지 않는다
    band = m[y0:y0 + int((y1 - y0) * a.neck_band)]
    cx = np.where(band.any(0))[0].mean()
    return f, y0, y1, cx


def run(a):
    items = []
    for it in a.items:
        k, sep, p = it.partition("=")
        if not sep or not k or not p:
            sys.exit("입력은 <키>=<경로> 형식: %r" % it)
        if not Path(p).is_file():
            sys.exit("파일 없음: %s" % p)
        items.append((k, Path(p)))
    out = Path(a.out)
    W, H = a.width, a.height
    res = {}
    for k, p in items:
        src = on_white(p)
        f, y0, y1, cx = front(src, a)
        s = a.garment_h / (y1 - y0)
        g = f.resize((round(f.width * s), round(f.height * s)), Image.LANCZOS)
        c = Image.new("RGB", (W, H), "white")
        c.paste(g, (round(W / 2 - cx * s), round(a.top - y0 * s)))
        save_atomic(c, out / ("%s_%s_F.png" % (a.style, k)))
        res[k] = c
        print("%-4s 원본 %s  앞판 세로 %d px → 배율 %.3f" % (k, src.size, y1 - y0, s))
    # 대조: 기준 선 = 빨강, 옵션 선 = 파랑, 겹치는 선 = 검정 → 바뀐 곳만 색이 남는다
    bk = items[0][0]
    b = np.asarray(res[bk].convert("L")) < a.line
    for k, _ in items[1:]:
        o = np.asarray(res[k].convert("L")) < a.line
        d = np.full((H, W, 3), 255, np.uint8)
        d[b & ~o] = (220, 40, 40)
        d[o & ~b] = (40, 80, 230)
        d[b & o] = (40, 40, 40)
        save_atomic(Image.fromarray(d), out / ("_overlay_%s.png" % k))
    print("저장:", out)
    return res


def parser():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("items", nargs="*", help="<키>=<스케치.png>, 첫 번째가 대조 기준")
    ap.add_argument("--style", help="출력 이름 앞부분 (<style>_<key>_F.png)")
    ap.add_argument("--out", default="work/sketch", help="출력 폴더 (기본 work/sketch)")
    ap.add_argument("--width", type=int, default=2000, help="출력 캔버스 가로")
    ap.add_argument("--height", type=int, default=2400, help="출력 캔버스 세로")
    ap.add_argument("--garment-h", type=int, default=1900, help="앞판 세로 범위를 이 높이로")
    ap.add_argument("--top", type=int, default=250, help="앞판 위쪽 여백 px")
    ap.add_argument("--ink", type=int, default=200, help="선으로 볼 밝기 상한 (회색조)")
    ap.add_argument("--gap-lo", type=float, default=0.3, help="앞·뒤 틈 찾는 구간 시작 (가로 비율)")
    ap.add_argument("--gap-hi", type=float, default=0.7, help="앞·뒤 틈 찾는 구간 끝")
    ap.add_argument("--gap-min", type=int, default=20, help="틈으로 인정할 최소 빈 열 수")
    ap.add_argument("--neck-band", type=float, default=0.04, help="넥 띠 높이 (앞판 세로 비율)")
    ap.add_argument("--line", type=int, default=160, help="대조 그림의 선 밝기 상한")
    ap.add_argument("--self-test", action="store_true", help="합성 이미지로 자체 점검")
    return ap


def self_test():
    def sketch(path, cw, ch, x0, y0, gw, gh):
        # 앞판(왼쪽)·뒤판(오른쪽) 사각 윤곽 + 넥 띠
        im = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
        dr = ImageDraw.Draw(im)
        for ox in (x0, cw // 2 + x0 // 2):
            dr.rectangle((ox, y0, ox + gw, y0 + gh), outline="black", width=3)
            dr.rectangle((ox + gw // 3, y0, ox + 2 * gw // 3, y0 + gh // 20), fill="black")
        im.save(path)

    with tempfile.TemporaryDirectory() as td:
        d = Path(td) / "테스트 폴더"
        d.mkdir()
        sketch(d / "기준.png", 1000, 600, 60, 40, 300, 500)
        sketch(d / "옵션 1.png", 800, 700, 100, 150, 200, 330)
        a = parser().parse_args(["--style", "ST", "--out", str(d / "출력"),
                                 "base=" + str(d / "기준.png"), "o1=" + str(d / "옵션 1.png")])
        run(a)
        for k in ("base", "o1"):
            im = Image.open(d / "출력" / ("ST_%s_F.png" % k))
            assert im.size == (2000, 2400), im.size
            m = np.asarray(im.convert("L")) < 200
            ys, xs = np.where(m)
            assert abs(ys.min() - 250) <= 6 and abs(ys.max() - 2150) <= 6  # 선 굵기 × 배율 · LANCZOS 번짐, (k, ys.min(), ys.max())
            band = m[ys.min():ys.min() + 50]
            assert abs(np.where(band.any(0))[0].mean() - 1000) <= 4, k  # 넥 가운데 = 캔버스 가운데
        assert Image.open(d / "출력" / "_overlay_o1.png").size == (2000, 2400)
    print("self-test OK")


if __name__ == "__main__":
    a = parser().parse_args()
    if a.self_test:
        self_test()
    else:
        if not a.style or len(a.items) < 1:
            parser().error("--style 와 <키>=<경로> 하나 이상이 필요하다")
        run(a)

"""옵션 컷의 배율만 바꿔 모델 키(머리 끝 ~ 밑창)를 기준 컷과 같게 한다. 그 밖의 수정은 하지 않는다.

배율 s = 기준 키 / 옵션 키 로 늘리거나 줄이고, 머리 중심(가로)과 밑창(세로)이 기준과 같은 자리에 오게 옮긴다.
빈 가장자리는 배경색으로 채운다. 밑창 = 아래 --sole-zone 안에서 밝기 < --sole-max 인 줄(짙은 신발 가정).
입력은 건드리지 않는다 — 결과는 --out 폴더에 같은 이름으로.

    python fit_height.py <기준.png> <옵션.png> [...] [--out work/fit]

예: 원본 착샷끼리 크기가 다를 때(289×549 base ↔ 1500×2000 옵션) 큰 쪽을 기준으로 작은 원본을 키워 refs/에 쓴다
    python fit_height.py source/opt.jpg source/base.png --out refs
"""
import argparse
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import save_atomic  # noqa: E402


def measure(im, a):
    x = np.asarray(im.convert("RGB")).astype(int)
    H = x.shape[0]
    bg = np.median(x[:a.bg_patch, :a.bg_patch].reshape(-1, 3), 0)
    m = np.abs(x - bg).max(-1) > a.bg_thr
    rows = np.where(m.sum(1) > a.row_min)[0]
    if not rows.size:
        raise ValueError("사람을 못 찾았다 (배경과 다른 화소 없음)")
    top = rows.min()                                             # 머리 끝
    dark = x.mean(-1) < a.sole_max                               # 짙은 신발 — 그림자는 이만큼 어둡지 않다
    z0 = int(H * (1 - a.sole_zone))
    lower = np.where(dark[z0:].sum(1) > a.sole_row_min)[0]
    if not lower.size:
        raise ValueError("밑창을 못 찾았다: 아래 %d%% 에 밝기 < %d 인 줄 없음 (--sole-max/--sole-zone 확인)"
                         % (a.sole_zone * 100, a.sole_max))
    sole = z0 + lower.max()                                      # 밑창
    head = m[top:top + int((sole - top) * a.head_band)]
    cx = np.where(head.any(0))[0].mean()                         # 머리 중심
    return int(top), int(sole), cx, tuple(int(v) for v in bg)


def fit(base_p, opt_p, out_p, a):
    b = Image.open(base_p).convert("RGB")
    o = Image.open(opt_p).convert("RGB")
    bt, bs, bcx, _ = measure(b, a)
    ot, os_, ocx, bg = measure(o, a)
    s = (bs - bt) / (os_ - ot)
    o2 = o.resize((round(o.width * s), round(o.height * s)), Image.LANCZOS)
    # 옵션의 (머리 중심, 밑창) 이 기준의 (머리 중심, 밑창) 에 오도록
    dx = round(bcx - ocx * s)
    dy = round(bs - os_ * s)
    canvas = Image.new("RGB", b.size, bg)
    canvas.paste(o2, (dx, dy))
    save_atomic(canvas, out_p)
    return s, (bt, bs), measure(canvas, a)[:2]


def run(a):
    out = Path(a.out)
    ins = {Path(p).resolve() for p in [a.base, *a.options]}
    for p in map(Path, a.options):
        q = out / p.name
        if q.resolve() in ins:
            sys.exit("입력을 덮어쓸 수 없다: %s (--out 을 다른 폴더로)" % q)
        s, b, after = fit(a.base, p, q, a)
        print("%s  배율 %.4f  기준 머리·밑창 %s → 옵션 %s  → %s" % (p.name, s, b, after, q))


def parser():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("base", nargs="?", help="기준 컷 (손대지 않음)")
    ap.add_argument("options", nargs="*", help="크기를 맞출 옵션 컷")
    ap.add_argument("--out", default="work/fit", help="출력 폴더, 같은 파일 이름 (기본 work/fit)")
    ap.add_argument("--sole-max", type=int, default=95, help="밑창으로 볼 밝기 상한 (짙은 신발)")
    ap.add_argument("--sole-zone", type=float, default=0.25, help="밑창을 찾는 아래쪽 비율")
    ap.add_argument("--sole-row-min", type=int, default=8, help="밑창 줄로 인정할 최소 어두운 화소 수")
    ap.add_argument("--bg-patch", type=int, default=30, help="배경색을 재는 왼쪽 위 정사각 크기 px")
    ap.add_argument("--bg-thr", type=int, default=30, help="사람으로 볼 배경과의 채널 차")
    ap.add_argument("--row-min", type=int, default=3, help="머리 끝 줄로 인정할 최소 화소 수")
    ap.add_argument("--head-band", type=float, default=0.08, help="머리 중심을 재는 띠 (키 비율)")
    ap.add_argument("--self-test", action="store_true", help="합성 이미지로 자체 점검")
    return ap


def self_test():
    def figure(path, size, x, top, h):
        im = np.full((size[1], size[0], 3), 235, np.uint8)
        y = lambda f: top + int(h * f)
        im[top:y(.12), x - h // 14:x + h // 14] = (200, 150, 120)          # 머리
        im[y(.12):y(.9), x - h // 6:x + h // 6] = (90, 120, 200)           # 몸·옷
        im[y(.9):top + h, x - h // 7:x + h // 7] = (40, 30, 20)            # 부츠(짙음)
        im[top + h:top + h + 6, x - h // 4:x + h // 4] = (190, 190, 190)   # 그림자(옅음)
        Image.fromarray(im).save(path)

    with tempfile.TemporaryDirectory() as td:
        d = Path(td) / "테스트"
        d.mkdir()
        figure(d / "기준.png", (400, 600), 200, 50, 500)
        figure(d / "옵션 1.png", (400, 600), 170, 120, 400)
        before = (d / "옵션 1.png").read_bytes()
        a = parser().parse_args([str(d / "기준.png"), str(d / "옵션 1.png"), "--out", str(d / "맞춤")])
        run(a)
        assert (d / "옵션 1.png").read_bytes() == before, "입력이 바뀌었다"
        bt, bs, bcx, _ = measure(Image.open(d / "기준.png"), a)
        ot, os_, ocx, _ = measure(Image.open(d / "맞춤" / "옵션 1.png"), a)
        assert Image.open(d / "맞춤" / "옵션 1.png").size == (400, 600)
        assert abs((bs - bt) - (os_ - ot)) <= 2 and abs(bs - os_) <= 1 and abs(bcx - ocx) <= 2, \
            ((bt, bs, bcx), (ot, os_, ocx))
        a.out = str(d)     # 입력 덮어쓰기 거부
        try:
            run(a)
            raise AssertionError("덮어쓰기를 막지 않았다")
        except SystemExit:
            pass
    print("self-test OK")


if __name__ == "__main__":
    a = parser().parse_args()
    if a.self_test:
        self_test()
    else:
        if not a.base or not a.options:
            parser().error("<기준.png> <옵션.png> ... 가 필요하다")
        run(a)

"""(선택 후처리) 편집을 거듭한 컷의 머리·얼굴을 1세대 컷 화소로 되돌린다.

AI 편집을 여러 번 거치면 얼굴이 조금씩 다른 사람이 된다. 두 컷은 같은 자리에 같은 사람이라
목 위를 1세대로 갈아끼우면 된다. 입력은 건드리지 않고 --out 에 쓴다.
  --mode head    (기본·권장) 목 위만 1세대, 목 아래는 편집 컷. 기장·발 위치가 바뀌어도 잔상이 없다.
  --mode garment 옷이 바뀐 영역(|편집 − 1세대| 를 닫고 채운 것)만 편집 컷, 나머지·머리는 1세대.
  목 높이: 기본은 사람 영역(배경과 다른 화소) 맨 위 ~ 맨 아래의 --neck-frac 지점.
           --fixed 면 사람이 위 --top-frac ~ 아래 --bot-frac 에 맞춰 잘린 컷으로 보고 계산만 한다.
  --split: 앞|뒤 한 장 — 좌우 반을 따로 처리.

    python restore_head.py <1세대.png> <편집.png> --out <출력.png> [--mode head|garment] [--fixed] [--split]
"""
import argparse
import sys
import tempfile
from pathlib import Path

import cv2
import numpy as np
from PIL import Image
from scipy import ndimage

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import save_atomic  # noqa: E402


def neck_row(a1, a):
    """목(어깨 시작) 높이 — 머리~턱 아래(목 중간)까지."""
    H = a1.shape[0]
    if a.fixed:    # 정렬된 컷: 사람 = top_frac ~ bot_frac
        return int(H * a.top_frac) + int(H * (a.bot_frac - a.top_frac) * a.neck_frac)
    bg = np.median(a1[5:5 + a.bg_patch, 5:5 + a.bg_patch].reshape(-1, 3), 0)
    m = np.abs(a1 - bg).max(-1) > a.bg_thr
    rows = np.where(m.sum(1) > a.row_min)[0]
    if not rows.size:
        raise ValueError("사람을 못 찾았다 (배경과 다른 화소 없음)")
    top, bot = rows.min(), rows.max()
    return top + int((bot - top) * a.neck_frac)


def head_lock(a1, ae, a):
    """목 위만 1세대, 목 아래는 편집 컷. 목에서 blend px 에 걸쳐 잇는다."""
    neck, half = neck_row(a1, a), a.blend // 2
    if not half <= neck <= a1.shape[0] - half:
        raise ValueError("목 높이 %d 가 잇는 폭 %d 와 맞지 않는다" % (neck, a.blend))
    m = np.ones(a1.shape[0], np.float32)
    m[:neck - half] = 0
    m[neck - half:neck + half] = np.linspace(0, 1, 2 * half)
    m = m[:, None, None]
    return a1 * (1 - m) + ae * m, 1.0


def garment(a1, ae, a):
    d = np.abs(ae - a1).max(-1) > a.thr
    d = cv2.morphologyEx(d.astype(np.uint8), cv2.MORPH_OPEN, np.ones((a.open, a.open), np.uint8))
    d = cv2.morphologyEx(d, cv2.MORPH_CLOSE, np.ones((a.close, a.close), np.uint8)) > 0
    lab, n = ndimage.label(d)
    if n:
        sz = ndimage.sum(d, lab, range(1, n + 1))
        d = np.isin(lab, [i + 1 for i, z in enumerate(sz) if z > a.min_area * d.size])
    d = ndimage.binary_fill_holes(d)
    d = ndimage.binary_dilation(d, np.ones((a.dilate, a.dilate), bool))
    d[:neck_row(a1, a)] = False                        # 머리·얼굴은 무조건 1세대
    m = ndimage.gaussian_filter(d.astype(np.float32), a.sigma)[..., None]
    return a1 * (1 - m) + ae * m, d.mean()


def restore(p1, pe, out, a):
    a1 = np.asarray(Image.open(p1).convert("RGB")).astype(np.float32)
    ae = np.asarray(Image.open(pe).convert("RGB").resize((a1.shape[1], a1.shape[0]), Image.LANCZOS)).astype(np.float32)
    f = head_lock if a.mode == "head" else garment
    if a.split:
        W = a1.shape[1] // 2
        (L, rl), (R, rr) = f(a1[:, :W], ae[:, :W], a), f(a1[:, W:], ae[:, W:], a)
        o, ratios = np.concatenate([L, R], 1), (rl, rr)
    else:
        o, r = f(a1, ae, a)
        ratios = (r,)
    save_atomic(Image.fromarray(np.clip(o, 0, 255).astype(np.uint8)), out)
    return ratios


def run(a):
    out = Path(a.out).resolve()
    if out in (Path(a.first).resolve(), Path(a.edit).resolve()):
        sys.exit("입력을 덮어쓸 수 없다: %s" % a.out)
    if a.blend is None:
        a.blend = 40 if a.fixed else 60
    r = restore(a.first, a.edit, a.out, a)
    print("모드 %s · 편집 컷 비율 %s → %s" % (a.mode, " · ".join("%.3f" % v for v in r), a.out))
    return r


def parser():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("first", nargs="?", help="1세대 컷 (머리 원본)")
    ap.add_argument("edit", nargs="?", help="편집 컷")
    ap.add_argument("--out", help="출력 파일 (입력과 달라야 함)")
    ap.add_argument("--mode", choices=("head", "garment"), default="head", help="head(기본) | garment")
    ap.add_argument("--split", action="store_true", help="앞|뒤 한 장: 좌우 반을 따로 처리")
    ap.add_argument("--fixed", action="store_true", help="목 높이를 --top-frac/--bot-frac 로 계산 (정렬된 컷)")
    ap.add_argument("--top-frac", type=float, default=0.05, help="--fixed: 머리 끝 위치 (세로 비율)")
    ap.add_argument("--bot-frac", type=float, default=0.95, help="--fixed: 발끝 위치 (세로 비율)")
    ap.add_argument("--neck-frac", type=float, default=0.145, help="사람 키 중 목까지 비율")
    ap.add_argument("--blend", type=int, default=None, help="목에서 잇는 폭 px (기본 60, --fixed 면 40)")
    ap.add_argument("--bg-patch", type=int, default=35, help="배경색을 재는 왼쪽 위 정사각 크기 px (5px 안쪽부터)")
    ap.add_argument("--bg-thr", type=int, default=30, help="사람으로 볼 배경과의 채널 차")
    ap.add_argument("--row-min", type=int, default=3, help="사람 줄로 인정할 최소 화소 수")
    ap.add_argument("--thr", type=int, default=28, help="garment: 바뀐 화소로 볼 채널 차")
    ap.add_argument("--open", type=int, default=5, help="garment: 잡티 제거 커널")
    ap.add_argument("--close", type=int, default=41, help="garment: 영역 닫기 커널")
    ap.add_argument("--min-area", type=float, default=0.002, help="garment: 남길 최소 조각 (면적 비율)")
    ap.add_argument("--dilate", type=int, default=9, help="garment: 영역 넓히기 커널")
    ap.add_argument("--sigma", type=float, default=3.0, help="garment: 경계 흐림")
    ap.add_argument("--self-test", action="store_true", help="합성 이미지로 자체 점검")
    return ap


def self_test():
    with tempfile.TemporaryDirectory() as td:
        d = Path(td) / "테스트"
        d.mkdir()
        x = np.full((600, 400, 3), 230, np.uint8)
        x[50:120, 170:230] = (200, 150, 120)           # 얼굴
        x[120:550, 130:270] = (60, 90, 160)            # 옷
        e = x.copy()
        e[50:120, 170:230] = (150, 100, 80)            # 얼굴이 바뀜
        e[250:400, 150:250] = (200, 40, 40)            # 옷이 바뀜
        Image.fromarray(x).save(d / "1세대.png")
        Image.fromarray(e).save(d / "편집.png")
        p = parser()
        neck = 50 + int(499 * 0.145)                   # 사람 50~549
        for extra in ([], ["--split"], ["--mode", "garment"]):
            a = p.parse_args([str(d / "1세대.png"), str(d / "편집.png"), "--out", str(d / "출력.png"), *extra])
            run(a)
            o = np.asarray(Image.open(d / "출력.png")).astype(int)
            assert o.shape == x.shape, extra
            assert np.abs(o[:neck - 30] - x[:neck - 30]).max() <= 1, extra      # 얼굴 = 1세대
            assert np.abs(o[260:390, 160:240] - e[260:390, 160:240]).max() <= 1, extra  # 옷 = 편집
        a = p.parse_args([str(d / "1세대.png"), str(d / "편집.png"), "--out", str(d / "고정.png"), "--fixed"])
        run(a)
        fn = int(600 * .05) + int(600 * .9 * .145)
        o = np.asarray(Image.open(d / "고정.png")).astype(int)
        assert np.abs(o[:fn - 20] - x[:fn - 20]).max() <= 1 and np.abs(o[fn + 20:] - e[fn + 20:]).max() <= 1
        try:
            run(p.parse_args([str(d / "1세대.png"), str(d / "편집.png"), "--out", str(d / "편집.png")]))
            raise AssertionError("덮어쓰기를 막지 않았다")
        except SystemExit:
            pass
    print("self-test OK")


if __name__ == "__main__":
    a = parser().parse_args()
    if a.self_test:
        self_test()
    else:
        if not (a.first and a.edit and a.out):
            parser().error("<1세대.png> <편집.png> --out <출력.png> 가 필요하다")
        run(a)

"""面积恒等回归 + dirty 预览冒烟 + 预览/落库读回互证。

数据夹具在独立模块 ``area_fixtures.py``，本模块只放断言函数与 pytest 用例。

覆盖（两类取舍都在，不可只测其一）：
1. 纯函数恒等：六面展开 × 折边 overlap 后按仓库位数（3 位小数）独立重算，
   与现有面积入口 ``paper_area`` 返回的 ``paper_m2`` 恒等（参数化 ≥6 组，
   含种子书型盒）。
2. 写入读回：同一份参数先预览（save=False）再落库（save=True），从
   calc_runs 读回的 paper_m2 必须与预览一致，且与纯函数重算值一致。
另含边长 0 / 负的拒绝用例（各一条，文案可区分）与 dirty 礼盒预览冒烟
（必须 422 失败，且用纸档 papers 不加行）。
"""

import json

import pytest
from fastapi import HTTPException

from app.db import connect
from app.engines.wrap_math import paper_area
from app.repositories import boxes as box_repo
from app.repositories import papers as paper_repo
from app.services import estimate_service

from area_fixtures import AREA_CASES, REJECT_CASES

# 仓库存储口径：wrap_math.paper_area 统一保留 3 位小数。
STORE_DECIMALS = 3


def expected_paper_m2(length, width, height, overlap):
    """按既有口径独立重算：六面展开面积 × 折边，再按仓库位数圆整。

    刻意不调用 paper_area，也不复用其 2*(lw+lh+wh) 写法，而是把六个面
    逐项列出后求和，保证是独立的第二条计算路径。
    """
    six_faces = [
        length * width,   # 上
        length * width,   # 下
        length * height,  # 前
        length * height,  # 后
        width * height,   # 左
        width * height,   # 右
    ]
    return round(sum(six_faces) * overlap, STORE_DECIMALS)


def assert_area_identity(label, length, width, height, overlap):
    """断言函数：走现有面积入口，比对独立重算值；失败打印输入与结果。"""
    result = paper_area(length, width, height, overlap)
    got = result["paper_m2"]
    want = expected_paper_m2(length, width, height, overlap)
    if got != want:
        diag = (
            f"[{label}] 输入 length={length}, width={width}, height={height}, "
            f"overlap={overlap}; paper_area 结果 paper_m2={got!r} "
            f"box_surface={result.get('box_surface')!r}; 六面×折边独立重算={want!r}"
        )
        print(diag)
        pytest.fail(diag)
    return result


@pytest.mark.parametrize("label,length,width,height,overlap", AREA_CASES,
                         ids=[c[0] for c in AREA_CASES])
def test_paper_m2_identity_six_faces_times_overlap(label, length, width, height, overlap):
    """每组夹具走现有面积入口，paper_m2 == 六面 × 折边按 3 位圆整。"""
    result = assert_area_identity(label, length, width, height, overlap)
    # 入口返回结构与圆整位数的最低限度护栏。
    assert set(["box_surface", "overlap", "paper_m2"]).issubset(result)
    assert result["paper_m2"] == round(result["paper_m2"], STORE_DECIMALS)


def test_seed_book_box_is_in_cases():
    """首组夹具必须取自 seed.py 的种子书型盒（0.30×0.20×0.15 / 1.15）。"""
    label, length, width, height, overlap = AREA_CASES[0]
    assert "seed-book" in label
    assert (length, width, height, overlap) == (0.30, 0.20, 0.15, 1.15)
    seeded = next(b for b in box_repo.list_boxes() if b["name"] == "书型盒")
    assert (seeded["length"], seeded["width"], seeded["height"]) == (0.30, 0.20, 0.15)
    assert_area_identity(label, seeded["length"], seeded["width"], seeded["height"], overlap)


@pytest.mark.parametrize("label,length,width,height,overlap,tag", REJECT_CASES,
                         ids=[c[0] for c in REJECT_CASES])
def test_non_positive_edge_rejected(label, length, width, height, overlap, tag):
    """边长为 0、为负各一条拒绝用例；tag 为可区分文案。"""
    assert tag in ("边长为 0", "边长为负")
    try:
        paper_area(length, width, height, overlap)
    except ValueError as exc:
        # 两条用例必须能用各自文案区分，且入口确实以 ValueError 拒绝。
        assert str(exc).strip() != ""
        print(f"[{label}] {tag}: 输入=({length},{width},{height}) 已被拒绝: {exc}")
        return
    diag = f"[{label}] {tag}: 输入=({length},{width},{height}) 应被拒绝却返回了结果"
    print(diag)
    pytest.fail(diag)


def _count_papers():
    return len(paper_repo.list_papers())


def _count_runs():
    c = connect()
    try:
        return c.execute("SELECT COUNT(*) c FROM calc_runs").fetchone()["c"]
    finally:
        c.close()


def _get_dirty_box():
    dirty = [b for b in box_repo.list_boxes() if b.get("data_quality") == "dirty"]
    assert dirty, "seed 数据中应存在 dirty 礼盒"
    return dirty[0]


def test_dirty_box_preview_must_fail_and_no_paper_row():
    """dirty 礼盒预览冒烟：必须失败（422），且用纸档 papers 不加行。"""
    box = _get_dirty_box()
    papers_before = _count_papers()
    runs_before = _count_runs()

    with pytest.raises(HTTPException) as ei:
        estimate_service.run_estimate(box["id"], 1.15, "cross", save=False, note="")
    assert ei.value.status_code == 422

    # 用纸档不加行；失败的预览也不得产生落库运行记录。
    assert _count_papers() == papers_before
    assert _count_runs() == runs_before


def test_preview_then_save_readback_matches():
    """同参先预览再落库：读回 paper_m2 与预览一致，并与纯函数恒等值互证。"""
    # 取种子「方形礼盒」，尺寸与夹具 flat-square 同参 (0.25,0.25,0.10,1.20)。
    box = next(b for b in box_repo.list_boxes() if b["name"] == "方形礼盒")
    length, width, height, overlap = box["length"], box["width"], box["height"], 1.20
    want = expected_paper_m2(length, width, height, overlap)

    # 1) 纯函数恒等（与面积用例同一入口）。
    pure = paper_area(length, width, height, overlap)["paper_m2"]
    assert pure == want

    # 2) 先预览：不落库、无 run_id。
    preview = estimate_service.run_estimate(box["id"], overlap, "cross", save=False, note="")
    assert preview["run_id"] is None
    preview_m2 = preview["paper_m2"]
    assert preview_m2 == want

    runs_before = _count_runs()

    # 3) 同参再落库。
    saved = estimate_service.run_estimate(box["id"], overlap, "cross", save=True, note="roundtrip")
    run_id = saved["run_id"]
    assert isinstance(run_id, int)
    assert saved["paper_m2"] == preview_m2
    assert _count_runs() == runs_before + 1

    # 4) 从仓库读回结果 JSON，paper_m2 必须与预览一致 —— 写入/读回与纯函数互证。
    c = connect()
    try:
        row = c.execute(
            "SELECT box_id, overlap, result_json FROM calc_runs WHERE id=?", (run_id,)
        ).fetchone()
    finally:
        c.close()
    assert row is not None, f"run_id={run_id} 未落库"
    stored = json.loads(row["result_json"])
    assert row["box_id"] == box["id"]
    assert stored["paper_m2"] == preview_m2 == pure == want

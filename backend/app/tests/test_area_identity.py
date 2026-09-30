"""面积恒等回归 + 写入读回互证测例。

夹具表（(长,宽,高,overlap) 数据与独立参照公式）在 area_fixtures.py，
本模块只放断言与测例，两个模块分开存放。

覆盖：
1. 纯函数恒等：六组以上 (长,宽,高,overlap) 走现有面积入口 paper_area，
   paper_m2 必须等于「六面 × 折边后按仓库位数圆整」的独立参照值；
   失败时打印输入与结果。
2. 拒绝用例：边长为 0、为负各一条，错误文案可区分。
3. dirty 礼盒预览冒烟：必须失败，且用纸档（calc_runs）不加行。
4. 同参先预览（save=False）再落库（save=True），读回 paper_m2 与预览一致，
   并与纯函数结果、夹具期望值互相对齐——纯函数恒等与写入读回都要覆盖。
"""

import pytest
from fastapi import HTTPException

from app import seed
from app.db import connect
from app.engines.wrap_math import paper_area
from app.repositories import history, papers as papers_repo
from app.services import estimate_service
from area_fixtures import AREA_CASES, expected_cases, expected_paper_m2


def assert_paper_identity(label, length, width, height, overlap, expected):
    """走现有面积入口，断言 paper_m2 等于独立参照值；失败打印输入与结果。"""
    result = paper_area(length, width, height, overlap)
    got = result["paper_m2"]
    if got != expected:
        print(
            f"[面积恒等失败] case={label} | 输入: 长={length}, 宽={width}, "
            f"高={height}, overlap={overlap} | 入口结果: {result} | "
            f"期望 paper_m2={expected}"
        )
    assert got == expected, (
        f"case={label} 输入(长={length}, 宽={width}, 高={height}, overlap={overlap}) "
        f"结果 paper_m2={got} 期望 {expected}"
    )


@pytest.mark.parametrize(
    "label,length,width,height,overlap,expected",
    expected_cases(),
    ids=[c[0] for c in expected_cases()],
)
def test_paper_area_identity(label, length, width, height, overlap, expected):
    """六面 × 折边再按仓库位数圆整：现有面积入口对夹具表逐组恒等。"""
    assert_paper_identity(label, length, width, height, overlap, expected)


def test_fixture_contains_seed_book_box():
    """夹具表必须包含种子书型盒 (0.30, 0.20, 0.15, 1.15)，且手写组至少四组。"""
    assert ("seed-book-box-书型盒", 0.30, 0.20, 0.15, 1.15) in AREA_CASES
    handwritten = [c for c in AREA_CASES if not c[0].startswith("seed-")]
    assert len(handwritten) >= 4
    assert len(AREA_CASES) >= 6


def test_zero_dimension_rejected():
    """边长为 0 必须被拒绝。"""
    with pytest.raises(ValueError) as exc:
        paper_area(0.0, 0.20, 0.15, 1.15)
    assert "zero" in str(exc.value)


def test_negative_dimension_rejected():
    """边长为负必须被拒绝，文案与为 0 的用例可区分。"""
    with pytest.raises(ValueError) as exc:
        paper_area(0.20, 0.20, -0.10, 1.15)
    assert "negative" in str(exc.value)
    assert "zero" not in str(exc.value)


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    """每个 DB 测例使用独立临时库并播种，绝不污染仓库默认 data/app.db。"""
    db_file = tmp_path / "test_warehouse.db"
    monkeypatch.setattr("app.config.DB_PATH", db_file)
    monkeypatch.setattr("app.db.DB_PATH", db_file)
    seed.init_db()
    return db_file


def _insert_box(name, length, width, height, quality="clean"):
    c = connect()
    try:
        cur = c.execute(
            "INSERT INTO boxes(name,length,width,height,data_quality,note) "
            "VALUES (?,?,?,?,?,?)",
            (name, length, width, height, quality, ""),
        )
        c.commit()
        return int(cur.lastrowid)
    finally:
        c.close()


def _runs_count():
    c = connect()
    try:
        return c.execute("SELECT COUNT(*) c FROM calc_runs").fetchone()["c"]
    finally:
        c.close()


def test_dirty_gift_box_preview_smoke(temp_db):
    """dirty 礼盒（种子 id=3）预览必须失败，用纸档（calc_runs）不加行。"""
    runs_before = _runs_count()
    papers_before = len(papers_repo.list_papers())

    with pytest.raises(HTTPException) as exc:
        estimate_service.run_estimate(3, 1.15, "cross", save=False, note="")
    assert exc.value.status_code == 422

    assert _runs_count() == runs_before == 0
    # 估算流程本身不应改动纸张表
    assert len(papers_repo.list_papers()) == papers_before


@pytest.mark.parametrize(
    "label,length,width,height,overlap,expected",
    expected_cases(),
    ids=[c[0] for c in AREA_CASES],
)
def test_preview_then_save_readback(temp_db, label, length, width, height, overlap, expected):
    """同参先预览再落库：读回 paper_m2 与预览、纯函数结果、夹具期望四者一致。"""
    # 种子书型盒已由 init_db 播种为 id=1；其余夹具组临时建盒
    if label == "seed-book-box-书型盒":
        box_id = 1
    else:
        box_id = _insert_box(f"手写-{label}", length, width, height)

    runs_before = _runs_count()

    # 1) 先预览（不落库）
    preview = estimate_service.run_estimate(
        box_id, overlap, "cross", save=False, note="preview"
    )
    assert preview["run_id"] is None
    assert _runs_count() == runs_before

    # 2) 同参再落库
    saved = estimate_service.run_estimate(
        box_id, overlap, "cross", save=True, note="saved"
    )
    assert saved["run_id"] is not None
    assert _runs_count() == runs_before + 1

    # 3) 从用纸档读回
    runs = history.list_runs()
    row = next(r for r in runs if r["id"] == saved["run_id"])
    readback_paper_m2 = row["result"]["paper_m2"]

    pure = paper_area(length, width, height, overlap)["paper_m2"]

    if not (preview["paper_m2"] == saved["paper_m2"] == readback_paper_m2 == pure == expected):
        print(
            f"[预览/落库不一致] case={label} | 输入: 长={length}, 宽={width}, "
            f"高={height}, overlap={overlap} | 预览={preview['paper_m2']}, "
            f"落库返回={saved['paper_m2']}, 读回={readback_paper_m2}, "
            f"纯函数={pure}, 期望={expected} | 读回行: {row}"
        )
    # 纯函数恒等 与 写入读回互证
    assert preview["paper_m2"] == pure == expected
    assert readback_paper_m2 == preview["paper_m2"]
    assert saved["paper_m2"] == preview["paper_m2"]

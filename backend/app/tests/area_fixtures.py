"""面积恒等回归的夹具表模块：只放 (长, 宽, 高, overlap) 数据与独立参照值。

单位均为米；overlap 为折边系数（种子设置默认 1.15）。
断言函数在 test_area_identity.py，两边分模块存放，互不混写。

首组直接取自 app/seed.py 的种子「书型盒」(id=1)，其余为手写用例。
expected 一律按「六面总面积 × overlap 后再按仓库位数圆整」独立重算，
不调用生产函数 paper_area，以保证参照值独立。
"""

# 仓库圆整位数，须与 app/engines/wrap_math.py 中 paper_area 的 round(..., 3) 一致
WAREHOUSE_DECIMALS = 3

# (标签, 长, 宽, 高, overlap)
AREA_CASES = [
    ("seed-book-box-书型盒", 0.30, 0.20, 0.15, 1.15),  # 种子数据，必须保留在首位
    ("unit-cube-no-overlap", 1.0, 1.0, 1.0, 1.0),      # 手写：单位立方体，折边系数 1
    ("small-cube-overlap", 0.10, 0.10, 0.10, 1.20),    # 手写：小立方盒
    ("long-flat-box", 0.50, 0.30, 0.05, 1.10),         # 手写：扁平长盒
    ("tall-box", 0.20, 0.20, 0.40, 1.25),              # 手写：高盒
    ("tiny-fractional", 0.07, 0.11, 0.13, 1.08),       # 手写：零碎小数边长
]


def expected_paper_m2(length: float, width: float, height: float, overlap: float) -> float:
    """独立参照公式：六面 × 折边，再按仓库位数圆整。"""
    six_face_surface = 2 * (length * width + length * height + width * height)
    return round(six_face_surface * float(overlap), WAREHOUSE_DECIMALS)


def expected_cases():
    """返回带期望圆整值的 (label, l, w, h, overlap, expected_paper_m2) 列表。"""
    return [
        (label, l, w, h, ov, expected_paper_m2(l, w, h, ov))
        for label, l, w, h, ov in AREA_CASES
    ]

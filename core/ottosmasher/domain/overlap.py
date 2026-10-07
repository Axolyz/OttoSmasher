"""正长度交叠（规格 04 §4.3.3）：全应用只有这一个判定——标签继承、命名找交叠文字、派生范围、文字层、OP/ED 排除、音高检索的标签范围都用它。

``a.start < b.end 且 a.end > b.start``，端点相接不算；浮点误差按 ``EPS`` 吸收（同一个容差）。
"""

from __future__ import annotations

EPS = 1e-9
"""秒。小于它的差视为相等（端点相接）。"""


def overlaps(a0: float, a1: float, b0: float, b1: float) -> bool:
    return a0 < b1 - EPS and a1 > b0 + EPS


def contains(outer0: float, outer1: float, a0: float, a1: float) -> bool:
    """a 完全落在 outer 里（含端点）。"""
    return a0 >= outer0 - EPS and a1 <= outer1 + EPS

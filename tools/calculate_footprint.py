#!/usr/bin/env python3
"""
计算机器人顶升货架后的 footprint 和相对 base_link 原点的外接圆半径。

特点：
1. 单文件运行，不需要 ROS、NumPy、OpenCV 或其他第三方库。
2. 默认参数与 launch/test_footprint_main.launch 一致。
3. 使用连续几何坐标计算，不经过像素栅格化。

坐标约定：
- x 轴正方向：机器人前方
- x 轴负方向：机器人后方
- y 轴正方向：机器人左侧
- y 轴负方向：机器人右侧
- 所有长度单位均为米

使用方法：

1. 直接使用文件下方的默认参数：

   python3 calculate_footprint.py

2. 从命令行指定货架长宽：

   python3 calculate_footprint.py --rack-length 1.2 --rack-width 0.8

3. 指定全部货架位置参数：

   python3 calculate_footprint.py --rack-length 1.2 --rack-width 0.8 \
       --back-depth 0.0 \
       --front-limit-x 0.3634 \
       --center-to-rear 0.0

4. 指定机器人原始 footprint。参数需要作为一个完整字符串传入：

   python3 calculate_footprint.py \
       --base-footprint '[[0.46,0.266],[0.41,0.303],[-0.41,0.303],[-0.46,0.266],[-0.46,-0.266],[-0.41,-0.303],[0.41,-0.303],[0.46,-0.266]]' \
       --rack-length 1.1 \
       --rack-width 1.1

也可以直接修改下面“默认输入参数”区域后运行。

输出字段：
- rack_placement：货架中心、前沿和后沿的 x 坐标
- rack_rectangle：货架矩形的四个顶点
- lifted_footprint：机器人 footprint 与货架矩形合并后的外轮廓
- circumscribed_radius_m：以 base_link 原点 (0, 0) 为圆心的外接圆半径
- footprint_length_x_m：合并 footprint 在 x 方向的长度
- footprint_width_y_m：合并 footprint 在 y 方向的宽度
"""



import argparse
import ast
import json
import math
from typing import Dict, List, Sequence, Tuple

# matplotlib 仅在交互/绘图模式下使用，命令行 JSON 模式不依赖它
try:
    import matplotlib
    matplotlib.use('TkAgg')
    import matplotlib.pyplot as plt
    from matplotlib import font_manager as _fm
    # Windows 中文支持：优先选用微软雅黑
    _CN_FONT_NAMES = ['Microsoft YaHei', 'SimHei', 'WenQuanYi Micro Hei', 'Noto Sans CJK SC']
    for _f in _CN_FONT_NAMES:
        try:
            _fm.findfont(_f, fallback_to_default=False)
            plt.rcParams['font.sans-serif'] = [_f, 'DejaVu Sans']
            plt.rcParams['axes.unicode_minus'] = False
            break
        except Exception:
            continue
    _HAS_MPL = True
except Exception:
    _HAS_MPL = False


Point = Tuple[float, float]
# 浮点数比较容差，用于判断点重合、共线和线段相交。
EPS = 1e-9

# ---------------------------------------------------------------------------
# 默认输入参数
# ---------------------------------------------------------------------------
# 这些值与 test_footprint_main.launch 保持一致。
# 不使用命令行参数时，程序直接使用这里的配置。
BASE_FOOTPRINT = [
    [0.46, 0.266],
    [0.410, 0.303],
    [-0.410, 0.303],
    [-0.46, 0.266],
    [-0.460, -0.266],
    [-0.41, -0.303],
    [0.41, -0.303],
    [0.46, -0.266],
]
RACK_LENGTH_M = 0.5     # B
RACK_WIDTH_M = 0.76      # A
BACK_DEPTH_M = 0.0
FRONT_LIMIT_X_M = 0.3634
CENTER_TO_REAR_M = 0.0


def cross(a: Point, b: Point) -> float:
    """计算二维向量叉积，用于判断方向、共线和线段相交。"""
    return a[0] * b[1] - a[1] * b[0]


def subtract(a: Point, b: Point) -> Point:
    """计算向量 a - b。"""
    return a[0] - b[0], a[1] - b[1]


def interpolate(a: Point, b: Point, t: float) -> Point:
    """计算线段 AB 上参数为 t 的点，t=0 对应 A，t=1 对应 B。"""
    return a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t


def signed_area(polygon: Sequence[Point]) -> float:
    """
    计算多边形有符号面积。

    面积大于 0 表示顶点为逆时针排列，小于 0 表示顺时针排列。
    """
    return 0.5 * sum(
        polygon[i][0] * polygon[(i + 1) % len(polygon)][1]
        - polygon[(i + 1) % len(polygon)][0] * polygon[i][1]
        for i in range(len(polygon))
    )


def normalize_polygon(points: Sequence[Sequence[float]]) -> List[Point]:
    """检查多边形输入，移除重复闭合点，并统一为逆时针排列。"""
    polygon = [(float(point[0]), float(point[1])) for point in points]
    # 输入允许首尾重复，例如 [..., [0.46, 0.266]]。
    if len(polygon) >= 2 and distance(polygon[0], polygon[-1]) <= EPS:
        polygon.pop()
    if len(polygon) < 3:
        raise ValueError("footprint must contain at least three points")
    if signed_area(polygon) < 0.0:
        polygon.reverse()
    return polygon


def distance(a: Point, b: Point) -> float:
    """计算两个二维点之间的欧氏距离。"""
    return math.hypot(a[0] - b[0], a[1] - b[1])


def point_location(point: Point, polygon: Sequence[Point]) -> int:
    """
    判断点与多边形的位置关系。

    返回值：
    - 1：点在多边形内部
    - 0：点在多边形边界上
    - -1：点在多边形外部
    """
    inside = False
    px, py = point
    for index, a in enumerate(polygon):
        b = polygon[(index + 1) % len(polygon)]
        ab = subtract(b, a)
        ap = subtract(point, a)

        # 点与边 AB 共线，并且投影落在线段范围内，说明点在边界上。
        if abs(cross(ab, ap)) <= EPS:
            dot = ap[0] * ab[0] + ap[1] * ab[1]
            if -EPS <= dot <= ab[0] * ab[0] + ab[1] * ab[1] + EPS:
                return 0

        # 射线法：从待测点向 x 正方向发射射线，统计穿过多边形边界的次数。
        if (a[1] > py) != (b[1] > py):
            x_crossing = a[0] + (py - a[1]) * (b[0] - a[0]) / (b[1] - a[1])
            if x_crossing > px:
                inside = not inside
    return 1 if inside else -1


def segment_split_parameters(a: Point, b: Point, c: Point, d: Point) -> List[float]:
    """
    求线段 AB 与 CD 的交点在 AB 上的位置参数。

    返回 t 后，可以通过 A + t * (B - A) 得到交点。共线重叠时会返回
    CD 两个端点中落在 AB 上的位置，供后续切分边界使用。
    """
    r = subtract(b, a)
    s = subtract(d, c)
    denominator = cross(r, s)
    c_minus_a = subtract(c, a)

    # 两条直线不平行时，分别计算交点在 AB、CD 上的参数 t 和 u。
    if abs(denominator) > EPS:
        t = cross(c_minus_a, s) / denominator
        u = cross(c_minus_a, r) / denominator
        if -EPS <= t <= 1.0 + EPS and -EPS <= u <= 1.0 + EPS:
            return [min(1.0, max(0.0, t))]
        return []

    # 平行但不共线，不存在交点。
    if abs(cross(c_minus_a, r)) > EPS:
        return []

    # 共线时，找出 CD 端点在 AB 上的位置。
    length_squared = r[0] * r[0] + r[1] * r[1]
    if length_squared <= EPS:
        return []
    values = []
    for point in (c, d):
        t = ((point[0] - a[0]) * r[0] + (point[1] - a[1]) * r[1]) / length_squared
        if -EPS <= t <= 1.0 + EPS:
            values.append(min(1.0, max(0.0, t)))
    return values


def split_polygon_edges(
    polygon: Sequence[Point], other: Sequence[Point]
) -> List[Tuple[Point, Point]]:
    """
    使用另一个多边形的边，把当前多边形每条边切成若干短线段。

    切分之后，每一小段的中点都不会跨越另一个多边形的边界，
    因此可以明确判断这段边位于另一个多边形的内部还是外部。
    """
    segments = []
    for index, a in enumerate(polygon):
        b = polygon[(index + 1) % len(polygon)]
        parameters = [0.0, 1.0]
        for other_index, c in enumerate(other):
            d = other[(other_index + 1) % len(other)]
            parameters.extend(segment_split_parameters(a, b, c, d))
        parameters.sort()
        unique_parameters = []
        for value in parameters:
            if not unique_parameters or abs(value - unique_parameters[-1]) > EPS:
                unique_parameters.append(value)
        for start_t, end_t in zip(unique_parameters, unique_parameters[1:]):
            if end_t - start_t > EPS:
                segments.append((interpolate(a, b, start_t), interpolate(a, b, end_t)))
    return segments


def is_union_boundary(segment: Tuple[Point, Point], other: Sequence[Point]) -> bool:
    """判断一小段边是否应该保留为两个多边形并集的外边界。"""
    a, b = segment
    midpoint = interpolate(a, b, 0.5)

    # 位于另一个多边形内部的边属于合并图形内部，不是最终外轮廓。
    if point_location(midpoint, other) == 1:
        return False

    length = distance(a, b)
    if length <= EPS:
        return False
    # 多边形已经统一为逆时针，因此自身内部位于有向边的左侧。
    # 如果另一个多边形还占据边的右侧，这是一条内部公共边，需要删除。
    right_offset = (
        midpoint[0] + (b[1] - a[1]) / length * 1e-7,
        midpoint[1] - (b[0] - a[0]) / length * 1e-7,
    )
    return point_location(right_offset, other) != 1


def point_key(point: Point) -> Tuple[int, int]:
    """把浮点坐标转成稳定的整数键，便于连接相同端点的线段。"""
    return round(point[0] / EPS), round(point[1] / EPS)


def polygon_union(first: Sequence[Point], second: Sequence[Point]) -> List[Point]:
    """
    计算两个简单多边形的并集外轮廓。

    实现步骤：
    1. 在两个多边形的所有交点处切分边。
    2. 删除落在另一个多边形内部的短边。
    3. 将剩余短边按首尾连接成闭合轮廓。
    4. 取面积最大的闭合轮廓作为最终 footprint。

    当前业务中两个多边形分别是机器人 footprint 和轴对齐货架矩形。
    它们应当相交或互相包含，从而形成一个连续的合并 footprint。
    """
    # 分别收集两个多边形中属于并集外轮廓的边段。
    candidate_segments = [
        segment
        for segment in split_polygon_edges(first, second)
        if is_union_boundary(segment, second)
    ]
    candidate_segments.extend(
        segment
        for segment in split_polygon_edges(second, first)
        if is_union_boundary(segment, first)
    )

    # 去除完全重合的公共边。键按无方向端点排序，AB 与 BA 被视为同一条边。
    unique_segments: Dict[Tuple[Tuple[int, int], Tuple[int, int]], Tuple[Point, Point]] = {}
    for segment in candidate_segments:
        a_key, b_key = point_key(segment[0]), point_key(segment[1])
        undirected_key = tuple(sorted((a_key, b_key)))
        unique_segments.setdefault(undirected_key, segment)

    # 建立“起点 -> 边段”索引，后面从一条边快速找到下一条边。
    outgoing: Dict[Tuple[int, int], List[Tuple[Point, Point]]] = {}
    for segment in unique_segments.values():
        outgoing.setdefault(point_key(segment[0]), []).append(segment)

    # 将所有未使用的边段依次连接成一个或多个闭合轮廓。
    loops = []
    unused = set(unique_segments)
    while unused:
        segment_key = next(iter(unused))
        first_segment = unique_segments[segment_key]
        loop = [first_segment[0]]
        current = first_segment
        unused.remove(segment_key)

        for _ in range(len(unique_segments) + 1):
            loop.append(current[1])
            if point_key(current[1]) == point_key(loop[0]):
                loop.pop()
                break
            choices = []
            for next_segment in outgoing.get(point_key(current[1]), []):
                next_key = tuple(sorted((point_key(next_segment[0]), point_key(next_segment[1]))))
                if next_key in unused:
                    choices.append((next_key, next_segment))
            if not choices:
                raise ValueError("failed to build a closed union footprint")
            next_key, current = choices[0]
            unused.remove(next_key)
        loops.append(remove_collinear_points(loop))

    if not loops:
        raise ValueError("the two polygons do not produce a valid union")
    # 正常业务输入只有一个外轮廓。若出现多个，保留面积最大的主体。
    result = max(loops, key=lambda polygon: abs(signed_area(polygon)))
    if signed_area(result) < 0.0:
        result.reverse()
    return rotate_to_front_right(result)


def remove_collinear_points(polygon: Sequence[Point]) -> List[Point]:
    """删除轮廓上处于同一直线的中间点，使输出 footprint 更简洁。"""
    result = list(polygon)
    changed = True
    while changed and len(result) > 3:
        changed = False
        for index, current in enumerate(result):
            previous = result[index - 1]
            following = result[(index + 1) % len(result)]
            if abs(cross(subtract(current, previous), subtract(following, current))) <= EPS:
                result.pop(index)
                changed = True
                break
    return result


def rotate_to_front_right(polygon: Sequence[Point]) -> List[Point]:
    """
    调整顶点输出起点，但不改变多边形形状。

    与 C++ 逻辑一致：在最前方 x 附近选择 y 最小的点作为第一个点，
    即从机器人右前方开始输出 footprint。
    """
    max_x = max(point[0] for point in polygon)
    candidates = [
        (index, point)
        for index, point in enumerate(polygon)
        if point[0] >= max_x - 0.01
    ]
    start_index = min(candidates, key=lambda item: item[1][1])[0]
    return list(polygon[start_index:]) + list(polygon[:start_index])


def compute_rack_rectangle(
    base_footprint: Sequence[Point],
    rack_length_m: float,
    rack_width_m: float,
    back_depth_m: float,
    front_limit_x_m: float,
    center_to_rear_m: float,
) -> Tuple[List[Point], Dict[str, float]]:
    """
    根据业务参数计算货架在 base_link 坐标系中的矩形。

    rack_length_m：
        货架沿 x 方向的长度。
    rack_width_m：
        货架沿 y 方向的宽度。
    back_depth_m：
        配置时表示“机器人尾部参考位置到货架前沿”的 x 距离。
        接近 0 时，先让货架中心位于 x=0，再应用前方限位。
    front_limit_x_m：
        货架前沿允许到达的最大 x 坐标。
    center_to_rear_m：
        可选的机器人中心到尾部距离。大于 0.01 时覆盖原始 footprint
        中的最小 x；0 表示直接使用原始 footprint 的尾部坐标。
    """
    if rack_length_m <= 0.0 or rack_width_m <= 0.0 or back_depth_m < 0.0:
        raise ValueError("rack length/width must be positive and back depth must be non-negative")

    # 原始 footprint 中 x 最小的位置就是机器人尾部。
    robot_rear_x = min(point[0] for point in base_footprint)
    center_to_rear_x = -center_to_rear_m if center_to_rear_m > 0.01 else robot_rear_x

    # back_depth 有效时，从机器人尾部参考位置向前确定货架前沿。
    # 未配置时，先将货架中心放在原点。
    if back_depth_m > rack_width_m * 0.01:
        rack_front_x = center_to_rear_x + back_depth_m
    else:
        rack_front_x = rack_length_m * 0.5

    rack_rear_x = rack_front_x - rack_length_m
    rack_center_x = rack_front_x - rack_length_m * 0.5

    # 如果货架前沿超过机械限位，就将整个货架沿 x 负方向后移。
    if rack_front_x > front_limit_x_m:
        overflow = rack_front_x - front_limit_x_m
        rack_front_x -= overflow
        rack_rear_x -= overflow
        rack_center_x -= overflow

    if rack_front_x < robot_rear_x:
        raise ValueError(
            "rack is behind the robot footprint: "
            "rack_front_x ({:.4f}) < robot_rear_x ({:.4f})".format(
                rack_front_x, robot_rear_x
            )
        )

    # 根据前后沿和半宽生成货架矩形。
    half_width = rack_width_m * 0.5
    rectangle = [
        (rack_front_x, half_width),
        (rack_rear_x, half_width),
        (rack_rear_x, -half_width),
        (rack_front_x, -half_width),
    ]
    rectangle = normalize_polygon(rectangle)
    placement = {
        "center_x_m": rack_center_x,
        "front_x_m": rack_front_x,
        "rear_x_m": rack_rear_x,
    }
    return rectangle, placement


def calculate(
    base_footprint: Sequence[Sequence[float]],
    rack_length_m: float,
    rack_width_m: float,
    back_depth_m: float,
    front_limit_x_m: float,
    center_to_rear_m: float,
) -> Dict[str, object]:
    """执行完整计算并返回适合输出为 JSON 的结果。"""
    # 统一机器人 footprint 顶点方向，生成货架矩形，再计算两者并集。
    base_polygon = normalize_polygon(base_footprint)
    rack_rectangle, placement = compute_rack_rectangle(
        base_polygon,
        rack_length_m,
        rack_width_m,
        back_depth_m,
        front_limit_x_m,
        center_to_rear_m,
    )
    lifted_footprint = polygon_union(base_polygon, rack_rectangle)

    # 轴对齐包围盒用于计算 footprint 的整体长度和宽度。
    min_x = min(point[0] for point in lifted_footprint)
    max_x = max(point[0] for point in lifted_footprint)
    min_y = min(point[1] for point in lifted_footprint)
    max_y = max(point[1] for point in lifted_footprint)

    # 外接圆固定以 base_link 原点为圆心。多边形内部任意点到原点的
    # 最大距离一定出现在某个顶点，所以只需遍历所有轮廓顶点。
    return {
        "rack_placement": placement,
        "rack_rectangle": rack_rectangle,
        "lifted_footprint": lifted_footprint,
        "circumscribed_radius_m": max(math.hypot(*point) for point in lifted_footprint),
        "footprint_length_x_m": max_x - min_x,
        "footprint_width_y_m": max_y - min_y,
        "_base_footprint": list(base_polygon),   # 保留原始 footprint 供绘图
    }


def parse_footprint(text: str) -> Sequence[Sequence[float]]:
    """将命令行中的 '[[x1,y1], ...]' 字符串安全解析为 Python 列表。"""
    value = ast.literal_eval(text)
    if not isinstance(value, (list, tuple)):
        raise ValueError("base footprint must look like [[x1,y1],[x2,y2],...]")
    return value


def rounded(value):
    """递归将输出浮点数保留到 6 位小数，使 JSON 更容易阅读和复制。"""
    if isinstance(value, float):
        return round(value, 6)
    if isinstance(value, tuple):
        return [rounded(item) for item in value]
    if isinstance(value, list):
        return [rounded(item) for item in value]
    if isinstance(value, dict):
        return {key: rounded(item) for key, item in value.items()}
    return value


def draw_footprint_plot(result: dict, align_mode: str, back_depth: float,
                        length: float, width: float) -> None:
    """用 matplotlib 绘制 footprint、货架、外接圆示意图，在独立窗口显示。"""
    if not _HAS_MPL:
        print("\n  [!] matplotlib 未安装，无法生成图片。")
        print("  安装方法: pip install matplotlib")
        return

    base_fp = result["_base_footprint"]
    rack_rect = result["rack_rectangle"]
    lifted_fp = result["lifted_footprint"]
    radius = result["circumscribed_radius_m"]
    mp = result["rack_placement"]

    fig, ax = plt.subplots(figsize=(11, 9))
    fig.canvas.manager.set_window_title("顶升货架 Footprint 计算")

    # ---- 原点十字与基准线 ----
    ax.axhline(0, color='#999999', linewidth=0.6, linestyle='-', alpha=0.5)
    ax.axvline(0, color='#999999', linewidth=0.6, linestyle='-', alpha=0.5)

    # ---- 1) 机器人原始 footprint（蓝色填充） ----
    bx = [p[0] for p in base_fp] + [base_fp[0][0]]
    by = [p[1] for p in base_fp] + [base_fp[0][1]]
    ax.fill(bx, by, alpha=0.25, color='#42A5F5', edgecolor='#1565C0',
            linewidth=2, label='机器人 Footprint', zorder=2)

    # ---- 2) 货架矩形（橙色填充） ----
    rx = [p[0] for p in rack_rect] + [rack_rect[0][0]]
    ry = [p[1] for p in rack_rect] + [rack_rect[0][1]]
    ax.fill(rx, ry, alpha=0.30, color='#FFA726', edgecolor='#E65100',
            linewidth=2, linestyle='--', label='货架', zorder=3)

    # ---- 3) 合并轮廓（绿色粗线） ----
    lx = [p[0] for p in lifted_fp] + [lifted_fp[0][0]]
    ly = [p[1] for p in lifted_fp] + [lifted_fp[0][1]]
    ax.plot(lx, ly, color='#2E7D32', linewidth=2.5, label='合并轮廓 (lifted)', zorder=4)

    # ---- 4) 外接圆（红色虚线） ----
    circle = plt.Circle((0, 0), radius, fill=False, color='#D32F2F',
                        linewidth=2, linestyle=':', zorder=5,
                        label=f'外接圆 r={radius:.4f} m')
    ax.add_patch(circle)

    # ---- 5) 关键标注 ----
    # 原点
    ax.plot(0, 0, 'X', color='#B71C1C', markersize=12, markeredgewidth=1.5,
            zorder=6, label='base_link 原点')

    # 货架中心
    cx = mp["center_x_m"]
    ax.plot(cx, 0, 'o', color='#E65100', markersize=8, zorder=6)
    ax.annotate(f'货架中心\n({cx:.3f}, 0.000)', (cx, 0),
                textcoords="offset points", xytext=(10, 18),
                fontsize=9, color='#BF360C',
                arrowprops=dict(arrowstyle='->', color='#BF360C', lw=1.2))

    # 半径参考线（画一个代表性的顶点到原点的连线）
    # 找离原点最远的 lifted_footprint 顶点
    farthest = max(lifted_fp, key=lambda pt: math.hypot(pt[0], pt[1]))
    ax.plot([0, farthest[0]], [0, farthest[1]], color='#D32F2F', linewidth=1, alpha=0.55,
            linestyle='-', zorder=5)
    mid_rx, mid_ry = farthest[0] / 2, farthest[1] / 2
    ax.annotate(f'r={radius:.4f}', (mid_rx, mid_ry + 0.03),
                fontsize=9, color='#B71C1C', ha='center', va='bottom',
                bbox=dict(boxstyle='round,pad=0.2', fc='white', ec='#D32F2F', alpha=0.8))

    # ---- 6) 图形美化 ----
    ax.set_aspect('equal')
    ax.grid(True, alpha=0.25, linestyle=':', color='#666666')
    ax.set_xlabel('X (m) — 前方 +', fontsize=11)
    ax.set_ylabel('Y (m) — 左侧 +', fontsize=11)

    mode_label = "居中" if align_mode == "center" else f"尾部对齐 (back_depth={back_depth:.3f} m)"
    ax.set_title(f'顶升货架 Footprint 计算\n'
                 f'货架: {length:.3f} × {width:.3f} m | {mode_label} | '
                 f'外接圆半径: {radius:.4f} m',
                 fontsize=13, fontweight='bold', pad=15)

    ax.legend(loc='upper left', fontsize=9, framealpha=0.85)

    # 自适应边距
    margin = max(radius * 0.18, 0.3)
    ax.set_xlim(-radius - margin, radius + margin)
    ax.set_ylim(-radius - margin, radius + margin)

    plt.tight_layout()
    plt.show()


def interactive_mode() -> None:
    """交互模式：选择对齐方式 → 输入尺寸 → 展示结果并保持窗口打开。"""
    print("=" * 58)
    print("  顶升货架 Footprint & 外接圆半径计算器")
    print("=" * 58)
    print()
    print("  货架相对于机器人的放置方式：")
    print("    [1] 居中 — 货架中心对齐机器人 base_link 原点")
    print("    [2] 尾部对齐 — 货架前沿从机器人尾部向前伸出")
    print()
    print("-" * 58)

    # ---- 选择对齐方式 ----
    while True:
        choice = input("  请选择 (1 或 2) [默认 1]: ").strip()
        if choice == "" or choice == "1":
            align_mode = "center"
            back_depth = 0.0
            print("  → 已选择：居中")
            break
        elif choice == "2":
            align_mode = "rear"
            print("  → 已选择：尾部对齐")
            break
        else:
            print("  [!] 请输入 1 或 2")

    print()
    print("-" * 58)

    # ---- 尾部对齐时额外输入 back_depth ----
    if align_mode == "rear":
        robot_rear = min(p[0] for p in BASE_FOOTPRINT)
        print(f"  机器人尾端坐标: {robot_rear:.4f} m")
        print(f"  机械限位 (front_limit_x): {FRONT_LIMIT_X_M:.4f} m")
        print()
        while True:
            try:
                raw = input(f"  请输入货架前沿距机器人尾端的距离 back_depth (m) [默认 0.8]: ").strip()
                if raw == "":
                    back_depth = 0.8
                else:
                    back_depth = float(raw)
                if back_depth <= 0:
                    print("  [!] 必须为正数，请重新输入")
                    continue
                break
            except ValueError:
                print("  [!] 格式错误，请输入数字")
        print()
        print("-" * 58)

    # ---- 通用：提示输入长宽 ----
    def prompt_float(prompt_text: str, default: float) -> float:
        while True:
            try:
                raw = input(f"  {prompt_text} (m) [默认 {default}]: ").strip()
                if raw == "":
                    return default
                val = float(raw)
                if val <= 0:
                    print("  [!] 必须为正数，请重新输入")
                    continue
                return val
            except ValueError:
                print("  [!] 格式错误，请输入数字")

    length = prompt_float("请输入货架长度 (x方向)", RACK_LENGTH_M)
    width = prompt_float("请输入货架宽度 (y方向)", RACK_WIDTH_M)
    print()
    print("-" * 58)
    print("  计算中...")
    print()

    result = calculate(
        BASE_FOOTPRINT,
        length,
        width,
        back_depth,
        FRONT_LIMIT_X_M,
        CENTER_TO_REAR_M,
    )

    # 友好输出（非 JSON）
    mode_label = "居中" if align_mode == "center" else f"尾部对齐 (back_depth={back_depth:.3f}m)"
    print(f"  对齐方式: {mode_label}")
    print(f"  货架尺寸: {length:.3f} x {width:.3f} m")
    print()
    mp = result["rack_placement"]
    print("  ┌─ 货架位置 ─────────────────────────────────┐")
    print(f"  │  中心 x: {mp['center_x_m']:>8.4f} m                       │")
    print(f"  │  前沿 x: {mp['front_x_m']:>8.4f} m                       │")
    print(f"  │  后沿 x: {mp['rear_x_m']:>8.4f} m                       │")
    print("  └──────────────────────────────────────────────┘")
    print()
    print(f"  货架外接圆半径:    {result['circumscribed_radius_m']:.4f} m")
    print(f"  合并轮廓 x 向长度: {result['footprint_length_x_m']:.4f} m")
    print(f"  合并轮廓 y 向宽度: {result['footprint_width_y_m']:.4f} m")
    print()
    print("  ┌─ 合并轮廓顶点 (lifted_footprint) ──────────┐")
    for i, (x, y) in enumerate(result["lifted_footprint"]):
        print(f"  │  [{i:>2}]  ({x:>7.4f}, {y:>7.4f})                  │")
    print("  └──────────────────────────────────────────────┘")
    print()
    print("-" * 58)
    print("  计算完成。复制下方 JSON 供代码使用：")
    print("-" * 58)
    print(json.dumps(rounded(result), indent=2, ensure_ascii=False))
    print()
    print("  正在生成示意图，请查看弹出的窗口...")
    draw_footprint_plot(result, align_mode, back_depth, length, width)
    input("按 Enter 键退出...")


def main() -> None:
    """解析命令行参数、执行计算并打印 JSON。"""
    # 检查是否为双击启动（无任何命令行参数）
    import sys as _sys
    if len(_sys.argv) == 1:
        interactive_mode()
        return

    parser = argparse.ArgumentParser(
        description="无需 ROS，计算顶升货架后的 footprint 和外接圆半径。"
    )
    parser.add_argument(
        "--base-footprint",
        default=repr(BASE_FOOTPRINT),
        help="机器人原始 footprint，例如 '[[0.46,0.266],[-0.46,0.266],...]'",
    )
    parser.add_argument(
        "--rack-length",
        type=float,
        default=RACK_LENGTH_M,
        help="货架沿 x 方向的长度，单位 m",
    )
    parser.add_argument(
        "--rack-width",
        type=float,
        default=RACK_WIDTH_M,
        help="货架沿 y 方向的宽度，单位 m",
    )
    parser.add_argument(
        "--back-depth",
        type=float,
        default=BACK_DEPTH_M,
        help="机器人尾部参考位置到货架前沿的距离，单位 m",
    )
    parser.add_argument(
        "--front-limit-x",
        type=float,
        default=FRONT_LIMIT_X_M,
        help="货架前沿允许到达的最大 x 坐标，单位 m",
    )
    parser.add_argument(
        "--center-to-rear",
        type=float,
        default=CENTER_TO_REAR_M,
        help="机器人中心到尾部外沿的距离；0 表示从 footprint 自动计算",
    )
    parser.add_argument(
        "--plot",
        action="store_true",
        help="计算完成后弹出 matplotlib 示意图（需要安装 matplotlib）",
    )
    args = parser.parse_args()

    result = calculate(
        parse_footprint(args.base_footprint),
        args.rack_length,
        args.rack_width,
        args.back_depth,
        args.front_limit_x,
        args.center_to_rear,
    )
    print(json.dumps(rounded(result), indent=2, ensure_ascii=False))

    if args.plot:
        # 命令行模式下推断对齐方式
        _mode = "rear" if args.back_depth > args.rack_width * 0.01 else "center"
        draw_footprint_plot(result, _mode, args.back_depth,
                            args.rack_length, args.rack_width)


if __name__ == "__main__":
    main()

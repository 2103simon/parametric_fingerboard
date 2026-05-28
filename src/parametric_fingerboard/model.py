from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cadquery as cq
from cadquery import exporters

FINGER_ORDER = ("index", "middle", "ring", "pinky")


@dataclass(slots=True)
class SideParameters:
    edge_depth: float = 20.0
    hand_span: float = 68.0
    index_middle: float = 0.0
    middle_ring: float = 0.0
    ring_pinky: float = 0.0
    edge_rounding: float = 2.5


@dataclass(slots=True)
class FingerboardParameters:
    left: SideParameters
    right: SideParameters
    board_width_scale: float = 1.0
    wall_thickness: float = 3.0
    outer_wall_thickness: float = 10.0
    x_margin: float = 8.0
    y_margin: float = 6.0
    fixed_x_space: float = 10.0
    center_bulk: float = 10.0
    height_margin: float = 10.0
    min_board_length: float = 110.0
    min_board_width: float = 46.0
    min_board_height: float = 34.0
    cord_hole_diameter: float = 8.0


@dataclass(slots=True)
class PreparedFingerboard:
    board_length: float
    board_width: float
    board_height: float
    left_finger_depths: list[float]
    right_finger_depths: list[float]


def _slot_centers_x(side: SideParameters) -> list[float]:
    segment = side.hand_span / 3.0
    return [-1.5 * segment, -0.5 * segment, 0.5 * segment, 1.5 * segment]


def _plateaus(side: SideParameters) -> list[float]:
    # User deltas are treated as magnitudes and converted into cumulative plateaus:
    # 1) pinky is baseline 0
    # 2) ring = pinky + |ring_pinky|
    # 3) middle = ring + |middle_ring|
    # 4) index = middle - |index_middle|
    # If index would be negative, all plateaus are shifted up uniformly so that
    # index is exactly 0 while preserving relative finger-to-finger deltas.
    index_middle_delta = abs(side.index_middle)
    middle_ring_delta = abs(side.middle_ring)
    ring_pinky_delta = abs(side.ring_pinky)

    pinky = 0.0
    ring = pinky + ring_pinky_delta
    middle = ring + middle_ring_delta
    index = middle - index_middle_delta

    if index < 0.0:
        shift = -index
        index += shift
        middle += shift
        ring += shift
        pinky += shift

    return [index, middle, ring, pinky]


def _side_span_x(side: SideParameters) -> float:
    return side.hand_span


def _max_pocket_height_side(side: SideParameters) -> float:
    return side.hand_span / 3.0


def _finger_depths(side: SideParameters) -> list[float]:
    base = side.edge_depth
    plateaus = _plateaus(side)
    max_plateau = max(plateaus)
    # Pinky is the deepest cut. Higher plateaus reduce the cut depth and leave
    # more material behind, which creates the visible stair steps.
    return [base + (max_plateau - p) for p in plateaus]


def _prepare_fingerboard(params: FingerboardParameters) -> PreparedFingerboard:
    if params.board_width_scale <= 0:
        raise ValueError("board_width_scale must be > 0")

    required_length = max(_side_span_x(params.left), _side_span_x(params.right))
    required_length += (2.0 * params.x_margin) + params.fixed_x_space

    left_finger_depths = _finger_depths(params.left)
    right_finger_depths = _finger_depths(params.right)
    max_side_depth = max(max(left_finger_depths), max(right_finger_depths))
    required_scaled_width = (
        (2.0 * max_side_depth)
        + (2.0 * params.y_margin)
        + params.center_bulk
        + (2.0 * params.outer_wall_thickness)
    )

    # board_width is the pre-scale dimension. Grow it so that the final scaled width
    # always fits the deepest stair values plus margins and center bulk.
    required_unscaled_width = required_scaled_width / params.board_width_scale
    board_length = max(params.min_board_length, required_length)
    board_width = max(params.min_board_width, required_unscaled_width)

    required_height = max(_max_pocket_height_side(params.left), _max_pocket_height_side(params.right))
    required_height += params.height_margin
    board_height = max(params.min_board_height, required_height)

    scaled_width = board_width * params.board_width_scale
    max_depth = (
        (scaled_width - params.center_bulk) / 2.0
        - params.y_margin
        - params.outer_wall_thickness
    )

    for side_name, side, finger_depths in (
        ("left", params.left, left_finger_depths),
        ("right", params.right, right_finger_depths),
    ):
        if side.edge_depth <= 8:
            raise ValueError(f"{side_name}.edge_depth must be > 8 mm")
        if side.edge_depth > max_depth:
            raise ValueError(
                f"{side_name}.edge_depth must be <= {max_depth:.1f} mm for current board width"
            )
        if side.hand_span < 45:
            raise ValueError(f"{side_name}.hand_span must be >= 45 mm")
        if side.edge_rounding < 0:
            raise ValueError(f"{side_name}.edge_rounding must be >= 0 mm")

        for finger_name, finger_depth in zip(FINGER_ORDER, finger_depths):
            if finger_depth < 8:
                raise ValueError(
                    f"{side_name}.{finger_name} depth must be >= 8 mm"
                )
            if finger_depth > max_depth:
                raise ValueError(
                    f"{side_name}.{finger_name} depth must be <= {max_depth:.1f} mm"
                )

    if params.cord_hole_diameter > params.center_bulk - 2.0:
        raise ValueError("cord_hole_diameter must be at least 2 mm smaller than center_bulk")

    if params.cord_hole_diameter > board_height:
        raise ValueError(f"cord_hole_diameter must be <= board_height ({board_height:.1f} mm)")

    return PreparedFingerboard(
        board_length=board_length,
        board_width=board_width,
        board_height=board_height,
        left_finger_depths=left_finger_depths,
        right_finger_depths=right_finger_depths,
    )


def derive_dimensions(params: FingerboardParameters) -> tuple[float, float, float]:
    prepared = _prepare_fingerboard(params)
    return prepared.board_length, prepared.board_width, prepared.board_height


def _validate(params: FingerboardParameters) -> None:
    _prepare_fingerboard(params)


def build_fingerboard(
    params: FingerboardParameters,
    prepared: PreparedFingerboard | None = None,
) -> cq.Workplane:
    if prepared is None:
        prepared = _prepare_fingerboard(params)

    board_length = prepared.board_length
    board_width = prepared.board_width
    board_height = prepared.board_height
    scaled_width = board_width * params.board_width_scale

    body = cq.Workplane("XY").box(
        board_length,
        scaled_width,
        board_height,
        centered=(True, True, False),
    )

    # UI mapping: "Left Hand" controls left visual side and "Right Hand" right side.
    # Finger slot order is index -> middle -> ring -> pinky for both sides.
    for side_sign, side, finger_depths in (
        (-1.0, params.right, prepared.right_finger_depths),
        (1.0, params.left, prepared.left_finger_depths),
    ):
        centers_x = _slot_centers_x(side)
        slot_width = side.hand_span / 3.0

        # Keep the center-facing pocket wall fixed and grow depth toward the outer wall.
        inner_wall_abs = (params.center_bulk / 2.0) + params.y_margin
        for cx, pocket_depth in zip(centers_x, finger_depths):
            y_center = side_sign * (inner_wall_abs + pocket_depth / 2.0)
            pocket_height = slot_width
            z_center = board_height - (pocket_height / 2.0)

            pocket = (
                cq.Workplane("XY")
                .center(cx, y_center)
                .box(slot_width, pocket_depth, pocket_height, centered=(True, True, True))
                .translate((0.0, 0.0, z_center))
            )
            body = body.cut(pocket)

            # NOTE: Pocket edge rounding cutter was removed because it introduced
            # unintended internal holes in the finger boxes.

    # Single rope hole at the center of the ridge.
    hole_z = board_height / 2.0
    center_hole = (
        cq.Workplane("YZ")
        .center(0.0, hole_z)
        .circle(params.cord_hole_diameter / 2.0)
        .extrude((board_length / 2.0) + 2.0, both=True)
    )
    body = body.cut(center_hole)

    # Side labels: L and R as negative imprints on outer side faces.
    text_depth = max(1.2, min(2.0, params.outer_wall_thickness * 0.35))
    text_size = max(16.0, min(board_height * 0.60, board_length * 0.22))

    side_text_1 = body.faces(">Y").workplane(centerOption="CenterOfBoundBox").text(
        "L",
        text_size,
        -text_depth,
        combine=False,
        halign="center",
        valign="center",
    )
    side_text_2 = body.faces("<Y").workplane(centerOption="CenterOfBoundBox").text(
        "R",
        text_size,
        -text_depth,
        combine=False,
        halign="center",
        valign="center",
    )

    body = body.cut(side_text_1).cut(side_text_2)

    return body


def export_stl(
    params: FingerboardParameters,
    output_path: str | Path,
    tolerance: float = 0.15,
    shape: cq.Workplane | None = None,
    prepared: PreparedFingerboard | None = None,
) -> Path:
    if shape is None:
        shape = build_fingerboard(params, prepared=prepared)
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    exporters.export(shape, str(target), tolerance=tolerance)
    return target

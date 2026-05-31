"""
Fingerboard axis definitions (coordinate system):

- Length (X axis):
    The axis connecting the two sides with the engraved labels 'L' (left) and 'R' (right).
    This is the longest axis of the board, and the board is created with length along X in the CadQuery model.
    In the code: 'board_length'.

- Width (Y axis):
    The axis running perpendicular to the length, along the center hole (rope hole direction).
    This is the axis from the front to the back of the board, and is called 'board_width' in the code.
    The width is affected by hand_span and scaling parameters.

- Height (Z axis):
    The vertical axis, perpendicular to both length and width.
    This is the thickness of the board, and is called 'board_height' in the code.
    The height is the dimension you see from the tabletop up.

Summary:
    - Length: connects 'L' and 'R' labels (X)
    - Width: along the center hole (Y)
    - Height: vertical thickness (Z)

All geometric calculations and slot placements in this file follow this convention.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cadquery as cq
from cadquery import exporters

FINGER_ORDER = ("index", "middle", "ring", "pinky")


@dataclass(slots=True)
class SideParameters:
    index_middle: float = 0.0
    middle_ring: float = 0.0
    ring_pinky: float = 0.0


@dataclass(slots=True)
class FingerboardParameters:
    left: SideParameters
    right: SideParameters
    hand_span: float = 68.0
    edge_rounding: float = 2.5
    wall_thickness: float = 3.0
    side_margin: float = 8.0
    top_margin: float = 8.0
    # fixed_x_space: float = 10.0
    center_bulk: float = 10.0
    edge_depth: float = 20.0  # User-settable cutout height (was board_height minus bottom layer)
    # Advanced parameters
    bottom_layer_thickness: float = 5.0
    z_chamfer: float = 5.0
    top_bottom_chamfer: float = 2.0
    # min_board_length: float = 110.0
    # min_board_width: float = 46.0
    # min_board_height: float = 34.0
    cord_hole_diameter: float = 8.0




@dataclass(slots=True)
class PreparedFingerboard:
    board_length: float
    board_width: float
    board_height: float
    left_outer_reach: float
    right_outer_reach: float
    left_finger_depths: list[float]
    right_finger_depths: list[float]


def _slot_centers_x(hand_span: float) -> list[float]:
    segment = hand_span / 3.0
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


def _side_span_x(hand_span: float) -> float:
    return hand_span


# def _max_pocket_height_side(hand_span: float) -> float:
#     return hand_span / 3.0


def _finger_depths(hand_span: float, side: SideParameters) -> list[float]:
    base = hand_span / 2.0
    plateaus = _plateaus(side)
    max_plateau = max(plateaus)
    # Pinky is the deepest cut. Higher plateaus reduce the cut depth and leave
    # more material behind, which creates the visible stair steps.
    return [base + (max_plateau - p) for p in plateaus]


def _prepare_fingerboard(params: FingerboardParameters) -> PreparedFingerboard:
    if params.edge_rounding < 0:
        raise ValueError("edge_rounding must be >= 0 mm")

    # Reserve full side_margin on each side (total 2x)
    required_length = _side_span_x(params.hand_span)
    required_length += (2.0 * params.side_margin)

    left_finger_depths = _finger_depths(params.hand_span, params.left)
    right_finger_depths = _finger_depths(params.hand_span, params.right)
    left_max_depth = max(left_finger_depths)
    right_max_depth = max(right_finger_depths)
    # Both sides get full top_margin on each side (total 2x)
    left_required_reach = (
        (params.center_bulk / 2.0)
        + left_max_depth
        + params.top_margin
    )
    right_required_reach = (
        (params.center_bulk / 2.0)
        + right_max_depth
        + params.top_margin
    )
    required_scaled_width = (
        left_required_reach
        + right_required_reach
    )

    # board_width is the pre-scale dimension. Grow it so that the final scaled width
    # always fits the deepest stair values plus margins and center bulk.
    board_length = required_length
    board_width = required_scaled_width
    left_outer_reach = left_required_reach
    right_outer_reach = right_required_reach

    # New logic: board height is bottom_layer_thickness + user edge_depth
    board_height = params.bottom_layer_thickness + params.edge_depth

    for side_name, side, finger_depths in (
        ("left", params.left, left_finger_depths),
        ("right", params.right, right_finger_depths),
    ):
        for finger_name, finger_depth in zip(FINGER_ORDER, finger_depths):
            if finger_depth < 8:
                raise ValueError(
                    f"{side_name}.{finger_name} depth must be >= 8 mm"
                )

    if params.cord_hole_diameter > params.center_bulk - 2.0:
        raise ValueError("cord_hole_diameter must be at least 2 mm smaller than center_bulk")

    if params.cord_hole_diameter > board_height:
        raise ValueError(f"cord_hole_diameter must be <= board_height ({board_height:.1f} mm)")

    return PreparedFingerboard(
        board_length=board_length,
        board_width=board_width,
        board_height=board_height,
        left_outer_reach=left_outer_reach,
        right_outer_reach=right_outer_reach,
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
) -> tuple[cq.Workplane, str | None]:
    if prepared is None:
        prepared = _prepare_fingerboard(params)

    board_length = prepared.board_length
    board_width = prepared.board_width
    board_height = prepared.board_height
    body_center_y = (prepared.left_outer_reach - prepared.right_outer_reach) / 2.0

    # --- Calculate max safe z chamfer ---
    min_dist = float('inf')
    n_slots = 4
    slot_width = params.hand_span / n_slots
    left_edge = -0.5 * params.hand_span
    for side_sign, side, finger_depths in (
        (-1.0, params.right, prepared.right_finger_depths),
        (1.0, params.left, prepared.left_finger_depths),
    ):
        centers_x = [left_edge + (i + 0.5) * slot_width for i in range(n_slots)]
        inner_wall_abs = (params.center_bulk / 2.0)
        for cx, pocket_depth in zip(centers_x, finger_depths):
            y_center = side_sign * (inner_wall_abs + pocket_depth / 2.0)
            dist_x1 = abs((board_length / 2.0) - abs(cx + slot_width / 2.0))
            dist_x2 = abs((board_length / 2.0) - abs(cx - slot_width / 2.0))
            dist_y1 = abs((board_width / 2.0) - abs(y_center + pocket_depth / 2.0))
            dist_y2 = abs((board_width / 2.0) - abs(y_center - pocket_depth / 2.0))
            min_dist = min(min_dist, dist_x1, dist_x2, dist_y1, dist_y2)
    margin = min_dist / 10.0
    max_z_chamfer = max(0.0, min_dist - margin)
    warning = None
    z_chamfer = params.z_chamfer
    if z_chamfer > max_z_chamfer:
        z_chamfer = max_z_chamfer
        warning = (
            f"z_chamfer too large and would cut into the fingerbox. "
            f"Clamped to {max_z_chamfer:.2f} mm (margin {margin:.2f} mm)."
        )

    body = cq.Workplane("XY").box(
        board_length,
        board_width,
        board_height,
        centered=(True, True, False),
    ).translate((0.0, body_center_y, 0.0))
    # Apply z_chamfer to all vertical (|Z) edges if nonzero
    if z_chamfer > 0:
        body = body.edges("|Z").chamfer(z_chamfer)

    # Apply top_bottom_chamfer only to the outer perimeter edges of the top and bottom faces if nonzero
    if params.top_bottom_chamfer > 0:
        body = body.faces(">Z").wires().toPending().edges().chamfer(params.top_bottom_chamfer)
        body = body.faces("<Z").wires().toPending().edges().chamfer(params.top_bottom_chamfer)

    # UI mapping: "Left Hand" controls left visual side and "Right Hand" right side.
    # Finger slot order is index -> middle -> ring -> pinky for both sides.
    for side_sign, side, finger_depths in (
        (-1.0, params.right, prepared.right_finger_depths),
        (1.0, params.left, prepared.left_finger_depths),
    ):
        # The fingerbox region is exactly hand_span wide, centered on the board
        n_slots = 4
        slot_width = params.hand_span / n_slots
        left_edge = -0.5 * params.hand_span
        centers_x = [left_edge + (i + 0.5) * slot_width for i in range(n_slots)]

        # Center-facing pocket wall: only center_bulk applies, not margin
        inner_wall_abs = (params.center_bulk / 2.0)


        for cx, pocket_depth in zip(centers_x, finger_depths):
            y_center = side_sign * (inner_wall_abs + pocket_depth / 2.0)
            pocket_width = slot_width
            pocket_depth_val = pocket_depth
            pocket_height = params.edge_depth
            z_center = params.bottom_layer_thickness + pocket_height / 2.0

            pocket = (
                cq.Workplane("XY")
                .center(cx, y_center)
                .box(pocket_width, pocket_depth_val, pocket_height, centered=(True, True, True))
                .translate((0.0, 0.0, z_center))
            )
            body = body.cut(pocket)

            # NOTE: Pocket edge rounding cutter was removed because it introduced
            # unintended internal holes in the finger boxes.

    # Single rope hole at the center of the ridge.
    hole_z = board_height / 2.0
    hole_radius = params.cord_hole_diameter / 2.0
    center_hole = (
        cq.Workplane("YZ")
        .center(0.0, hole_z)
        .circle(hole_radius)
        .extrude((board_length / 2.0) + 2.0, both=True)
    )
    body = body.cut(center_hole)

    positive_end_groove = (
        cq.Workplane("XZ")
        .center(board_length / 2.0, hole_z)
        .circle(hole_radius)
        .extrude((board_width / 2.0) + 2.0, both=True)
    )
    negative_end_groove = (
        cq.Workplane("XZ")
        .center(-(board_length / 2.0), hole_z)
        .circle(hole_radius)
        .extrude((board_width / 2.0) + 2.0, both=True)
    )
    body = body.cut(positive_end_groove).cut(negative_end_groove)

    # Side labels: L and R as negative imprints on outer side faces.
    text_depth = 1.2  # Fixed value since outer_wall_thickness is removed
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

    return body, warning


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
    exporters.export(shape, str(target), tolerance=tolerance)  # File type can also be 3mf. TODO make export type selectable (as well as tolerances?) 
    return target

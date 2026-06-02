"""
Model definitions and geometry generation for the parametric fingerboard application.

Contains:
- Data classes for parameter storage
- Geometry preparation and validation logic
- 3D model construction using CadQuery
- STL export functionality

Coordinate system:
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
from typing import Literal

import cadquery as cq
from cadquery import exporters

FINGER_ORDER = ("index", "middle", "ring", "pinky")
ExportType = Literal["STL", "STEP", "AMF", "SVG", "TJS", "DXF", "VRML", "VTP", "3MF", "BREP", "BIN"]


@dataclass(slots=True)
class SideParameters:
    """
    Stores finger delta parameters for one hand side (left or right).

    Attributes:
        index_middle (float): Delta between index and middle finger.
        middle_ring (float): Delta between middle and ring finger.
        ring_pinky (float): Delta between ring and pinky finger.
    """
    index_middle: float = 0.0
    middle_ring: float = 0.0
    ring_pinky: float = 0.0


@dataclass(slots=True)
class FingerboardParameters:
    """
    Stores all user-configurable parameters for the fingerboard.

    Attributes:
        left (SideParameters): Parameters for the left hand.
        right (SideParameters): Parameters for the right hand.
        hand_span (float): Total span between index and pinky fingers.
        edge_rounding (float): Rounding radius for board edges.
        side_margin (float): Margin at the board sides.
        top_margin (float): Margin at the board top/bottom.
        center_bulk (float): Width of the central bulk region.
        edge_depth (float): Height of the finger cutouts.
        bottom_layer_thickness (float): Thickness of the bottom layer.
        side_chamfer (float): Chamfer size for vertical edges.
        top_bottom_chamfer (float): Chamfer size for top/bottom edges.
        cord_hole_diameter (float): Diameter of the cord hole.
    """
    left: SideParameters
    right: SideParameters
    hand_span: float = 68.0
    edge_rounding: float = 2.5
    side_margin: float = 8.0
    top_margin: float = 8.0
    center_bulk: float = 15.0
    edge_depth: float = 20.0
    # Advanced parameters
    bottom_layer_thickness: float = 5.0
    side_chamfer: float = 5.0
    top_bottom_chamfer: float = 2.0
    cord_hole_diameter: float = 8.0




@dataclass(slots=True)
class PreparedFingerboard:
    """
    Stores precomputed geometric values for a fingerboard, used to avoid redundant calculations.

    Attributes:
        board_length (float): Total length of the board.
        board_width (float): Total width of the board.
        board_height (float): Total height of the board.
        left_outer_reach (float): Reach of the left hand side.
        right_outer_reach (float): Reach of the right hand side.
        left_finger_depths (list[float]): List of finger cut depths for the left side.
        right_finger_depths (list[float]): List of finger cut depths for the right side.
    """
    board_length: float
    board_width: float
    board_height: float
    left_outer_reach: float
    right_outer_reach: float
    left_finger_depths: list[float]
    right_finger_depths: list[float]


def _plateaus(side: SideParameters) -> list[float]:
    """
    Computes the cumulative finger plateau heights for a hand side.

    Algorithm:
        1. Pinky is baseline 0
        2. Ring = pinky + |ring_pinky|
        3. Middle = ring + |middle_ring|
        4. Index = middle - |index_middle|
        If index would be negative, all plateaus are shifted up uniformly so that
        index is exactly 0 while preserving relative finger-to-finger deltas.

    Args:
        side (SideParameters): The finger deltas for one hand side.

    Returns:
        list[float]: Plateau heights for [index, middle, ring, pinky], always non-negative for index.
    """
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
    """
    Returns the hand span, which is the required length of the fingerbox region (the area spanned by the fingers),
    not including margins or other board features.

    Args:
        hand_span (float): The span between index and pinky fingers.

    Returns:
        float: The fingerbox region length (not including margins).
    """
    return hand_span


def _finger_depths(hand_span: float, side: SideParameters) -> list[float]:
    """
    Calculates the finger cut depths for a hand side, based on hand span and plateau heights.

    Args:
        hand_span (float): The span between index and pinky fingers.
        side (SideParameters): The finger deltas for one hand side.

    Returns:
        list[float]: List of depths for [index, middle, ring, pinky].
    """
    base = hand_span / 2.0
    plateaus = _plateaus(side)
    max_plateau = max(plateaus)
    return [base + (max_plateau - p) for p in plateaus]


def _prepare_fingerboard(params: FingerboardParameters) -> PreparedFingerboard:
    """
    Validates the provided fingerboard parameters and computes all geometric values required to build the fingerboard.

    This function checks the validity of all user-supplied parameters (e.g., margins, chamfers, hole diameters, finger depths),
    computes the required board length and width (including margins and bulk), and determines the finger cut depths for both sides.
    It returns a PreparedFingerboard dataclass containing all precomputed dimensions and lists of finger depths for further geometry generation.

    Args:
        params: FingerboardParameters
            The user-supplied parameters for the fingerboard, including hand span, margins, chamfers, and finger deltas for both sides.

    Returns:
        PreparedFingerboard: A dataclass containing all validated and precomputed geometric values needed for model construction.

    Raises:
        ValueError: If any parameter is invalid (e.g., negative edge rounding, finger depths < 8 mm, cord hole diameter too large).
    """
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

    board_length = required_length
    board_width = required_scaled_width
    left_outer_reach = left_required_reach
    right_outer_reach = right_required_reach

    # board height is bottom_layer_thickness + user edge_depth
    board_height = params.bottom_layer_thickness + params.edge_depth

    for side_name, _, finger_depths in (
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
    """
    Computes and returns the (length, width, height) of the fingerboard for the given parameters.

    Args:
        params (FingerboardParameters): The user-supplied parameters for the fingerboard.

    Returns:
        tuple[float, float, float]: The (length, width, height) of the fingerboard.
    """
    prepared = _prepare_fingerboard(params)
    return prepared.board_length, prepared.board_width, prepared.board_height


def build_fingerboard(
    params: FingerboardParameters,
    prepared: PreparedFingerboard | None = None,
) -> tuple[cq.Workplane, str | None]:
    """
    Constructs the 3D fingerboard model using CadQuery based on the provided parameters and precomputed geometry.

    This function builds the full parametric fingerboard, including:
      - The main board body (with correct length, width, and height)
      - Chamfers on vertical and horizontal edges, clamped to safe values if needed
      - Finger slots for both hands, with depths and positions determined by user parameters
      - Central rope hole and grooves at both ends
      - Negative imprints of 'L' and 'R' labels on the board sides
    All geometry is constructed in the CadQuery XY plane, with the board's length along X, width along Y, and height along Z.

    Args:
        params: FingerboardParameters
            The user-supplied parameters for the fingerboard, including all geometry and feature options.
        prepared: PreparedFingerboard, optional
            Precomputed geometry values. If None, will be computed from params.

    Returns:
        tuple[cq.Workplane, str | None]:
            - The CadQuery Workplane object representing the final board geometry.
            - A warning string if any parameters (e.g., chamfers) were clamped for safety, else None.

    Raises:
        ValueError: If the parameters are invalid (see _prepare_fingerboard for details).

    Modeling Steps:
        1. Validate and prepare all geometry values (dimensions, finger depths, margins, chamfers).
        2. Create the main board body as a box, centered in XY, with height from the table up.
        3. Apply side chamfers to all vertical edges, clamping to safe values if needed.
        4. Apply top/bottom chamfers to the outer perimeter of the top and bottom faces, clamping as needed.
        5. For each hand side, cut finger slots at the correct positions and depths.
        6. Cut a central rope hole through the board and grooves at both ends.
        7. Add negative 'L' and 'R' labels as imprints on the outer side faces.
        8. Return the final CadQuery object and any warnings about parameter clamping.
    """
    if prepared is None:
        prepared = _prepare_fingerboard(params)

    board_length = prepared.board_length
    board_width = prepared.board_width
    board_height = prepared.board_height
    body_center_y = (prepared.left_outer_reach - prepared.right_outer_reach) / 2.0

    # --- Calculate max safe side chamfer based only on available margins ---
    # Chamfer size must only depend on geometric clearance margins, not board length/width.
    min_margin = min(params.top_margin, params.side_margin)
    side_tolerance = min_margin / 6.0
    max_side_chamfer = max(0.0, min_margin - side_tolerance)
    warning = None
    side_chamfer = params.side_chamfer
    if side_chamfer < 0:
        side_chamfer = 0.0
        warning = "side_chamfer cannot be negative. Clamped to 0.00 mm."
    elif side_chamfer > max_side_chamfer:
        side_chamfer = max_side_chamfer
        warning = (
            f"side_chamfer too large and would cut into the fingerbox. "
            f"Clamped to {max_side_chamfer:.2f} mm (tolerance {side_tolerance:.2f} mm)."
        )

    # --- Calculate max safe top/bottom chamfer based on margin to fingerbox ---
    # The chamfer must not bring the edge closer to the fingerbox than the minimum of top_margin or side_margin, minus a tolerance.
    tb_tolerance = min_margin / 6.0
    max_tb_chamfer = max(0.0, min_margin - tb_tolerance)
    tb_chamfer = params.top_bottom_chamfer
    tb_chamfer_clamped = False
    tb_warning = None
    # Clamp to [0, max_tb_chamfer]
    if tb_chamfer < 0:
        tb_chamfer = 0.0
        tb_chamfer_clamped = True
        tb_warning = (
            f"top/bottom chamfer cannot be negative. Clamped to 0.00 mm.")
    elif tb_chamfer > max_tb_chamfer:
        tb_chamfer = max_tb_chamfer
        tb_chamfer_clamped = True
        tb_warning = (
            f"top/bottom chamfer too large and would cut into the fingerbox. "
            f"Clamped to {max_tb_chamfer:.2f} mm (tolerance {tb_tolerance:.2f} mm)."
        )
    if tb_chamfer_clamped:
        if warning and tb_warning is not None:
            warning += " " + tb_warning
        else:
            warning = tb_warning

    body = cq.Workplane("XY").box(
        board_length,
        board_width,
        board_height,
        centered=(True, True, False),
    ).translate((0.0, body_center_y, 0.0))
    # Apply side_chamfer to all vertical (|Z) edges if nonzero
    if side_chamfer > 0:
        body = body.edges("|Z").chamfer(side_chamfer)

    # Apply top_bottom_chamfer only to the outer perimeter edges of the top and bottom faces if nonzero
    if tb_chamfer > 0:
        body = body.faces(">Z").wires().toPending().edges().chamfer(tb_chamfer)
        body = body.faces("<Z").wires().toPending().edges().chamfer(tb_chamfer)

    # UI mapping: "Left Hand" controls left visual side and "Right Hand" right side.
    # Finger slot order is index -> middle -> ring -> pinky for both sides.
    for side_sign, _, finger_depths in (
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
    text_depth = 1.2
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
    export_type: ExportType | None = None,
) -> Path:
    """
    Exports the fingerboard model using CadQuery exporters.

    Args:
        params (FingerboardParameters): Parameters for the fingerboard geometry.
        output_path (str | Path): Path to save the STL file.
        tolerance (float, optional): Export tolerance for mesh accuracy. Defaults to 0.15.
        shape (cq.Workplane, optional): Optional pre-built CadQuery shape. If None, the shape is built from params.
        prepared (PreparedFingerboard, optional): Optional precomputed geometry.
        export_type (str | None, optional): Explicit CadQuery export type (e.g. "STL", "3MF", "STEP").
            If None, CadQuery infers type from the file extension.

    Returns:
        Path: Path to the exported STL file.
    """
    if shape is None:
        shape, _ = build_fingerboard(params, prepared=prepared)
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    exporters.export(shape, str(target), exportType=export_type, tolerance=tolerance)
    return target

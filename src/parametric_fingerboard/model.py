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

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import cadquery as cq
from cadquery import exporters

FINGER_ORDER = ("index", "middle", "ring", "pinky")
CORD_HOLE_TOP_LAYER_CLEARANCE = 2.0
MIN_EFFECTIVE_CHAMFER = 0.001
FINGER_GROOVE_MAX_FACTOR = 10.0
# OCCT fails the second chamfer when the side bevel is too small to meet the
# top/bottom bevel at the corner. This is the observed geometric threshold.
SIDE_TOP_CHAMFER_MIN_RATIO = 2.0 - math.sqrt(2.0)
CHAMFER_INTERSECTION_CLEARANCE = 0.0001
ExportType = Literal["STL", "STEP", "AMF", "SVG", "TJS", "DXF", "VRML", "VTP", "3MF", "BREP", "BIN"]


def _format_chamfer_mm(value: float) -> str:
    return f"{value:.4f}".rstrip("0").rstrip(".")


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
        finger_groove_factor (float): Scaling factor for the finger sattle (groove) radius, relative to hand span.
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
    finger_groove_factor: float = 0.74




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


def _sanitize_center_bulk_and_cord(
    center_bulk: float,
    cord_hole_diameter: float,
    board_height: float,
    bulk_cord_preference: Literal["center_bulk", "cord_hole_diameter", "auto"] = "auto",
) -> tuple[float, float, list[str]]:
    """
    Clamps center bulk and cord hole diameter to a geometry-safe combination.

    Rules:
      - center_bulk must be >= 2.0 mm
      - cord_hole_diameter must be >= 0.0 mm
      - cord_hole_diameter must be <= center_bulk - 2.0 mm
      - cord_hole_diameter must be <= board_height

        Preference behavior:
            - center_bulk: prioritize keeping cord_hole_diameter and increase center_bulk when needed.
            - cord_hole_diameter: prioritize keeping center_bulk and decrease cord_hole_diameter when needed.
            - auto: same as cord_hole_diameter.

    Returns:
        tuple[float, float, list[str]]:
            (safe_center_bulk, safe_cord_hole_diameter, warning_messages)
    """
    warnings: list[str] = []

    safe_center_bulk = center_bulk
    if safe_center_bulk < 2.0:
        warnings.append(
            f"center_bulk too small for a safe cord channel. Clamped to 2.00 mm (was {center_bulk:.2f} mm)."
        )
        safe_center_bulk = 2.0

    safe_cord = cord_hole_diameter
    if safe_cord < 0.0:
        warnings.append(
            f"cord_hole_diameter cannot be negative. Clamped to 0.00 mm (was {cord_hole_diameter:.2f} mm)."
        )
        safe_cord = 0.0

    max_height_cord = max(0.0, board_height)

    preference = bulk_cord_preference
    if preference == "auto":
        preference = "cord_hole_diameter"

    if preference == "center_bulk":
        min_center_for_cord = safe_cord + 2.0
        if safe_center_bulk < min_center_for_cord:
            warnings.append(
                f"center_bulk too small for the requested cord hole. Clamped to {min_center_for_cord:.2f} mm so center_bulk >= cord_hole_diameter + 2.00 mm."
            )
            safe_center_bulk = min_center_for_cord
    else:
        max_cord_for_bulk = max(0.0, safe_center_bulk - 2.0)
        max_cord = min(max_cord_for_bulk, max_height_cord)
        if safe_cord > max_cord:
            warnings.append(
                f"cord_hole_diameter too large for the current bulk. Clamped to {max_cord:.2f} mm so cord_hole_diameter <= center_bulk - 2.00 mm."
            )
            safe_cord = max_cord

    if safe_cord > max_height_cord:
        warnings.append(
            f"cord_hole_diameter too large for current board_height. Clamped to {max_height_cord:.2f} mm so cord_hole_diameter <= board_height."
        )
        safe_cord = max_height_cord

    return safe_center_bulk, safe_cord, warnings


def _sanitize_finger_grooves(
    slot_width: float, 
    hand_span: float, 
    finger_groove_factor: float
) -> tuple[float, float, list[str]]:
    """
    Clamps finger groove parameters to a geometry-safe combination.

    Rules:
      - finger_groove_factor == 0 disables finger grooves
      - finger_groove_factor must result in a groove_cut_radius >= slot_width
      - finger_groove_factor is capped to avoid unstable large-radius CAD cuts
      - groove_cut_radius is calculated as hand_span * finger_groove_factor

    Returns:
        tuple[float, float, list[str]]:
            (safe_groove_cut_radius, safe_finger_groove_factor, warning_messages)
    """
    
    warnings: list[str] = []

    if not math.isfinite(finger_groove_factor):
        warnings.append(
            "finger_groove_factor must be a finite number. "
            f"Clamped to {FINGER_GROOVE_MAX_FACTOR:.2f} so the model can be created."
        )
        finger_groove_factor = FINGER_GROOVE_MAX_FACTOR

    if finger_groove_factor < 0.0:
        warnings.append(
            "finger_groove_factor cannot be negative. "
            "Clamped to 0.00 and finger grooves were disabled."
        )
        return 0.0, 0.0, warnings

    if finger_groove_factor == 0.0:
        return 0.0, 0.0, warnings
    
    safe_groove_cut_radius = hand_span * finger_groove_factor
    safe_finger_groove_factor = finger_groove_factor
    if safe_groove_cut_radius < slot_width:
        safe_finger_groove_factor = slot_width / hand_span
        warnings.append(
            f"finger_groove_factor is too small and results in groove_cut_radius {safe_groove_cut_radius:.2f} mm that is smaller than slot width {slot_width:.2f} mm. Clamped to {safe_finger_groove_factor:.2f} so groove_cut_radius >= slot_width."
        )
        safe_groove_cut_radius = slot_width
    if safe_finger_groove_factor > FINGER_GROOVE_MAX_FACTOR:
        safe_finger_groove_factor = FINGER_GROOVE_MAX_FACTOR
        safe_groove_cut_radius = hand_span * safe_finger_groove_factor
        warnings.append(
            f"finger_groove_factor too large for stable CAD geometry. "
            f"Clamped to {safe_finger_groove_factor:.2f} so the model can be created."
        )
    return safe_groove_cut_radius, safe_finger_groove_factor, warnings


def _sanitize_edge_rounding(edge_rounding: float, top_margin: float) -> tuple[float, list[str]]:
    """
    Clamps edge rounding parameters to a geometry-safe combination.

    Rules:
      - edge_rounding must not exceed half of the top_margin

    Returns:
        tuple[float, list[str]]:
            (safe_edge_rounding, warning_messages)
    """

    warnings: list[str] = []
    
    safe_edge_rounding = edge_rounding
    if edge_rounding > (top_margin / 2.0)*0.9:
        safe_edge_rounding = (top_margin / 2.0)*0.9
        warnings.append(
            f"edge_rounding too large and would cut into the top margin. Clamped to {safe_edge_rounding:.2f} mm so edge_rounding <= top_margin / 2."
        )
    
    return safe_edge_rounding, warnings


def _cord_hole_stair_center_z(
    bottom_layer_thickness: float,
    edge_depth: float,
    board_height: float,
    cord_hole_diameter: float,
) -> tuple[float, list[str]]:
    """
    Places the cord hole at the stair center while preserving top-layer material.

    The preferred center is halfway up the stair depth above the bottom layer:
    bottom_layer_thickness + edge_depth / 2.
    The top-layer clearance is measured from the top edge of the circular hole:
    hole_center_z + cord_hole_diameter / 2 <= board_height - clearance.
    """
    warnings: list[str] = []
    preferred_hole_z = bottom_layer_thickness + (edge_depth / 2.0)
    cord_hole_radius = cord_hole_diameter / 2.0
    max_hole_center_z = board_height - CORD_HOLE_TOP_LAYER_CLEARANCE - cord_hole_radius

    if preferred_hole_z > max_hole_center_z:
        warnings.append(
            f"cord hole placement too close to the top layer. "
            f"Lowered hole center to {max_hole_center_z:.2f} mm so the "
            f"{cord_hole_diameter:.2f} mm hole leaves at least "
            f"{CORD_HOLE_TOP_LAYER_CLEARANCE:.2f} mm of material above it."
        )
        return max_hole_center_z, warnings

    return preferred_hole_z, warnings


def _prepare_fingerboard(
    params: FingerboardParameters,
    bulk_cord_preference: Literal["center_bulk", "cord_hole_diameter", "auto"] = "auto",
) -> PreparedFingerboard:
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
        ValueError: If any parameter is invalid (e.g., negative edge rounding, finger depths < 8 mm).
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
    # board height is bottom_layer_thickness + user edge_depth
    board_height = params.bottom_layer_thickness + params.edge_depth

    safe_center_bulk, _, _ = _sanitize_center_bulk_and_cord(
        params.center_bulk,
        params.cord_hole_diameter,
        board_height,
        bulk_cord_preference=bulk_cord_preference,
    )

    # Both sides get full top_margin on each side (total 2x)
    left_required_reach = (
        (safe_center_bulk / 2.0)
        + left_max_depth
        + params.top_margin
    )
    right_required_reach = (
        (safe_center_bulk / 2.0)
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

    for side_name, _, finger_depths in (
        ("left", params.left, left_finger_depths),
        ("right", params.right, right_finger_depths),
    ):
        for finger_name, finger_depth in zip(FINGER_ORDER, finger_depths):
            if finger_depth < 8:
                raise ValueError(
                    f"{side_name}.{finger_name} depth must be >= 8 mm"
                )

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
    bulk_cord_preference: Literal["center_bulk", "cord_hole_diameter", "auto"] = "auto",
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
        prepared = _prepare_fingerboard(params, bulk_cord_preference=bulk_cord_preference)

    board_length = prepared.board_length
    board_width = prepared.board_width
    board_height = prepared.board_height
    body_center_y = (prepared.left_outer_reach - prepared.right_outer_reach) / 2.0

    # --- Calculate max safe side chamfer based only on available margins ---
    # Chamfer size must only depend on geometric clearance margins, not board length/width.
    min_margin = min(params.top_margin, params.side_margin)
    side_tolerance = min_margin / 6.0
    max_side_chamfer = max(0.0, min_margin - side_tolerance)
    warning_messages: list[str] = []
    side_chamfer = params.side_chamfer
    if side_chamfer < 0:
        side_chamfer = 0.0
        warning_messages.append("side_chamfer cannot be negative. Clamped to 0.00 mm.")
    elif side_chamfer > max_side_chamfer:
        side_chamfer = max_side_chamfer
        warning_messages.append(
            f"side_chamfer too large and would cut into the fingerbox. "
            f"Clamped to {max_side_chamfer:.2f} mm (tolerance {side_tolerance:.2f} mm)."
        )

    # --- Calculate max safe top/bottom chamfer based on margin to fingerbox ---
    # The chamfer must not bring the edge closer to the fingerbox than the minimum of top_margin or side_margin, minus a tolerance.
    tb_tolerance = min_margin / 6.0
    max_tb_chamfer = max(0.0, min_margin - tb_tolerance)
    tb_chamfer = params.top_bottom_chamfer
    # Clamp to [0, max_tb_chamfer]
    if tb_chamfer < 0:
        tb_chamfer = 0.0
        warning_messages.append("top/bottom chamfer cannot be negative. Clamped to 0.00 mm.")
    elif tb_chamfer > max_tb_chamfer:
        tb_chamfer = max_tb_chamfer
        warning_messages.append(
            f"top/bottom chamfer too large and would cut into the fingerbox. "
            f"Clamped to {max_tb_chamfer:.2f} mm (tolerance {tb_tolerance:.2f} mm)."
        )
    if 0.0 < tb_chamfer < MIN_EFFECTIVE_CHAMFER:
        if max_tb_chamfer >= MIN_EFFECTIVE_CHAMFER:
            tb_chamfer = MIN_EFFECTIVE_CHAMFER
            warning_messages.append(
                f"top/bottom chamfer too small for the CAD kernel. "
                f"Clamped to {_format_chamfer_mm(tb_chamfer)} mm so the model can be created."
            )
        else:
            tb_chamfer = 0.0
            warning_messages.append(
                f"top/bottom chamfer too small for the CAD kernel, and no positive top/bottom "
                f"chamfer fits the current margins. Clamped to 0.00 mm."
            )

    if side_chamfer > 0.0:
        min_side_chamfer = MIN_EFFECTIVE_CHAMFER
        min_side_chamfer_reason = "CAD kernel"
        if tb_chamfer > 0.0:
            min_side_for_top_bottom = (
                (tb_chamfer * SIDE_TOP_CHAMFER_MIN_RATIO)
                + CHAMFER_INTERSECTION_CLEARANCE
            )
            if min_side_for_top_bottom > min_side_chamfer:
                min_side_chamfer = min_side_for_top_bottom
                min_side_chamfer_reason = "active top/bottom chamfer"

        if side_chamfer < min_side_chamfer:
            if min_side_chamfer <= max_side_chamfer:
                side_chamfer = min_side_chamfer
                warning_messages.append(
                    f"side_chamfer too small for the {min_side_chamfer_reason}. "
                    f"Clamped to {_format_chamfer_mm(side_chamfer)} mm so the model can be created."
                )
            else:
                side_chamfer = 0.0
                warning_messages.append(
                    f"side_chamfer too small for the {min_side_chamfer_reason}, and no positive "
                    f"side chamfer fits the current margins. Clamped to 0.00 mm."
                )

    safe_center_bulk, safe_cord_hole_diameter, bulk_cord_warnings = _sanitize_center_bulk_and_cord(
        params.center_bulk,
        params.cord_hole_diameter,
        board_height,
        bulk_cord_preference=bulk_cord_preference,
    )
    warning_messages.extend(bulk_cord_warnings)

    body = cq.Workplane("XY").box(
        board_length,
        board_width,
        board_height,
        centered=(True, True, False),
    ).translate((0.0, body_center_y, 0.0))

    # let us prepare some parameters for the finger slots and grooves
    n_slots = 4
    slot_width = params.hand_span / n_slots
    
    safe_finger_groove_cut_radius, _, finger_groove_warnings = _sanitize_finger_grooves(slot_width, params.hand_span, params.finger_groove_factor)
    warning_messages.extend(finger_groove_warnings)
    finger_groove_enabled = safe_finger_groove_cut_radius > 0.0
    finger_groove_penetration = 2.0 if finger_groove_enabled else 0.0
    finger_groove_offset = safe_finger_groove_cut_radius - finger_groove_penetration
    
    fillet_radius, edge_rounding_warnings = _sanitize_edge_rounding(params.edge_rounding, params.top_margin)  # TODO sanitize fillet radius. Must be < params.top_margin
    warning_messages.extend(edge_rounding_warnings)
    fingerbox_rounding_regions: list[tuple[float, float, float, float]] = []

    # UI mapping: "Left Hand" controls left visual side and "Right Hand" right side.
    # Finger slot order is index -> middle -> ring -> pinky for both sides.
    for side_sign, _, finger_depths in (
        (-1.0, params.right, prepared.right_finger_depths),
        (1.0, params.left, prepared.left_finger_depths),
    ):
        # The fingerbox region is exactly hand_span wide, centered on the board
        left_edge = -0.5 * params.hand_span
        centers_x = [left_edge + (i + 0.5) * slot_width for i in range(n_slots)]

        # Center-facing pocket wall: only center_bulk applies, not margin
        inner_wall_abs = (safe_center_bulk / 2.0)


        for cx, pocket_depth in zip(centers_x, finger_depths):
            y_center = side_sign * (inner_wall_abs + pocket_depth / 2.0)
            pocket_width = slot_width
            pocket_height = params.edge_depth  # cut full depth minus sattle penetration for the groove
            z_center = params.bottom_layer_thickness + pocket_height / 2.0

            pocket = (
                cq.Workplane("XY")
                .center(cx, y_center)
                .box(
                    pocket_width, 
                    pocket_depth - finger_groove_penetration, 
                    pocket_height, 
                    centered=(True, True, True)
                )
                .translate((0.0, 0.0, z_center))
            )
            body = body.cut(pocket)
            
            if finger_groove_enabled:
                # Sattle for the fingers to rest on the stairs.
                groove_y = side_sign * (inner_wall_abs + pocket_depth - finger_groove_offset)
                groove_depth = params.edge_depth

                # Cylindrical groove cutter
                cutter = (
                    cq.Workplane("XY")
                    .center(cx, groove_y)
                    .circle(safe_finger_groove_cut_radius)
                    .extrude(groove_depth / 2.0, both=True)
                    .translate((0.0, 0.0, z_center))
                )

                # limiting box to only cut stairs
                groove_width = slot_width
                groove_length = 2 * finger_groove_penetration  # local region only
                box_y = side_sign * (inner_wall_abs + pocket_depth)
                # Limit region with a box
                limit_box = (
                    cq.Workplane("XY")
                    .center(cx, box_y)
                    .box(
                        groove_width,
                        groove_length,
                        groove_depth,
                        centered=(True, True, True)
                    )
                    .translate((0, 0, z_center))
                )
                fingerbox_rounding_regions.append((
                    cx - (groove_width / 2.0),
                    cx + (groove_width / 2.0),
                    min(box_y - (groove_length / 2.0), box_y + (groove_length / 2.0)),
                    max(box_y - (groove_length / 2.0), box_y + (groove_length / 2.0)),
                ))

                # Keep only intersecting region
                sattle = cutter.intersect(limit_box)

                body = body.cut(sattle)

    body_x_min = -(board_length / 2.0)
    body_x_max = board_length / 2.0
    body_y_min = body_center_y - (board_width / 2.0)
    body_y_max = body_center_y + (board_width / 2.0)
    outer_edge_tolerance = 1e-4

    def _near(value: float, target: float) -> bool:
        return abs(value - target) <= outer_edge_tolerance

    def _bbox_on_x_boundary(bbox) -> bool:
        return (
            (_near(bbox.xmin, body_x_min) and _near(bbox.xmax, body_x_min))
            or (_near(bbox.xmin, body_x_max) and _near(bbox.xmax, body_x_max))
        )

    def _bbox_on_y_boundary(bbox) -> bool:
        return (
            (_near(bbox.ymin, body_y_min) and _near(bbox.ymax, body_y_min))
            or (_near(bbox.ymin, body_y_max) and _near(bbox.ymax, body_y_max))
        )

    def _edge_rounding_candidates(requested_radius: float) -> list[float]:
        """Returns fallback radii for fragile CadQuery fillets."""
        if requested_radius <= 0:
            return [0.0]

        conservative_limits = [
            requested_radius,
            params.edge_depth * 0.85,
            max(0.0, params.top_margin - finger_groove_penetration) * 0.5,
            finger_groove_penetration * 0.75,
            finger_groove_penetration * 0.5,
            0.5,
            0.0,
        ]
        candidates: list[float] = []
        for limit in conservative_limits:
            candidate = max(0.0, min(requested_radius, limit))
            if not any(abs(candidate - existing) < 1e-9 for existing in candidates):
                candidates.append(candidate)
        return candidates

    def _apply_fingerbox_rounding(source_body: cq.Workplane, radius: float) -> cq.Workplane:
        # Add a small fillet to the inner edge of each fingerbox for comfort. The
        # stored regions keep this from catching unrelated circular edges.
        if radius <= 0:
            return source_body

        rounding_tolerance = 1e-4
        fingerbox_rounding_edges = []
        for edge in source_body.edges("%Circle and >Z").vals():
            edge_bbox = edge.BoundingBox()
            edge_center = edge.Center()
            for x_min, x_max, y_min, y_max in fingerbox_rounding_regions:
                bbox_in_region = (
                    edge_bbox.xmin >= x_min - rounding_tolerance
                    and edge_bbox.xmax <= x_max + rounding_tolerance
                    and edge_bbox.ymin >= y_min - rounding_tolerance
                    and edge_bbox.ymax <= y_max + rounding_tolerance
                )
                center_in_region = (
                    x_min - rounding_tolerance <= edge_center.x <= x_max + rounding_tolerance
                    and y_min - rounding_tolerance <= edge_center.y <= y_max + rounding_tolerance
                )
                if bbox_in_region or center_in_region:
                    fingerbox_rounding_edges.append(edge)
                    break
        if not fingerbox_rounding_edges:
            return source_body
        return source_body.newObject(fingerbox_rounding_edges).fillet(radius)

    def _apply_outer_chamfers(source_body: cq.Workplane) -> cq.Workplane:
        result = source_body

        # Apply side_chamfer late, but only to the four original outer vertical edges.
        if side_chamfer > 0:
            side_chamfer_edges = []
            for edge in result.edges("|Z").vals():
                edge_bbox = edge.BoundingBox()
                if _bbox_on_x_boundary(edge_bbox) and _bbox_on_y_boundary(edge_bbox):
                    side_chamfer_edges.append(edge)
            if side_chamfer_edges:
                result = result.newObject(side_chamfer_edges).chamfer(side_chamfer)

        # Apply top_bottom_chamfer late, keeping it on the exterior perimeter only.
        if tb_chamfer > 0:
            top_bottom_chamfer_edges = []
            for face_selector in (">Z", "<Z"):
                for edge in result.faces(face_selector).wires().toPending().edges().vals():
                    edge_bbox = edge.BoundingBox()
                    if (
                        _near(edge_bbox.xmin, body_x_min)
                        or _near(edge_bbox.xmax, body_x_max)
                        or _near(edge_bbox.ymin, body_y_min)
                        or _near(edge_bbox.ymax, body_y_max)
                    ):
                        top_bottom_chamfer_edges.append(edge)
            if top_bottom_chamfer_edges:
                result = result.newObject(top_bottom_chamfer_edges).chamfer(tb_chamfer)

        return result

    unrounded_body = body
    edge_rounding_error: Exception | None = None
    for candidate_radius in _edge_rounding_candidates(fillet_radius):
        try:
            rounded_body = _apply_fingerbox_rounding(unrounded_body, candidate_radius)
            body = _apply_outer_chamfers(rounded_body)
            if candidate_radius < fillet_radius:
                warning_messages.append(
                    f"edge_rounding too large for the current fingerbox and chamfer geometry. "
                    f"Clamped to {candidate_radius:.2f} mm so the model can be created."
                )
            break
        except Exception as exc:
            edge_rounding_error = exc
    else:
        if edge_rounding_error is not None:
            raise edge_rounding_error

    body_bbox = body.val().BoundingBox()
    rope_cut_clearance = 2.0

    cord_hole_groove_cut_radius = safe_cord_hole_diameter / 2.0
    hole_z, cord_hole_placement_warnings = _cord_hole_stair_center_z(
        params.bottom_layer_thickness,
        params.edge_depth,
        board_height,
        safe_cord_hole_diameter,
    )
    warning_messages.extend(cord_hole_placement_warnings)

    # Single rope hole at the center of the stairs.
    center_hole_center_x = (body_bbox.xmin + body_bbox.xmax) / 2.0
    center_hole_half_length = (
        ((body_bbox.xmax - body_bbox.xmin) / 2.0)
        + rope_cut_clearance
    )
    center_hole = (
        cq.Workplane("YZ")
        .center(0.0, hole_z)
        .circle(cord_hole_groove_cut_radius)
        .extrude(center_hole_half_length, both=True)
        .translate((center_hole_center_x, 0.0, 0.0))
    )
    body = body.cut(center_hole)

    end_groove_center_y = (body_bbox.ymin + body_bbox.ymax) / 2.0
    end_groove_half_width = (
        ((body_bbox.ymax - body_bbox.ymin) / 2.0)
        + rope_cut_clearance
    )
    positive_end_groove = (
        cq.Workplane("XZ")
        .center(body_bbox.xmax, hole_z)
        .circle(cord_hole_groove_cut_radius)
        .extrude(end_groove_half_width, both=True)
        .translate((0.0, end_groove_center_y, 0.0))
    )
    negative_end_groove = (
        cq.Workplane("XZ")
        .center(body_bbox.xmin, hole_z)
        .circle(cord_hole_groove_cut_radius)
        .extrude(end_groove_half_width, both=True)
        .translate((0.0, end_groove_center_y, 0.0))
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

    warning = "\n".join(warning_messages) if warning_messages else None
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

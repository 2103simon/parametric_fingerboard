import unittest
from collections import Counter

from parametric_fingerboard.model import (
    FingerboardParameters,
    SideParameters,
    _finger_depth_offsets,
    _finger_depths,
    _minimum_profile_sum,
    _monotone_finger_profile,
    _profile_value,
    build_fingerboard,
    is_shape_watertight,
)


class InterpolatedFingerstairsTests(unittest.TestCase):
    def test_interpolation_offsets_use_the_stair_delta_chain_and_baseline(self) -> None:
        hand_span = 80.0
        side = SideParameters(
            index_middle=-12.0,
            middle_ring=-3.0,
            ring_pinky=-4.0,
        )

        # Pinky starts at plateau zero, then ring=4, middle=7 and index=-5.
        # Shifting the plateaus makes index zero without changing their
        # differences.  Converting plateaus to stair depths gives these
        # offsets from the hand_span / 2 baseline.
        expected_offsets = [12.0, 0.0, 3.0, 7.0]
        expected_depths = [40.0 + offset for offset in expected_offsets]

        self.assertEqual(_finger_depth_offsets(side), expected_offsets)
        self.assertEqual(_finger_depths(hand_span, side), expected_depths)

    def test_profile_mirrors_fingers_and_repeats_boundary_values(self) -> None:
        profile = _monotone_finger_profile(
            80.0,
            [1.0, 4.0, 2.0, 7.0],
            mirrored=True,
        )

        self.assertEqual(profile.y, (7.0, 7.0, 2.0, 4.0, 1.0, 1.0))
        self.assertEqual(profile.slopes[0], 0.0)
        self.assertEqual(profile.slopes[1], 0.0)
        self.assertEqual(profile.slopes[-2], 0.0)
        self.assertEqual(profile.slopes[-1], 0.0)

    def test_profile_does_not_overshoot_any_interval(self) -> None:
        profile = _monotone_finger_profile(
            68.0,
            [0.0, 3.0, 1.0, 5.0],
        )

        for interval_index in range(len(profile.x) - 1):
            x_0 = profile.x[interval_index]
            x_1 = profile.x[interval_index + 1]
            expected_min = min(profile.y[interval_index:interval_index + 2])
            expected_max = max(profile.y[interval_index:interval_index + 2])
            for sample_index in range(21):
                x = x_0 + ((x_1 - x_0) * sample_index / 20.0)
                value = _profile_value(profile, x)
                self.assertGreaterEqual(value, expected_min - 1e-9)
                self.assertLessEqual(value, expected_max + 1e-9)

    def test_center_bulk_is_the_minimum_profile_separation(self) -> None:
        hand_span = 68.0
        left_depths = _finger_depths(hand_span, SideParameters(2.0, 3.0, 4.0))
        right_depths = _finger_depths(hand_span, SideParameters(1.0, 4.0, 3.0))
        left_relative = [value - min(left_depths) for value in left_depths]
        right_relative = [value - min(right_depths) for value in right_depths]
        left_wall = _monotone_finger_profile(
            hand_span,
            right_relative,
            mirrored=True,
        )
        right_wall = _monotone_finger_profile(
            hand_span,
            left_relative,
            mirrored=True,
        )
        center_bulk = 15.0
        profile_minimum = _minimum_profile_sum(left_wall, right_wall)
        wall_base = (center_bulk / 2.0) - (profile_minimum / 2.0)

        separations = [
            (2.0 * wall_base)
            + _profile_value(left_wall, -hand_span / 2.0 + hand_span * i / 1000.0)
            + _profile_value(right_wall, -hand_span / 2.0 + hand_span * i / 1000.0)
            for i in range(1001)
        ]
        self.assertAlmostEqual(min(separations), center_bulk, places=8)
        self.assertTrue(all(value >= center_bulk - 1e-8 for value in separations))

    def test_curved_walls_are_rounded_and_watertight(self) -> None:
        params = FingerboardParameters(
            left=SideParameters(2.0, 3.0, 4.0),
            right=SideParameters(1.0, 4.0, 3.0),
            edge_rounding=0.5,
            finger_groove_factor=0.0,
            side_chamfer=0.0,
            top_bottom_chamfer=0.0,
        )

        body, warning = build_fingerboard(params)
        shape = body.val()
        face_types = Counter(face.geomType() for face in shape.Faces())

        self.assertIsNone(warning)
        self.assertTrue(shape.isValid())
        self.assertEqual(len(shape.Solids()), 1)
        self.assertGreaterEqual(face_types["BSPLINE"], 2)
        self.assertTrue(is_shape_watertight(shape))


if __name__ == "__main__":
    unittest.main()

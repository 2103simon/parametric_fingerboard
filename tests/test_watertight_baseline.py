import unittest
from collections import Counter

import trimesh

from parametric_fingerboard.model import (
    FingerboardParameters,
    SideParameters,
    _find_valid_fillet_radius,
    build_fingerboard,
)


class WatertightBaselineTests(unittest.TestCase):
    def assertWatertight(self, shape) -> None:
        vertices, triangles = shape.tessellate(0.15)
        mesh = trimesh.Trimesh(
            vertices=[vertex.toTuple() for vertex in vertices],
            faces=triangles,
            process=True,
        )

        self.assertTrue(shape.isValid())
        self.assertEqual(len(shape.Solids()), 1)
        self.assertEqual(len(shape.Shells()), 1)
        self.assertTrue(mesh.is_watertight)
        self.assertTrue(mesh.is_winding_consistent)

    def test_adaptive_search_converges_near_valid_limit(self) -> None:
        def accept_below_one(radius: float) -> float:
            if radius >= 1.0:
                raise ValueError("invalid test radius")
            return radius

        actual_radius, result = _find_valid_fillet_radius(
            2.0,
            accept_below_one,
        )

        self.assertGreater(actual_radius, 0.98)
        self.assertLess(actual_radius, 1.0)
        self.assertEqual(result, actual_radius)

    def test_asymmetric_stairs_fall_back_to_watertight_fillet(self) -> None:
        params = FingerboardParameters(
            left=SideParameters(2.0, 3.0, 4.0),
            right=SideParameters(1.0, 4.0, 3.0),
            edge_rounding=2.0,
        )
        body, warning = build_fingerboard(params)
        face_types = Counter(face.geomType() for face in body.val().Faces())

        self.assertIsNotNone(warning)
        self.assertIn("Clamped to 0.98 mm", warning)
        self.assertGreaterEqual(face_types["TORUS"], 8)
        self.assertWatertight(body.val())

    def test_tiny_stair_deltas_never_return_an_open_mesh(self) -> None:
        params = FingerboardParameters(
            left=SideParameters(0.25, 0.5, 0.75),
            right=SideParameters(0.5, 0.25, 0.75),
            edge_rounding=0.5,
        )
        body, warning = build_fingerboard(params)

        self.assertIsNotNone(warning)
        self.assertWatertight(body.val())


if __name__ == "__main__":
    unittest.main()

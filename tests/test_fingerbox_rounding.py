import unittest
from collections import Counter

import trimesh

from parametric_fingerboard.model import (
    FingerboardParameters,
    SideParameters,
    build_fingerboard,
)


def _asymmetric_parameters(edge_rounding: float) -> FingerboardParameters:
    return FingerboardParameters(
        left=SideParameters(2.0, 3.0, 4.0),
        right=SideParameters(1.0, 4.0, 3.0),
        edge_rounding=edge_rounding,
    )


class FingerboxRoundingTests(unittest.TestCase):
    def test_rounds_stairs_and_interpolated_contour(self) -> None:
        unrounded, _ = build_fingerboard(_asymmetric_parameters(0.0))
        rounded, warning = build_fingerboard(_asymmetric_parameters(0.5))

        unrounded_face_types = Counter(
            face.geomType() for face in unrounded.val().Faces()
        )
        rounded_face_types = Counter(
            face.geomType() for face in rounded.val().Faces()
        )

        self.assertIsNone(warning)
        self.assertTrue(rounded.val().isValid())
        self.assertEqual(len(rounded.val().Solids()), 1)
        # Circular stair edges create toroidal fillet faces.
        self.assertGreaterEqual(rounded_face_types["TORUS"], 8)
        # The sampled interpolated contour creates cylindrical fillet faces.
        self.assertGreater(
            rounded_face_types["CYLINDER"],
            unrounded_face_types["CYLINDER"],
        )

    def test_large_radius_falls_back_to_a_watertight_solid(self) -> None:
        rounded, warning = build_fingerboard(_asymmetric_parameters(2.5))
        shape = rounded.val()
        vertices, triangles = shape.tessellate(0.15)
        mesh = trimesh.Trimesh(
            vertices=[vertex.toTuple() for vertex in vertices],
            faces=triangles,
            process=True,
        )

        self.assertIsNotNone(warning)
        self.assertIn("Clamped to 0.50 mm", warning)
        self.assertTrue(shape.isValid())
        self.assertEqual(len(shape.Solids()), 1)
        self.assertTrue(mesh.is_watertight)
        self.assertTrue(mesh.is_winding_consistent)


if __name__ == "__main__":
    unittest.main()

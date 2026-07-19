import pathlib
import sys
import unittest


REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import bridge_server


class DurationToFramesTests(unittest.TestCase):
    def test_recovers_integer_frame_counts_at_kimodo_rate(self):
        fps = 30.0
        for expected_frames in range(1, 1001):
            with self.subTest(expected_frames=expected_frames):
                duration = expected_frames / fps
                self.assertEqual(
                    bridge_server._duration_to_frames(duration, fps),
                    expected_frames,
                )

    def test_clamps_subframe_duration_to_one_frame(self):
        self.assertEqual(bridge_server._duration_to_frames(0.0, 30.0), 1)


if __name__ == "__main__":
    unittest.main()

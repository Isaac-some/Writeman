"""Check rendered duration and visual order without hiding excess footage with -t."""
import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

SPEC = importlib.util.spec_from_file_location("assemble_demo", Path(__file__).with_name("assemble-demo.py"))
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def run(args):
    return subprocess.run(args, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout


class TimelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="writeman-timeline-")
        cls.root = Path(cls.temp.name)
        cls.source = cls.root / "four-colors.mp4"
        args = ["ffmpeg", "-hide_banner", "-loglevel", "error"]
        for color in ["red", "lime", "blue", "yellow"]:
            args += ["-f", "lavfi", "-i", f"color={color}:s=32x32:r=20:d=2"]
        run(args + ["-filter_complex", "[0:v][1:v][2:v][3:v]concat=n=4:v=1:a=0[v]",
                    "-map", "[v]", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(cls.source)])

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def render(self, speed_ranges, filename):
        filters, duration = MODULE.speed_filters(8.0, speed_ranges, input_label="0:v")
        output = self.root / filename
        run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(self.source),
             "-filter_complex", ";".join(filters), "-map", "[sped]", "-fps_mode", "cfr", "-r", "20",
             "-c:v", "libx264", str(output)])
        probe = json.loads(run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(output)]))
        # A CFR encoder can round each concat boundary by a frame (50ms here).
        self.assertAlmostEqual(float(probe["format"]["duration"]), duration, delta=0.15)
        return output

    def assert_color(self, video, seconds, expected):
        rgb = tuple(run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-ss", str(seconds),
                         "-i", str(video), "-vf", "scale=1:1", "-frames:v", "1", "-pix_fmt", "rgb24",
                         "-f", "rawvideo", "pipe:1"]))
        self.assertEqual(len(rgb), 3)
        for got, want in zip(rgb, expected):
            self.assertLess(abs(got - want), 20, (seconds, rgb, expected))

    def test_normal_demo_is_one_pass(self):
        video = self.render([], "normal.mp4")
        for seconds, color in [(0.5, (255, 0, 0)), (2.5, (0, 255, 0)),
                               (4.5, (0, 0, 255)), (6.5, (255, 255, 0))]:
            self.assert_color(video, seconds, color)

    def test_speed_interval_keeps_order_and_single_tail(self):
        video = self.render([(2.0, 4.0, 2.0)], "sped.mp4")
        for seconds, color in [(0.5, (255, 0, 0)), (2.5, (0, 255, 0)),
                               (3.5, (0, 0, 255)), (5.5, (255, 255, 0))]:
            self.assert_color(video, seconds, color)


class ZoomPlanTests(unittest.TestCase):
    def load(self, regions, clicks=None):
        with tempfile.TemporaryDirectory(prefix="writeman-plan-") as name:
            path = Path(name) / "plan.json"
            path.write_text(json.dumps({"zoomRegions": regions, "criticalClicksMs": clicks or []}))
            return MODULE.load_zoom_plan(path, 8.0)

    def region(self, start=1000, end=3000):
        return {"startMs": start, "endMs": end, "depth": 2,
                "focus": {"cx": 0.6, "cy": 0.4}, "rotationPreset": "left"}

    def test_rotation_and_pointer_follow_survive_plan_loading(self):
        result = self.load([self.region()], [2000])
        self.assertEqual(result[0]["rotationPreset"], "left")
        self.assertEqual(result[0]["focusMode"], "auto")

    def test_uncovered_critical_click_stops_rendering(self):
        with self.assertRaisesRegex(ValueError, "critical click"):
            self.load([self.region()], [3500])

    def test_overlapping_regions_stop_rendering(self):
        with self.assertRaisesRegex(ValueError, "overlap"):
            self.load([self.region(), self.region(2500, 4500)])

    def test_nonfinite_time_stops_rendering(self):
        with self.assertRaisesRegex(ValueError, "times"):
            self.load([self.region(end=float("nan"))])


if __name__ == "__main__":
    unittest.main()

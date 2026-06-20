"""Tests that pov_fuse_render escapes demo/CLI-derived text (no HTML/JS injection).

Pure stdlib unittest. Follows the komodobots convention: put the module's dir on
sys.path, import top-level. The render script writes a self-contained HTML contact
sheet that pov_fuse_shot.js opens in Chromium with file:// + --no-sandbox, so any
demo/player/CLI string that reaches a markup slot or the <script> payload would
execute. This guards the hardening:
  - the JSON __DATA__ payload is escaped so it cannot break out of <script>
  - header/sig fields are html.escape()d
  - the per-row teamsay/file strings are inserted as text nodes, not markup
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROUTE_OBS = HERE.parent / "experiments" / "route_observatory"
for _p in (str(ROUTE_OBS), str(HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

RENDER = ROUTE_OBS / "pov_fuse_render.py"
XSS = "</script><img src=x onerror=alert(1)>"


def render(leg):
    """Run pov_fuse_render on a leg dict and return the generated HTML string."""
    d = tempfile.mkdtemp()
    frames_dir = os.path.join(d, "frames")
    os.makedirs(frames_dir)
    # minimal valid jpeg (SOI+EOI) so img_data_uri() can read a frame
    with open(os.path.join(frames_dir, "f0.jpg"), "wb") as f:
        f.write(b"\xff\xd8\xff\xd9")
    leg_path = os.path.join(d, "leg.json")
    out_html = os.path.join(d, "out.html")
    with open(leg_path, "w", encoding="utf-8") as f:
        json.dump(leg, f)
    r = subprocess.run([sys.executable, str(RENDER), leg_path, frames_dir, out_html],
                       capture_output=True, text=True)
    assert r.returncode == 0, f"render failed: {r.stderr}"
    with open(out_html, encoding="utf-8") as f:
        return f.read()


def mk_leg(label=XSS, teamsay_text=XSS):
    return {
        "ticks": [{"t": 0.0, "x": 0, "y": 0, "z": 0, "hs": 400, "yaw": 0, "mdir": 0, "vz": 0}],
        "markers": [{"x": 0, "y": 0, "name": "RA", "res": True}],
        "teamsay": [{"t": 0.0, "text": teamsay_text}],
        "frames": [{"s": 0, "file": "f0.jpg", "exists": True}],
        "signature": {"dur_s": 1.0, "hs_min": 1, "hs_mean": 2, "hs_max": 3, "jumps": 0,
                      "lookmove_mean_deg": 0, "path_qu": 0, "straightness": 1.0},
        "label": label, "player": XSS, "demo": XSS,
    }


class TestRenderEscaping(unittest.TestCase):
    def test_no_script_breakout_or_executable_img(self):
        html = render(mk_leg())
        # The ONLY literal </script> allowed is the document's own closing tag.
        self.assertEqual(html.count("</script>"), 1,
                         "demo/CLI text broke out of <script> or a markup slot")
        self.assertTrue(html.rstrip().endswith("</script></body></html>"),
                        "the single </script> is not the document closer")
        # A literal '<img' (real '<') anywhere means an executable tag was injected.
        # After hardening, '<' is neutralized to '&lt;' (html.escape) or '\\u003c'
        # (script payload), so no literal '<img' should survive.
        self.assertNotIn("<img", html,
                         "an executable <img ...> reached a markup position")
        # the payload must still be PRESENT, only in escaped form
        self.assertTrue("&lt;" in html or "\\u003c" in html,
                        "payload was dropped instead of escaped")

    def test_benign_input_renders_label_and_teamsay(self):
        html = render(mk_leg(label="hilljump", teamsay_text="go go go"))
        # benign text survives verbatim in the output (visual identity preserved)
        self.assertIn("hilljump", html)
        self.assertIn("go go go", html)


if __name__ == "__main__":
    unittest.main()

"""Run: python -m unittest discover -s tests -v   (stdlib only, uses a synthetic screenplay)"""
import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from promofinder.parse import load_show, sec_to_ts
from promofinder.candidates import generate, MIN_LEN, MAX_LEN
from promofinder.llm import Model, build_judge_prompt, validate_judgement, quote_ok
from promofinder.pipeline import run

SAMPLE = Path(__file__).parent / "fixtures" / "sample_show"


class TestParse(unittest.TestCase):
    def test_parse(self):
        title, eps = load_show(SAMPLE)
        self.assertEqual(len(eps), 1)
        ep = eps[0]
        self.assertEqual(ep.number, 1)
        kinds = {b.kind for b in ep.beats}
        self.assertEqual(kinds, {"camera", "action", "dialogue", "sfx"})
        vera = [b for b in ep.beats if b.speaker == "VERA"][0]
        self.assertEqual(vera.delivery, "Cold, Accusing")
        self.assertTrue(vera.text.startswith("Before you toast her"))
        self.assertEqual(ep.duration, 52.0)
        self.assertEqual(sec_to_ts(75.5), "01:15.50")


class TestCandidates(unittest.TestCase):
    def setUp(self):
        self.title, self.eps = load_show(SAMPLE)
        self.promos, self.idx = generate(self.title, self.eps)

    def test_lengths_and_cuts(self):
        self.assertTrue(self.promos)
        ix = self.idx[1]
        for p in self.promos:
            self.assertGreaterEqual(p.duration, MIN_LEN - 0.01)
            self.assertLessEqual(p.duration, MAX_LEN + 0.01)
            for s in p.segments:
                self.assertFalse(ix._inside_line(s.start), f"{p.id} starts mid-line")
                self.assertFalse(ix._inside_line(s.end), f"{p.id} ends mid-line")

    def test_best_promo_hooks_and_ends_on_cliff(self):
        best = max(self.promos, key=lambda p: p.heuristic_score)
        self.assertGreater(best.scores["hook"], 0.5)
        self.assertGreater(best.scores["cliffhanger"], 0.5)


class TestModelLayer(unittest.TestCase):
    def setUp(self):
        self.title, self.eps = load_show(SAMPLE)
        self.promos, self.idx = generate(self.title, self.eps)
        self.p = max(self.promos, key=lambda p: p.heuristic_score)

    def test_rejects_invented_beats_and_quotes(self):
        prompt, allowed = build_judge_prompt(self.p, self.idx, self.title)
        some = next(iter(allowed))
        raw = {"hook_score": 8, "cliffhanger_score": 7, "standalone_score": 9, "overall": 8,
               "hook_beat": "E01-B999", "hook_quote": "made up",
               "cliff_beat": some, "cliff_quote": "a line that is not in the script at all",
               "why": "x", "suggested_start_beat": None, "suggested_end_beat": "E09-B001", "problems": []}
        clean, rejected = validate_judgement(raw, self.p, allowed)
        self.assertNotIn("hook_beat", clean)
        self.assertNotIn("cliff_beat", clean)
        self.assertNotIn("suggested_end_beat", clean)
        self.assertEqual(len(rejected), 3)
        self.assertEqual(clean["overall"], 8)

    def test_quote_match_is_tolerant_to_punctuation(self):
        self.assertTrue(quote_ok("there it is my sister is a thief", "There it is. My sister is a thief."))
        self.assertFalse(quote_ok("my brother is a thief", "There it is. My sister is a thief."))

    def test_openai_compatible_provider_end_to_end(self):
        """Spin up a fake OpenAI-compatible server and run the whole pipeline through it."""
        title, eps, idx = self.title, self.eps, self.idx

        class H(BaseHTTPRequestHandler):
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                prompt = body["messages"][0]["content"]
                ids = [l.split("]")[0][1:] for l in prompt.splitlines() if l.startswith("[E01-B")]
                b = idx[1].by_id[ids[0]]
                ans = {"hook_score": 7, "cliffhanger_score": 8, "standalone_score": 7, "overall": 7,
                       "hook_beat": b.id, "hook_quote": b.text, "cliff_beat": "E01-B777", "cliff_quote": "nope",
                       "why": "Public accusation at a party, ends on a family-secret question.",
                       "suggested_start_beat": None, "suggested_end_beat": None, "problems": []}
                out = json.dumps({"choices": [{"message": {"content": json.dumps(ans)}}],
                                  "usage": {"prompt_tokens": 100, "completion_tokens": 50}}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(out)

            def log_message(self, *a):
                pass

        srv = HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        import os
        os.environ["OPENAI_BASE_URL"] = f"http://127.0.0.1:{srv.server_port}/v1"
        os.environ["OPENAI_API_KEY"] = "test"
        with tempfile.TemporaryDirectory() as d:
            res = run(str(SAMPLE), out_dir=d, model_spec="openai:fake-model", shortlist_n=5,
                      cache_dir=str(Path(d) / "cache"), log=lambda *a: None)
            self.assertGreater(res["meta"]["llm_calls"], 0)
            judged = [p for p in res["promos"] if p.llm.get("overall") is not None]
            self.assertTrue(judged)
            # invented cliff beat must have been rejected, not used
            self.assertTrue(all(p.cliff_beat != "E01-B777" for p in judged))
            for f in ("promos.json", "promos.csv", "report.md", "report.html", "qc_report.md"):
                self.assertTrue((Path(d) / f).exists(), f)
            # second run hits the cache, no new calls
            res2 = run(str(SAMPLE), out_dir=d, model_spec="openai:fake-model", shortlist_n=5,
                       cache_dir=str(Path(d) / "cache"), log=lambda *a: None)
            self.assertEqual(res2["meta"]["llm_calls"], 0)
        srv.shutdown()
        srv.server_close()

    def test_model_timeout_falls_back_to_rules(self):
        """A slow or unreachable model must not crash the run; rules values are kept."""
        import os
        import urllib.request
        from unittest import mock

        def always_times_out(*a, **k):
            raise TimeoutError("The read operation timed out")

        os.environ["OPENAI_API_KEY"] = "test"
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(urllib.request, "urlopen", always_times_out), \
                mock.patch("promofinder.llm.time.sleep", lambda s: None):
            res = run(str(SAMPLE), out_dir=d, model_spec="openai:fake-model", shortlist_n=3,
                      cache_dir=str(Path(d) / "cache"), log=lambda *a: None)
            self.assertTrue(res["promos"])
            self.assertTrue(all(p.llm.get("overall") is None for p in res["promos"]))
            self.assertTrue((Path(d) / "promos.json").exists())


if __name__ == "__main__":
    unittest.main()

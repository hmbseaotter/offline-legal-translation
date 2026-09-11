#!/usr/bin/env python3
"""A stand-in for Ollama, for the tests. No model; invented text only.

Usage:  mock_ollama.py PORT RULES.json LOG.jsonl

Answers GET /api/tags with the models the rules name, and POST /api/generate
by the rules. They are read again on every request, so a test can change them
without a restart:

    {"models":   ["gams3:q8", "eurollm9b-2512:q8"],
     "map":      {"source text": "reply"},
     "map_firm": {"source text": "reply to the firmer retry"},
     "wrap":     "<<{}>>"}

A source with no entry is answered wrap.format(source). A numbered batch is
answered line by line by the same rules. Every request is appended to LOG as
one JSON line: the model, whether it was a batch or a firm retry, the prompt
and the reply.
"""
import json
import re
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT, RULES, LOG = int(sys.argv[1]), sys.argv[2], sys.argv[3]
# The openings of trlib.FIRM_PREFIX and of the batch request in
# trlib._translate_batch(). Each is followed by a blank line and the text.
FIRM = "Translate only the text below."
BATCH = "Translate each numbered line separately."


def rules():
    with open(RULES, encoding="utf-8") as fh:
        return json.load(fh)


def reply(text, firm, r):
    if firm and text in r.get("map_firm", {}):
        return r["map_firm"][text]
    if text in r.get("map", {}):
        return r["map"][text]
    return r.get("wrap", "<<{}>>").format(text)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def send(self, obj):
        body = json.dumps(obj).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith("/api/tags"):
            return self.send({"models": [{"name": m} for m in rules().get("models", [])]})
        self.send_error(404)

    def do_POST(self):
        req = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        r, prompt = rules(), req.get("prompt", "")
        firm, batch = prompt.startswith(FIRM), prompt.startswith(BATCH)
        body = prompt.split("\n\n", 1)[-1] if firm or batch else prompt
        if batch:
            lines = (re.match(r"^(\d+)\. (.*)$", ln) for ln in body.splitlines())
            out = "\n".join(f"{m.group(1)}. " + reply(m.group(2), False, r).replace("\n", " ")
                            for m in lines if m)
        else:
            out = reply(body, firm, r)
        with open(LOG, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"model": req.get("model"), "firm": firm, "batch": batch,
                                 "prompt": prompt, "reply": out}, ensure_ascii=False) + "\n")
        self.send({"model": req.get("model"), "response": out, "done": True,
                   "done_reason": "stop"})


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()

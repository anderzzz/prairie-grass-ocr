"""Vision-LLM cell reader (Anthropic API), opt-in and cost-capped.

Called only by pipeline code; every raw response is cached on disk together
with its token usage, so re-runs cost nothing and the exact model output
behind each value can be inspected later. The model never sees anything but
pixels of the page and a fixed prompt.

Modes (what the model is shown):
  glyphs      the isolated glyphs the offline readers see
  cell        the cell as scanned, with a margin and its ruling
  cell_rules  as `cell`, plus the table's printing conventions; returns JSON
              with an `uncertain` flag and a short note
  context     a strip of the same column (2 rows above and below) with the
              target cell outlined, plus the conventions; returns JSON
"""
from __future__ import annotations

import base64
import json
import os
import threading
from dataclasses import dataclass

import cv2
import numpy as np

from .cache import cached

# USD per million tokens (input, output); Anthropic list prices, Nov 2026
PRICES = {"claude-haiku-5-5": (0.10, 0.50), "claude-sonnet-5-5": (2.00, 10.00),
          "claude-opus-5-5": (4.00, 20.00)}
MAX_NEW_CALLS = int(os.environ.get("PGOCR_LLM_MAX_CALLS", "2000"))

_lock = threading.Lock()
_new_calls = 0
_spend = {"input_tokens": 0, "output_tokens": 0, "calls": 0}

PLAIN = ("This image shows one cell of a printed 1950s table of gas concentrations. "
         "Transcribe exactly the characters printed in the cell: digits, decimal point, "
         "the letter M, or an asterisk. Ignore ruling lines and anything cut off at the "
         "image edge that belongs to a neighbouring cell. Reply with only the characters; "
         "reply EMPTY if the cell is blank and ILLEGIBLE if it cannot be read.")

RULES = (
    "Printing conventions of this table (mg per cubic metre):\n"
    "- Values have three significant figures: 0.ddd below 1 (e.g. 0.045), d.dd below 10 "
    "(e.g. 4.94), dd.d below 100 (e.g. 98.6), and whole numbers from 100 (e.g. 161, 2200).\n"
    "- A value below 1 always starts with '0.'; a value never starts or ends with a "
    "decimal point.\n"
    "- 'M' means missing; an asterisk after a value means estimated; a blank cell means "
    "no measurable concentration.\n"
    "Use these conventions only to decide between readings of what is actually printed "
    "(for example whether a faint mark is a decimal point). Never invent or complete "
    "characters that are not visible. If you had to choose between plausible readings, "
    "or any character is unclear, set uncertain to true and say why in the note.")

CELL_RULES = ("This image shows one cell of a printed 1950s table of SO2 concentrations, "
              "with a little of its ruling and neighbouring cells around it.\n" + RULES +
              "\nTranscribe the value printed in this cell. Use \"\" for a blank cell.")

CONTEXT = ("This image shows a strip of one column of a printed 1950s table of SO2 "
           "concentrations. The target cell is outlined in red; the other rows are shown "
           "only so you can see the print style and alignment.\n" + RULES +
           "\nTranscribe the value printed in the outlined cell only. Do not copy or derive "
           "it from the neighbouring rows. Use \"\" for a blank cell.")

SCHEMA = {"type": "object",
          "properties": {"text": {"type": "string"}, "uncertain": {"type": "boolean"},
                         "note": {"type": "string"}},
          "required": ["text", "uncertain", "note"], "additionalProperties": False}


class CallCapReached(RuntimeError):
    pass


def spend() -> dict:
    """Tokens and USD of *new* (uncached) calls in this process."""
    with _lock:
        return dict(_spend)


def cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    pi, po = PRICES.get(model, (float("nan"), float("nan")))
    return input_tokens / 1e6 * pi + output_tokens / 1e6 * po


def _png(img: np.ndarray) -> str:
    ok, buf = cv2.imencode(".png", img)
    return base64.b64encode(buf.tobytes()).decode()


@dataclass(frozen=True)
class LLMReader:
    model: str = "claude-haiku-5-5"
    mode: str = "cell_rules"
    effort: str = "low"
    scale: float = 2.0

    @property
    def name(self) -> str:
        return "llm"

    @staticmethod
    def available() -> bool:
        return bool(os.environ.get("ANTHROPIC_API_KEY"))

    def describe(self) -> dict:
        return {"engine": self.model, "mode": self.mode, "effort": self.effort, "scale": self.scale}

    def read(self, glyphs: np.ndarray, raw: np.ndarray | None = None) -> dict:
        """glyphs: isolated glyph crop; raw: the cell (or context strip) as
        scanned. Which one is sent depends on the mode."""
        img = glyphs if self.mode == "glyphs" else raw
        if img is None:
            raise ValueError(f"mode {self.mode} needs the raw crop")
        if self.scale != 1.0:
            img = cv2.resize(img, None, fx=self.scale, fy=self.scale, interpolation=cv2.INTER_CUBIC)
        prompt = {"glyphs": PLAIN, "cell": PLAIN, "cell_rules": CELL_RULES, "context": CONTEXT}[self.mode]
        structured = self.mode in ("cell_rules", "context")
        params = {"model": self.model, "prompt": prompt, "effort": self.effort,
                  "structured": structured}
        return cached("reader_llm", params, img, lambda: self._call(img, prompt, structured))

    def _call(self, img: np.ndarray, prompt: str, structured: bool) -> dict:
        global _new_calls
        with _lock:
            if _new_calls >= MAX_NEW_CALLS:
                raise CallCapReached(f"{MAX_NEW_CALLS} new API calls in this run "
                                     "(raise PGOCR_LLM_MAX_CALLS to allow more)")
            _new_calls += 1
        import anthropic
        client = anthropic.Anthropic()
        kw = {}
        if structured:
            kw["output_config"] = {"effort": self.effort,
                                   "format": {"type": "json_schema", "schema": SCHEMA}}
        else:
            kw["output_config"] = {"effort": self.effort}
        msg = client.messages.create(
            model=self.model, max_tokens=2000,
            messages=[{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                             "data": _png(img)}},
                {"type": "text", "text": prompt}]}],
            **kw)
        raw = "".join(b.text for b in msg.content if b.type == "text").strip()
        u = msg.usage
        with _lock:
            _spend["input_tokens"] += u.input_tokens
            _spend["output_tokens"] += u.output_tokens
            _spend["calls"] += 1
        out = {"raw_response": raw, "stop_reason": msg.stop_reason, "model": msg.model,
               "request_id": getattr(msg, "_request_id", None),
               "usage": {"input_tokens": u.input_tokens, "output_tokens": u.output_tokens},
               "conf": None}
        if structured:
            try:
                d = json.loads(raw)
                out.update(text=d["text"].strip(), uncertain=bool(d["uncertain"]), note=d["note"])
            except (ValueError, KeyError):
                out.update(text=raw, uncertain=True, note="unparseable JSON response")
        else:
            out.update(text="" if raw == "EMPTY" else raw, uncertain=raw == "ILLEGIBLE", note="")
        return out

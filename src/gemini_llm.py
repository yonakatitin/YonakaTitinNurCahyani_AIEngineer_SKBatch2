"""RealLLM berbasis Gemini lewat REST (tanpa SDK, supaya ringan untuk Vercel)."""
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from .llm import EXTRACTION_PROMPT

SCHEMA_HINT = """
Return ONE JSON object with exactly these keys:
{
  "education": [{"institution": str|null, "degree": str|null, "field_of_study": str|null,
                 "end_year": int|null, "gpa": float|null, "evidence": str|null,
                 "confidence": "high"|"medium"|"low"}],
  "experience": [{"company": str|null, "title": str|null, "start": "YYYY-MM"|null,
                  "end": "YYYY-MM"|"present"|null,
                  "employment_type": "internship"|"full_time"|"freelance"|"project"|"unknown",
                  "summary": str|null, "evidence": str|null, "confidence": "high"|"medium"|"low"}],
  "skills": [{"name": str, "category": "language"|"framework"|"tool"|"domain"|"other",
              "evidence": str|null, "confidence": "high"|"medium"|"low"}],
  "projects": [{"name": str|null, "description": str|null, "tech": [str],
                "evidence": str|null, "confidence": "high"|"medium"|"low"}],
  "certifications": [{"evidence": str|null, "confidence": "high"|"medium"|"low"}],
  "extraction_notes": [str]
}
Use lowercase for skill names. Use empty lists when nothing is found.
"""


def _load_env():
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


class RealLLM:
    def __init__(self):
        _load_env()
        self.key = os.getenv("LLM_API_KEY", "")
        self.model = os.getenv("LLM_MODEL", "")
        self.min_interval = float(os.getenv("LLM_MIN_INTERVAL", "4"))
        if not self.key or not self.model:
            raise RuntimeError("Set LLM_API_KEY and LLM_MODEL in .env for real mode.")
        self._last = 0.0

    def _post(self, body: dict) -> dict:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"
        req = urllib.request.Request(
            url, data=json.dumps(body).encode("utf-8"), method="POST",
            headers={"Content-Type": "application/json", "x-goog-api-key": self.key})
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def extract(self, cv_text: str) -> dict:
        body = {
            "systemInstruction": {"parts": [{"text": EXTRACTION_PROMPT + SCHEMA_HINT}]},
            "contents": [{"role": "user",
                          "parts": [{"text": "<cv>\n" + cv_text + "\n</cv>"}]}],
            "generationConfig": {"temperature": 0, "responseMimeType": "application/json"},
        }
        retry_codes = {429, 500, 502, 503, 504}
        max_attempts = 4
        for attempt in range(max_attempts):
            wait = self.min_interval - (time.time() - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.time()
            try:
                data = self._post(body)
                text = data["candidates"][0]["content"]["parts"][0]["text"]
                text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
                return json.loads(text)
            except urllib.error.HTTPError as e:
                print(f"[gemini] HTTP {e.code} (attempt {attempt + 1}/{max_attempts})", file=sys.stderr)
                if e.code in retry_codes and attempt < max_attempts - 1:
                    time.sleep(5 * (2 ** attempt))   # 5s, 10s, 20s
                    continue
                break
            except (KeyError, IndexError, json.JSONDecodeError, OSError) as e:
                print(f"[gemini] {type(e).__name__} (attempt {attempt + 1}/{max_attempts})", file=sys.stderr)
                if attempt < max_attempts - 1:
                    time.sleep(3)
                    continue
        return {"extraction_notes": ["llm_call_failed"]}

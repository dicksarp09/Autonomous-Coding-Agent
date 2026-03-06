"""Utilities to extract and hash error signatures from test traces."""
from __future__ import annotations
import hashlib
import re
from typing import List


def normalize_trace(trace: str) -> str:
    # remove timestamps and absolute paths -> keep filenames and line numbers
    # normalize Windows backslashes
    s = trace.replace("\\", "/")
    # remove timestamps like 2026-02-25 12:34:56
    s = re.sub(r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}", "", s)
    # replace absolute paths with basename: /home/user/project/foo.py -> foo.py:123
    s = re.sub(r"/([\w\-\.]+/)+([\w\-\.]+\.py):(\d+)", lambda m: f"{m.group(2)}:{m.group(3)}", s)
    # collapse whitespace
    s = "\n".join([line.strip() for line in s.splitlines() if line.strip()])
    return s


def signature_from_trace(trace: str) -> str:
    norm = normalize_trace(trace)
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()

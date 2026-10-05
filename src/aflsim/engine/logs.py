"""Game logs on disk: gzipped JSON (about a tenth the size of the old raw JSON). Plain .json still loads."""
from __future__ import annotations

import gzip
import json
import os


def _jsonable(o):
    import numpy as np
    if isinstance(o, (np.floating, np.integer)):
        return o.item()
    if isinstance(o, np.ndarray):
        return o.tolist()
    if isinstance(o, np.bool_):
        return bool(o)
    raise TypeError(type(o))


def save_log(ep: dict, path: str) -> str:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    data = json.dumps(ep, default=_jsonable).encode("utf-8")
    if path.endswith(".gz"):
        with gzip.open(path, "wb", compresslevel=6) as f:
            f.write(data)
    else:
        with open(path, "wb") as f:
            f.write(data)
    return path


def load_log(path: str) -> dict:
    if path.endswith(".gz"):
        with gzip.open(path, "rb") as f:
            return json.loads(f.read().decode("utf-8"))
    return json.load(open(path, encoding="utf-8"))

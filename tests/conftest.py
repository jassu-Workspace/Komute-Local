import os
from pathlib import Path

import pytest


def pytest_collection_modifyitems(config, items):
    d = os.environ.get("KOMUTE_SAMPLES_DIR")
    if d and Path(d).is_dir() and any(Path(d).iterdir()):
        return
    skip = pytest.mark.skip(reason="KOMUTE_SAMPLES_DIR missing or empty")
    for item in items:
        if "samples" in item.keywords:
            item.add_marker(skip)

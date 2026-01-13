from __future__ import annotations

import pytest
from questforge.engine.tests.manual_paths import build_paths, run_path


@pytest.mark.parametrize("path", build_paths(), ids=lambda p: p.name)
def test_manual_path(path):
    run_path(path, verbose=False)

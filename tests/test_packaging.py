"""The wheel is what `pip install memoryhub-mh` and `uv tool install memoryhub-mh` unpack.

The distribution is `memoryhub-mh` (PyPI's `memoryhub` is another project) while the import
package stays `memoryhub`, so pyproject tells hatchling where the package lives by hand. These
tests catch that mapping, the package data the CLI reads at runtime and the entry point drifting.
They build with uv, as CI and the release workflow do; uv's own cache is the one thing outside
the temp dir they touch.
"""

from __future__ import annotations

import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

pytestmark = pytest.mark.skipif(
    shutil.which("uv") is None or shutil.which("uvx") is None,
    reason="building the wheel needs uv",
)


@pytest.fixture(scope="module")
def wheel(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("dist")
    subprocess.run(
        ["uv", "build", "--wheel", "--out-dir", str(out), str(ROOT)],
        check=True,
        capture_output=True,
        text=True,
    )
    (built,) = out.glob("*.whl")
    return built


def _dist_info(z: zipfile.ZipFile) -> str:
    return next(n.split("/")[0] for n in z.namelist() if n.endswith("/METADATA"))


def test_the_wheel_carries_the_package_and_its_data_under_the_pypi_name(wheel: Path):
    assert wheel.name.startswith("memoryhub_mh-")
    names = set(zipfile.ZipFile(wheel).namelist())
    assert "memoryhub/cli.py" in names
    assert "memoryhub/skill/SKILL.md" in names  # `mh skill install` copies these
    assert "memoryhub/skill/ui/SKILL.md" in names
    assert "memoryhub/ui/index.html" in names  # `mh ui` serves this
    assert not any(n.startswith("memoryhub_mh/") for n in names)
    assert not any(n.startswith(("tests/", "docs/")) for n in names)


def test_the_metadata_names_the_distribution_the_floor_and_the_command(wheel: Path):
    z = zipfile.ZipFile(wheel)
    info = _dist_info(z)
    meta = z.read(f"{info}/METADATA").decode()
    assert "Name: memoryhub-mh" in meta
    assert "Requires-Python: >=3.12" in meta
    assert "Requires-Dist: typer" in meta
    assert "License-Expression: MIT" in meta or "License: MIT" in meta
    entry = z.read(f"{info}/entry_points.txt").decode()
    assert "mh = memoryhub.cli:app" in entry


def test_the_wheel_runs_on_its_own(wheel: Path, tmp_path: Path):
    """What a fresh install gets: the wheel plus its declared dependencies, nothing else."""
    r = subprocess.run(
        ["uvx", "--from", str(wheel), "mh", "--version"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr
    assert r.stdout.startswith("mh ")

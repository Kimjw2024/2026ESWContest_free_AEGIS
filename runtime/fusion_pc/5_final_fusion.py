# -*- coding: utf-8 -*-
"""Compatibility entry point for the live AEGIS fusion loop."""
import os
import runpy
import subprocess
import sys


PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
ASYNC_FUSION = os.path.join(PROJECT_ROOT, "5_final_fusion_async.py")


def _reexec_with_project_python():
    expected = os.path.join(
        os.environ.get("LOCALAPPDATA", ""),
        "Programs",
        "Python",
        "Python311",
        "python.exe",
    )
    if not expected or not os.path.exists(expected):
        return
    if os.path.normcase(os.path.abspath(sys.executable)) == os.path.normcase(os.path.abspath(expected)):
        return
    print(f"[PYTHON] Re-launching with project Python: {expected}", flush=True)
    raise SystemExit(subprocess.call([expected, os.path.abspath(__file__), *sys.argv[1:]]))


if __name__ == "__main__":
    _reexec_with_project_python()
    if os.environ.get("AEGIS_REEXEC_TEST") == "1":
        print(f"[PYTHON] Re-exec test interpreter: {sys.executable}", flush=True)
        raise SystemExit(0)
    runpy.run_path(ASYNC_FUSION, run_name="__main__")

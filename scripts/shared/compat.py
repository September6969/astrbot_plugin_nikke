# SPDX-License-Identifier: GPL-3.0-or-later
"""旧脚本入口的唯一转发实现，不创建子进程。"""
import importlib
from pathlib import Path
import runpy
import sys


def dispatch(name: str, namespace: dict, target: str) -> None:
    if name == "__main__":
        path = Path(__file__).resolve().parents[1].joinpath(*target.split('.')).with_suffix('.py')
        runpy.run_path(str(path), run_name="__main__")
    else:
        package = name.rpartition('.')[0] or "scripts"
        module = importlib.import_module(package + '.' + target)
        sys.modules[name] = module
        namespace.update(vars(module))

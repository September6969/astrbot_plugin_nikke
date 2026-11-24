"""无运行时的 Spine 本地预检查；不加载动画、不下载或执行外部代码。"""

# 支持直接执行、模块导入及从其他工作目录调用。
import sys as _bootstrap_sys
from pathlib import Path as _BootstrapPath
_bootstrap_root = _BootstrapPath(__file__).resolve().parents[2]
for _bootstrap_path in (_bootstrap_root.parent, _bootstrap_root):
    if str(_bootstrap_path) not in _bootstrap_sys.path:
        _bootstrap_sys.path.insert(0, str(_bootstrap_path))

import argparse
import json
from pathlib import Path

# 实现位于生产包 integrations.spine.bundle_inspection（AUD-016）；此处仅保留 CLI
# 薄入口，并重新导出原有名称，保证旧脚本与测试的导入路径继续可用。
from astrbot_plugin_nikke.integrations.spine.bundle_inspection import (  # noqa: F401
    _binary_spine_version,
    _read_binary_string,
    _read_varint,
    inspect,
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--atlas", required=True, type=Path)
    parser.add_argument("--skeleton", required=True, type=Path)
    parser.add_argument("--expected-version")
    args = parser.parse_args()
    try:
        print(json.dumps(inspect(args.atlas, args.skeleton, args.expected_version), ensure_ascii=False, indent=2))
    except (OSError, ValueError, TypeError, AttributeError):
        print(json.dumps({"status": "INSPECTION_FAILED", "runtime_executed": False}))
        raise SystemExit(1)


if __name__ == "__main__":
    main()

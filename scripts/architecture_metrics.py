"""采集整仓重构的静态结构指标，并提供可重复的架构门禁输入。"""

from __future__ import annotations

import argparse
import ast
import json
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any


PLAN_THRESHOLDS = {
    "main.py": 700,
    "adapters/astrbot/command_runtime.py": 400,
    "core/asset_manager.py": 300,
    "ui/t2i_payloads.py": 100,
    "features/calendar/schedule_service.py": 450,
    "features/announcement/service.py": 450,
    "core/container.py": 350,
}
PUBLIC_METHOD_MAX_LOGICAL_STATEMENTS = 20

RESOURCE_TYPES = ("NikkeStore", "BlaBlaClient", "AssetManager", "ClientSession")
FEATURE_FORBIDDEN_ROOTS = {
    "astrbot",
    "ui",
    "PIL",
    "sqlite3",
    "httpx",
    "aiohttp",
    "requests",
}
UI_FORBIDDEN_ROOTS = {"sqlite3", "httpx", "aiohttp", "requests"}
EXCLUDED_DIRS = {".git", ".venv", "venv", "__pycache__", "node_modules", "build", "dist"}
CLASS_GETATTR_ALLOWLIST = {
    ("features/announcement/service.py", "AnnouncementService", "_COMPAT_STATE")
}
ADAPTER_INFRASTRUCTURE_FORBIDDEN_ROOTS = {
    "integrations",
    "sqlite3",
    "httpx",
    "aiohttp",
    "requests",
    "urllib3",
}
ADAPTER_CORE_FORBIDDEN_PREFIXES = (
    "core.storage",
    "core.container",
    "core.providers",
)


def _module_name(root: Path, path: Path) -> str:
    relative = path.relative_to(root).with_suffix("")
    parts = list(relative.parts)
    if parts and parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts) if parts else "__root__"


def _is_package_initializer(path: Path) -> bool:
    return path.name == "__init__.py"


def _import_records(tree: ast.AST, path: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                records.append(
                    {
                        "path": path,
                        "line": node.lineno,
                        "kind": "import",
                        "module": alias.name,
                        "names": [alias.asname or alias.name.split(".")[0]],
                    }
                )
        elif isinstance(node, ast.ImportFrom):
            records.append(
                {
                    "path": path,
                    "line": node.lineno,
                    "kind": "from",
                    "module": node.module or "",
                    "level": node.level,
                    "names": [alias.name for alias in node.names],
                }
            )
    return records


def _normalise_module_name(name: str) -> str:
    prefix = "astrbot_plugin_nikke."
    if name.startswith(prefix):
        return name[len(prefix) :]
    if name == "astrbot_plugin_nikke":
        return "__root__"
    return name


def _resolve_import_targets(
    record: dict[str, Any],
    current_module: str,
    package_initializer: bool,
    known_modules: set[str],
) -> list[str]:
    if record["kind"] == "import":
        module = _normalise_module_name(record["module"])
        candidates = [module]
    else:
        if record.get("level", 0):
            current_parts = [] if current_module == "__root__" else current_module.split(".")
            package_parts = current_parts if package_initializer else current_parts[:-1]
            trim = record["level"] - 1
            if trim > len(package_parts):
                return []
            base_parts = package_parts[: len(package_parts) - trim]
            module_parts = record["module"].split(".") if record["module"] else []
            base_parts.extend(part for part in module_parts if part)
            base = ".".join(base_parts) or "__root__"
        else:
            base = _normalise_module_name(record["module"])
        candidates = []
        if base in known_modules:
            candidates.append(base)
        for imported in record["names"]:
            if imported == "*":
                continue
            candidate = f"{base}.{imported}" if base != "__root__" else imported
            if candidate in known_modules:
                candidates.append(candidate)
        if not candidates and base in known_modules:
            candidates.append(base)
    return sorted({candidate for candidate in candidates if candidate in known_modules})


def _statement_count(function: ast.FunctionDef | ast.AsyncFunctionDef) -> int:
    """按 AST 语句节点计数，递归统计分支，但不把格式空行当作逻辑。"""
    count = 0

    def visit(node: ast.AST) -> None:
        nonlocal count
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            return
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            if isinstance(node.value.value, str):
                return
        if isinstance(node, ast.stmt):
            count += 1
        for child in ast.iter_child_nodes(node):
            visit(child)

    for statement in function.body:
        visit(statement)
    return count


def _complexity_score(function: ast.FunctionDef | ast.AsyncFunctionDef) -> int:
    branch_types = (
        ast.If,
        ast.For,
        ast.AsyncFor,
        ast.While,
        ast.Try,
        ast.IfExp,
        ast.BoolOp,
        ast.comprehension,
    )
    return sum(1 for node in ast.walk(function) if isinstance(node, branch_types))


def _is_allowlisted_class_getattr(
    path: str, class_node: ast.ClassDef, method: ast.FunctionDef | ast.AsyncFunctionDef
) -> bool:
    """仅允许公告 facade 以显式状态名集合保留历史状态访问。"""
    if (path, class_node.name, "_COMPAT_STATE") not in CLASS_GETATTR_ALLOWLIST:
        return False
    has_membership_guard = any(
        isinstance(node, ast.Compare)
        and isinstance(node.left, ast.Name)
        and node.left.id == "name"
        and any(isinstance(operator, ast.In) for operator in node.ops)
        and any(
            isinstance(value, ast.Attribute)
            and isinstance(value.value, ast.Name)
            and value.value.id == "self"
            and value.attr == "_COMPAT_STATE"
            for value in node.comparators
        )
        for node in ast.walk(method)
    )
    raises_attribute_error = any(
        isinstance(node, ast.Raise)
        and node.exc is not None
        and (
            isinstance(node.exc, ast.Name)
            and node.exc.id == "AttributeError"
            or isinstance(node.exc, ast.Call)
            and isinstance(node.exc.func, ast.Name)
            and node.exc.func.id == "AttributeError"
        )
        for node in ast.walk(method)
    )
    return has_membership_guard and raises_attribute_error


def classify_module_shape(tree: ast.Module, path: str) -> dict[str, Any]:
    """标记空转发、通配符导入和动态模块属性，防止以薄壳绕过门禁。"""
    effective: list[ast.stmt] = []
    star_imports: list[int] = []
    dynamic_getattr: list[int] = []
    class_getattrs: list[dict[str, Any]] = []
    for node in tree.body:
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            if isinstance(node.value.value, str):
                continue
        if isinstance(node, ast.ImportFrom) and any(alias.name == "*" for alias in node.names):
            star_imports.append(node.lineno)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "__getattr__":
            dynamic_getattr.append(node.lineno)
        effective.append(node)

    for class_node in (node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)):
        for member in class_node.body:
            if not isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if member.name != "__getattr__":
                continue
            allowlisted = _is_allowlisted_class_getattr(path, class_node, member)
            class_getattrs.append(
                {
                    "class": class_node.name,
                    "line": member.lineno,
                    "allowlisted": allowlisted,
                }
            )

    forwarder_nodes = (ast.Import, ast.ImportFrom, ast.Assign, ast.AnnAssign, ast.Pass)
    has_import = any(isinstance(node, (ast.Import, ast.ImportFrom)) for node in effective)
    is_forwarder = (
        has_import
        and bool(effective)
        and all(isinstance(node, forwarder_nodes) for node in effective)
    )
    return {
        "path": path,
        "empty_forwarder": is_forwarder,
        "star_import_lines": star_imports,
        "module_getattr_lines": dynamic_getattr,
        "class_getattrs": class_getattrs,
        "broad_class_getattrs": [
            item for item in class_getattrs if not item["allowlisted"]
        ],
    }


def _command_runtime_responsibilities(
    tree: ast.Module, path: str
) -> list[dict[str, Any]]:
    """验证命令 runtime 只负责宿主路由，不编排领域、网络或展示实现。"""
    if path != "adapters/astrbot/command_runtime.py":
        return []
    violations: list[dict[str, Any]] = []
    forbidden_roots = {"features", "integrations", "ui", "core.storage"}
    forbidden_attributes = {
        "services",
        "store",
        "client",
        "asset_manager",
        "character_application",
        "raid_application",
        "campaign_application",
        "daily_application",
        "renderer",
        "character_renderer",
        "campaign_renderer",
        "raid_renderer",
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module.startswith("."):
                continue
            if any(module == root or module.startswith(root + ".") for root in forbidden_roots):
                violations.append(
                    {"line": node.lineno, "symbol": module, "reason": "domain-or-presentation-import"}
                )
        elif isinstance(node, ast.Attribute) and node.attr in forbidden_attributes:
            violations.append(
                {"line": node.lineno, "symbol": node.attr, "reason": "direct-orchestration-access"}
            )
    return violations


def _character_card_retirement_violations(
    root: Path, production_sources: dict[str, str]
) -> list[dict[str, Any]]:
    """阻止已退役的单角色 Pillow/classic 实现重新进入生产路径。"""
    violations: list[dict[str, Any]] = []
    legacy_module = root / "ui" / "renderers" / "character.py"
    if legacy_module.exists():
        violations.append(
            {
                "reason": "legacy-renderer-module",
                "path": "ui/renderers/character.py",
            }
        )

    for path, source in sorted(production_sources.items()):
        for line_number, line in enumerate(source.splitlines(), 1):
            if "CharacterCardRenderer" in line:
                violations.append(
                    {
                        "reason": "legacy-renderer-reference",
                        "path": path,
                        "line": line_number,
                    }
                )
            if "character_card_layout" in line:
                if path == "core/config.py" and line.strip() == (
                    'normalized.pop("character_card_layout", None)'
                ):
                    continue
                violations.append(
                    {
                        "reason": "legacy-layout-decision",
                        "path": path,
                        "line": line_number,
                    }
                )
            if '"classic"' in line.casefold() or "'classic'" in line.casefold():
                violations.append(
                    {
                        "reason": "classic-card-mode-literal",
                        "path": path,
                        "line": line_number,
                    }
                )

    schema_path = root / "_conf_schema.json"
    if schema_path.is_file():
        try:
            schema = json.loads(schema_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            schema = {}
        if "character_card_layout" in schema:
            violations.append(
                {
                    "reason": "legacy-layout-config-exposed",
                    "path": "_conf_schema.json",
                }
            )
    return violations


def _adapter_infrastructure_imports(
    path: str, records: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """拒绝 AstrBot adapter 直接拥有网络、数据库或 composition 实现。"""
    if not path.startswith("adapters/"):
        return []
    violations = []
    for record in records:
        module = _normalise_module_name(record["module"])
        root = module.split(".", 1)[0]
        if (
            root in ADAPTER_INFRASTRUCTURE_FORBIDDEN_ROOTS
            or any(module == prefix or module.startswith(prefix + ".")
                   for prefix in ADAPTER_CORE_FORBIDDEN_PREFIXES)
        ):
            violations.append(
                {
                    "path": path,
                    "line": record["line"],
                    "module": module,
                    "names": record["names"],
                }
            )
    return violations


def _strongly_connected_components(graph: dict[str, set[str]]) -> list[list[str]]:
    index = 0
    stack: list[str] = []
    on_stack: set[str] = set()
    indices: dict[str, int] = {}
    lowlinks: dict[str, int] = {}
    components: list[list[str]] = []

    def visit(node: str) -> None:
        nonlocal index
        indices[node] = index
        lowlinks[node] = index
        index += 1
        stack.append(node)
        on_stack.add(node)
        for target in sorted(graph.get(node, set())):
            if target not in indices:
                visit(target)
                lowlinks[node] = min(lowlinks[node], lowlinks[target])
            elif target in on_stack:
                lowlinks[node] = min(lowlinks[node], indices[target])
        if lowlinks[node] == indices[node]:
            component: list[str] = []
            while True:
                member = stack.pop()
                on_stack.remove(member)
                component.append(member)
                if member == node:
                    break
            if len(component) > 1 or node in graph.get(node, set()):
                components.append(sorted(component))

    for node in sorted(graph):
        if node not in indices:
            visit(node)
    return sorted(components)


def _public_imports(tree: ast.Module) -> dict[str, Any]:
    imported: list[dict[str, str]] = []
    explicit_exports: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name != "*":
                    imported.append(
                        {
                            "module": node.module or "",
                            "name": alias.name,
                            "asname": alias.asname or alias.name,
                        }
                    )
        elif isinstance(node, ast.Import):
            for alias in node.names:
                imported.append(
                    {"module": alias.name, "name": alias.name, "asname": alias.asname or alias.name}
                )
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any(isinstance(target, ast.Name) and target.id == "__all__" for target in targets):
                value = node.value
                if isinstance(value, (ast.List, ast.Tuple, ast.Set)):
                    explicit_exports.extend(
                        element.value
                        for element in value.elts
                        if isinstance(element, ast.Constant) and isinstance(element.value, str)
                    )
    return {
        "imports": sorted(imported, key=lambda item: (item["module"], item["name"], item["asname"])),
        "__all__": sorted(set(explicit_exports)),
    }


def _git_value(root: Path, *arguments: str) -> str | None:
    try:
        completed = subprocess.run(
            ["git", "-C", str(root), *arguments],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return completed.stdout.strip()


def _source_paths(root: Path) -> list[Path]:
    paths: list[Path] = []
    for path in root.rglob("*.py"):
        relative_parts = path.relative_to(root).parts
        if any(part in EXCLUDED_DIRS for part in relative_parts):
            continue
        paths.append(path)
    return sorted(paths)


def collect_metrics(root: Path) -> dict[str, Any]:
    root = root.resolve()
    paths = _source_paths(root)
    module_for_path = {path: _module_name(root, path) for path in paths}
    known_modules = set(module_for_path.values())
    trees: dict[Path, ast.Module] = {}
    sources: dict[Path, str] = {}
    syntax_errors: list[dict[str, Any]] = []
    for path in paths:
        relative = path.relative_to(root).as_posix()
        source = path.read_text(encoding="utf-8")
        sources[path] = source
        try:
            trees[path] = ast.parse(source, filename=relative)
        except SyntaxError as error:
            syntax_errors.append(
                {"path": relative, "line": error.lineno, "message": error.msg}
            )

    internal_edges: set[tuple[str, str]] = set()
    graph: dict[str, set[str]] = {module: set() for module in known_modules}
    imports: list[dict[str, Any]] = []
    public_import_inventory: dict[str, Any] = {}
    forwarders: list[dict[str, Any]] = []
    star_imports: list[dict[str, Any]] = []
    dynamic_getattrs: list[dict[str, Any]] = []
    class_getattrs: list[dict[str, Any]] = []
    function_metrics: list[dict[str, Any]] = []
    plugin_methods: list[dict[str, Any]] = []
    resource_constructors: dict[str, set[str]] = defaultdict(set)
    task_creators: set[str] = set()
    composition_definitions: dict[str, set[str]] = defaultdict(set)
    feature_dependency_violations: list[dict[str, Any]] = []
    ui_dependency_violations: list[dict[str, Any]] = []
    main_business_imports: list[dict[str, Any]] = []
    profile_flags: list[dict[str, Any]] = []
    adapter_domain_imports: list[dict[str, Any]] = []
    adapter_infrastructure_imports: list[dict[str, Any]] = []
    adapter_resource_constructions: list[dict[str, Any]] = []
    command_runtime_responsibilities: list[dict[str, Any]] = []

    for path, tree in trees.items():
        relative = path.relative_to(root).as_posix()
        module = module_for_path[path]
        package_initializer = _is_package_initializer(path)
        source_imports = _import_records(tree, relative)
        imports.extend(source_imports)
        adapter_infrastructure_imports.extend(
            _adapter_infrastructure_imports(relative, source_imports)
        )
        shape = classify_module_shape(tree, relative)
        if shape["empty_forwarder"] and not package_initializer:
            forwarders.append(shape)
        star_imports.extend(
            {"path": relative, "line": line} for line in shape["star_import_lines"]
        )
        dynamic_getattrs.extend(
            {"path": relative, "line": line} for line in shape["module_getattr_lines"]
        )
        class_getattrs.extend(
            {"path": relative, **item} for item in shape["class_getattrs"]
        )
        command_runtime_responsibilities.extend(
            {"path": relative, **item}
            for item in _command_runtime_responsibilities(tree, relative)
        )
        if package_initializer:
            public_import_inventory[relative] = _public_imports(tree)

        for record in source_imports:
            raw_module = record["module"]
            policy_module = _normalise_module_name(raw_module)
            root_name = policy_module.split(".")[0] if policy_module else ""
            if relative.startswith("features/") and (
                root_name in FEATURE_FORBIDDEN_ROOTS
                or policy_module.startswith("core.storage")
                or policy_module.startswith("core.container")
            ):
                feature_dependency_violations.append(record)
            if relative.startswith("ui/") and (
                root_name in UI_FORBIDDEN_ROOTS
                or policy_module.startswith("core.storage")
                or "NikkeStore" in record["names"]
            ):
                ui_dependency_violations.append(record)
            if relative == "main.py" and (
                root_name in {"features", "ui", "integrations"}
                or policy_module.startswith("core.storage")
            ):
                main_business_imports.append(record)
            if relative.startswith("adapters/") and (
                root_name == "features"
                and any(
                    part in {"service", "builder", "resolver", "registry"}
                    for part in policy_module.split(".")
                )
            ):
                adapter_domain_imports.append(record)

            targets = _resolve_import_targets(
                record, module, package_initializer, known_modules
            )
            for target in targets:
                if target != module:
                    internal_edges.add((module, target))
                    graph[module].add(target)

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                complexity = _complexity_score(node)
                statements = _statement_count(node)
                function_metrics.append(
                    {
                        "path": relative,
                        "name": node.name,
                        "line": node.lineno,
                        "logical_statements": statements,
                        "complexity_hint": complexity,
                    }
                )
            if isinstance(node, ast.Call):
                call_name = node.func.id if isinstance(node.func, ast.Name) else (
                    node.func.attr if isinstance(node.func, ast.Attribute) else ""
                )
                if call_name in RESOURCE_TYPES and not relative.startswith(("tests/", "scripts/")):
                    resource_constructors[call_name].add(relative)
                    if relative.startswith("adapters/"):
                        adapter_resource_constructions.append(
                            {"path": relative, "line": node.lineno, "symbol": call_name}
                        )
                if call_name == "create_task" and not relative.startswith(("tests/", "scripts/")):
                    task_creators.add(relative)
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name in {"ServiceContainer", "create_container"}:
                    composition_definitions[node.name].add(relative)

        for node in tree.body:
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                if any(
                    isinstance(target, ast.Name) and target.id == "profile_application_enabled"
                    for target in targets
                ):
                    profile_flags.append({"path": relative, "line": node.lineno})
        if relative == "_conf_schema.json" or relative.startswith("core/") or relative == "main.py":
            if "profile_application_enabled" in sources[path]:
                profile_flags.append({"path": relative, "line": None})
        if relative == "main.py":
            for node in ast.walk(tree):
                if not isinstance(node, ast.ClassDef) or node.name != "NikkePlugin":
                    continue
                for member in node.body:
                    if not isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        continue
                    if member.name.startswith("_") or member.name in {"terminate", "close"}:
                        continue
                    plugin_methods.append(
                        {
                            "name": member.name,
                            "line": member.lineno,
                            "logical_statements": _statement_count(member),
                            "complexity_hint": _complexity_score(member),
                        }
                    )

    config_schema = root / "_conf_schema.json"
    if config_schema.exists():
        schema_data = json.loads(config_schema.read_text(encoding="utf-8"))
        if "profile_application_enabled" in schema_data:
            profile_flags.append({"path": "_conf_schema.json", "line": None})
    profile_flags = sorted(
        { (item["path"], item["line"]) for item in profile_flags },
        key=lambda item: (item[0], item[1] or 0),
    )
    profile_flags = [{"path": path, "line": line} for path, line in profile_flags]

    line_metrics: dict[str, dict[str, int]] = {}
    for relative, maximum in PLAN_THRESHOLDS.items():
        path = root / relative
        if path.exists():
            source = path.read_text(encoding="utf-8")
            line_metrics[relative] = {
                "lines": len(source.splitlines()),
                "bytes": path.stat().st_size,
                "limit": maximum,
            }
        else:
            line_metrics[relative] = {"lines": 0, "bytes": 0, "limit": maximum}

    production_paths = [
        path for path in paths if not path.relative_to(root).as_posix().startswith(("tests/", "scripts/"))
    ]
    production_sources = {
        path.relative_to(root).as_posix(): sources[path] for path in production_paths
    }
    module_sizes = sorted(
        (
            {
                "path": path.relative_to(root).as_posix(),
                "lines": len(sources[path].splitlines()),
                "bytes": path.stat().st_size,
            }
            for path in production_paths
        ),
        key=lambda item: (-item["lines"], item["path"]),
    )
    cycles = _strongly_connected_components(graph)
    resource_owner_map = {
        name: sorted(owners) for name, owners in sorted(resource_constructors.items())
    }
    duplicate_resource_owners = {
        name: owners for name, owners in resource_owner_map.items() if len(owners) > 1
    }
    root_owners = {
        name: sorted(paths) for name, paths in sorted(composition_definitions.items())
    }

    violations: list[dict[str, Any]] = []
    for path, item in line_metrics.items():
        if item["lines"] > item["limit"]:
            violations.append(
                {
                    "category": "hotspot_size",
                    "path": path,
                    "actual": item["lines"],
                    "limit": item["limit"],
                }
            )
    for method in plugin_methods:
        if method["logical_statements"] > PUBLIC_METHOD_MAX_LOGICAL_STATEMENTS:
            violations.append(
                {
                    "category": "main_command_size",
                    "path": "main.py",
                    "symbol": method["name"],
                    "line": method["line"],
                    "actual": method["logical_statements"],
                    "limit": PUBLIC_METHOD_MAX_LOGICAL_STATEMENTS,
                }
            )
    violations.extend(
        {"category": "feature_dependency_direction", **record}
        for record in feature_dependency_violations
    )
    violations.extend(
        {"category": "ui_dependency_direction", **record}
        for record in ui_dependency_violations
    )
    violations.extend(
        {"category": "main_business_import", **record}
        for record in main_business_imports
    )
    violations.extend(
        {"category": "adapter_domain_import", **record}
        for record in adapter_domain_imports
    )
    violations.extend(
        {"category": "adapter_infrastructure_import", **record}
        for record in adapter_infrastructure_imports
    )
    violations.extend(
        {"category": "adapter_resource_construction", **record}
        for record in adapter_resource_constructions
    )
    violations.extend(
        {"category": "command_runtime_responsibility", **record}
        for record in command_runtime_responsibilities
    )
    character_card_retirement_violations = _character_card_retirement_violations(
        root, production_sources
    )
    violations.extend(
        {"category": "legacy_character_card", **record}
        for record in character_card_retirement_violations
    )
    for resource, owners in duplicate_resource_owners.items():
        violations.append(
            {"category": "duplicate_resource_owner", "resource": resource, "owners": owners}
        )
    for name, owners in root_owners.items():
        if len(owners) != 1 or owners != ["core/container.py"]:
            violations.append(
                {"category": "composition_root_owner", "symbol": name, "owners": owners}
            )
    for item in star_imports:
        if not item["path"].startswith(("tests/", "scripts/")):
            violations.append({"category": "star_import", **item})
    for item in dynamic_getattrs:
        if not item["path"].startswith(("tests/", "scripts/")):
            violations.append({"category": "dynamic_module_forwarder", **item})
    for item in class_getattrs:
        if not item["allowlisted"] and not item["path"].startswith(("tests/", "scripts/")):
            violations.append({"category": "broad_class_dynamic_forwarder", **item})
    for item in forwarders:
        if not item["path"].startswith(("tests/", "scripts/")):
            violations.append({"category": "empty_forwarder_module", "path": item["path"]})
    if profile_flags:
        violations.append(
            {"category": "default_off_or_legacy_route", "references": profile_flags}
        )
    for component in cycles:
        violations.append({"category": "import_cycle", "modules": component})
    for error in syntax_errors:
        violations.append({"category": "python_syntax_error", **error})

    functions = sorted(
        function_metrics,
        key=lambda item: (-item["complexity_hint"], -item["logical_statements"], item["path"], item["line"]),
    )
    return {
        "schema_version": 1,
        "repository": root.name,
        "head_sha": _git_value(root, "rev-parse", "HEAD"),
        "git_dirty": bool(_git_value(root, "status", "--porcelain=v1")),
        "source_file_count": len(paths),
        "production_module_count": len(production_paths),
        "hotspots": line_metrics,
        "largest_production_modules": module_sizes[:25],
        "plugin_public_methods": sorted(plugin_methods, key=lambda item: item["name"]),
        "functions_by_complexity": functions[:50],
        "import_edge_count": len(internal_edges),
        "import_edges": [
            {"from": source, "to": target} for source, target in sorted(internal_edges)
        ],
        "import_cycles": cycles,
        "public_imports": dict(sorted(public_import_inventory.items())),
        "container_definitions": root_owners,
        "resource_constructor_owners": resource_owner_map,
        "background_task_creation_paths": sorted(task_creators),
        "feature_dependency_violations": feature_dependency_violations,
        "ui_dependency_violations": ui_dependency_violations,
        "main_business_imports": main_business_imports,
        "adapter_domain_imports": adapter_domain_imports,
        "adapter_infrastructure_imports": adapter_infrastructure_imports,
        "empty_forwarder_modules": forwarders,
        "star_imports": star_imports,
        "dynamic_module_getattrs": dynamic_getattrs,
        "class_getattrs": class_getattrs,
        "adapter_resource_constructions": adapter_resource_constructions,
        "command_runtime_responsibilities": command_runtime_responsibilities,
        "character_card_retirement_violations": character_card_retirement_violations,
        "profile_route_flag_references": profile_flags,
        "syntax_errors": syntax_errors,
        "gate_violations": violations,
        "gate_violation_counts": dict(
            sorted(
                (category, sum(1 for item in violations if item["category"] == category))
                for category in {item["category"] for item in violations}
            )
        ),
    }


def compare_metrics(baseline: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    """按稳定字段生成前后对比，不把测试数量变化伪装成架构变化。"""
    baseline_sizes = baseline.get("hotspots", {})
    current_sizes = current.get("hotspots", {})
    size_delta = {
        path: {
            "before_lines": baseline_sizes.get(path, {}).get("lines", 0),
            "after_lines": current_sizes.get(path, {}).get("lines", 0),
            "delta_lines": current_sizes.get(path, {}).get("lines", 0)
            - baseline_sizes.get(path, {}).get("lines", 0),
        }
        for path in sorted(set(baseline_sizes) | set(current_sizes))
    }
    before_cycles = {tuple(component) for component in baseline.get("import_cycles", [])}
    after_cycles = {tuple(component) for component in current.get("import_cycles", [])}
    before_violations = baseline.get("gate_violation_counts", {})
    after_violations = current.get("gate_violation_counts", {})
    return {
        "baseline_head_sha": baseline.get("head_sha"),
        "current_head_sha": current.get("head_sha"),
        "hotspot_line_deltas": size_delta,
        "production_module_count_delta": current.get("production_module_count", 0)
        - baseline.get("production_module_count", 0),
        "import_edge_count_delta": current.get("import_edge_count", 0)
        - baseline.get("import_edge_count", 0),
        "cycles_removed": [list(item) for item in sorted(before_cycles - after_cycles)],
        "cycles_added": [list(item) for item in sorted(after_cycles - before_cycles)],
        "gate_violation_count_deltas": {
            category: after_violations.get(category, 0) - before_violations.get(category, 0)
            for category in sorted(set(before_violations) | set(after_violations))
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path, help="将 JSON 指标写到指定路径")
    parser.add_argument("--baseline", type=Path, help="附加与该指标文件的结构对比")
    parser.add_argument("--check", action="store_true", help="有架构门禁违规时返回非零")
    args = parser.parse_args(argv)

    metrics = collect_metrics(args.root)
    if args.baseline:
        baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
        metrics["comparison"] = compare_metrics(baseline, metrics)
    payload = json.dumps(metrics, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8", newline="\n")
    else:
        sys.stdout.write(payload)
    return 1 if args.check and metrics["gate_violations"] else 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Find out which Home Assistant deprecations affect this integration, before users do.

Home Assistant announces removals a year or more ahead of time, but only ever tells the *user* --
in their log, once the integration touches the deprecated thing. Waiting for someone to paste that
log into an issue is late and noisy, so this script goes looking instead. It runs two passes,
because neither alone is enough:

- The static pass reads every ``from homeassistant... import X`` in the integration and asks the
  live Home Assistant module whether ``X`` is deprecated (core tags them as ``_DEPRECATED_X``); the
  same for ``SomeEnum.MEMBER``, which core tags in ``SomeEnum.__deprecated__``. This sees
  deprecations in code the tests never run.
- The runtime pass runs the test suite under ``scripts/deprecation_pytest_plugin.py``, capturing the
  warnings core actually logs. This sees deprecated *calls* and behaviours, which no import scan can
  spot, and it fails loudly if a new Home Assistant breaks the integration outright.

Run against the newest Home Assistant (see ``.github/workflows/deprecations.yml``), the two together
answer "what will break, and when" while there is still time to act.

Usage:
    python scripts/check_deprecations.py [--json out.json] [--markdown out.md] [--skip-tests]

Exits 0 when nothing was found, 1 when there are findings (so a workflow step can branch on it).
"""

from __future__ import annotations

import argparse
import ast
import importlib
import json
import os
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
INTEGRATION_DIR = REPO_ROOT / "custom_components" / "frigidaire"
DEPRECATED_PREFIX = "_DEPRECATED_"
# Tail of the pytest output kept in the report when the suite fails; enough to identify the failure
# without pasting a whole run into a GitHub issue.
PYTEST_OUTPUT_LINES = 60


@dataclass
class Finding:
    """One deprecated thing the integration uses."""

    kind: str  # "constant", "enum member" or "runtime"
    name: str
    detail: str
    replacement: str | None = None
    breaks_in: str | None = None
    locations: list[str] = field(default_factory=list)

    @property
    def sort_key(self) -> tuple[tuple[int, ...], str, str]:
        """Order by what breaks soonest, with unannounced removals last.

        Versions are compared numerically so 2026.9 sorts before 2026.10.
        """
        if not self.breaks_in:
            return ((9999,), self.kind, self.name)
        parts = tuple(int(part) for part in self.breaks_in.split(".") if part.isdigit())
        return (parts or (9999,), self.kind, self.name)


def ha_version() -> str:
    """Return the Home Assistant version the scan ran against."""
    from homeassistant.const import __version__

    return __version__


def _describe_marker(marker: object) -> tuple[str | None, str | None]:
    """Return (replacement, breaks_in) from one of core's deprecation marker objects.

    Core has several marker types (``DeprecatedConstant``, ``DeprecatedConstantEnum``,
    ``DeprecatedAlias``, ``DeferredDeprecatedAlias``) and may add more, so read what is there
    instead of matching on type: everything carries ``breaks_in_ha_version``, and the replacement is
    either a ``replacement`` string or an ``enum`` member to name.
    """
    breaks_in = getattr(marker, "breaks_in_ha_version", None)
    replacement = getattr(marker, "replacement", None)
    if replacement is None and (member := getattr(marker, "enum", None)) is not None:
        replacement = f"{type(member).__name__}.{member.name}"
    return replacement, breaks_in


def _import_module(name: str) -> object | None:
    """Import a Home Assistant module, or return None if it no longer exists.

    A module that has gone away is a breakage rather than a deprecation; the runtime pass reports it
    as a test failure, so there is nothing to add here.
    """
    try:
        return importlib.import_module(name)
    except ImportError:
        return None


def _module_attribute(module: object, name: str) -> object | None:
    """Read an attribute without tripping core's deprecation warning for it."""
    return vars(module).get(name)


def _relative(path: Path) -> Path:
    """Return `path` relative to the repo, for locations that read the same as a GitHub link."""
    try:
        return path.relative_to(REPO_ROOT)
    except ValueError:
        return path


def scan_source(path: Path) -> list[Finding]:
    """Report the deprecated constants and enum members one source file uses."""
    findings: list[Finding] = []
    tree = ast.parse(path.read_text(), filename=str(path))
    relative = _relative(path)
    # Local name -> the Home Assistant object it refers to, so attribute accesses further down the
    # file can be resolved back to the enum or module they came from.
    imported: dict[str, object] = {}

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if not node.module or not node.module.startswith("homeassistant"):
                continue
            module = _import_module(node.module)
            if module is None:
                continue
            for alias in node.names:
                imported[alias.asname or alias.name] = _module_attribute(module, alias.name)
                marker = _module_attribute(module, f"{DEPRECATED_PREFIX}{alias.name}")
                if marker is None:
                    continue
                replacement, breaks_in = _describe_marker(marker)
                findings.append(
                    Finding(
                        kind="constant",
                        name=f"{node.module}.{alias.name}",
                        detail=f"`{alias.name}` imported from `{node.module}` is deprecated.",
                        replacement=replacement,
                        breaks_in=breaks_in,
                        # `alias.lineno` points at the imported name itself, which in a
                        # parenthesised import is not the line the `from` sits on.
                        locations=[f"{relative}:{alias.lineno}"],
                    )
                )
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("homeassistant"):
                    imported[alias.asname or alias.name] = _import_module(alias.name)

    findings.extend(_scan_attributes(tree, imported, relative))
    return findings


def _scan_attributes(tree: ast.AST, imported: dict[str, object], relative: Path) -> list[Finding]:
    """Report `Something.MEMBER` accesses where core has marked MEMBER deprecated.

    Covers both enums built with core's ``EnumWithDeprecatedMembers`` metaclass (which records
    ``__deprecated__``) and module aliases such as ``import homeassistant.const as const``.
    """
    findings: list[Finding] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Attribute) or not isinstance(node.value, ast.Name):
            continue
        owner = imported.get(node.value.id)
        if owner is None:
            continue

        # Enum member deprecations: {"MEMBER": (replacement, breaks_in_version)}.
        deprecated_members = getattr(owner, "__deprecated__", None)
        if isinstance(deprecated_members, dict) and node.attr in deprecated_members:
            replacement, breaks_in = deprecated_members[node.attr]
            findings.append(
                Finding(
                    kind="enum member",
                    name=f"{getattr(owner, '__name__', node.value.id)}.{node.attr}",
                    detail=f"`{node.value.id}.{node.attr}` is a deprecated enum member.",
                    replacement=replacement,
                    breaks_in=breaks_in,
                    locations=[f"{relative}:{node.lineno}"],
                )
            )
            continue

        # Module aliases: the deprecation marker lives beside the constant in the module.
        marker = vars(owner).get(f"{DEPRECATED_PREFIX}{node.attr}") if hasattr(owner, "__dict__") else None
        if marker is not None and getattr(owner, "__name__", "").startswith("homeassistant"):
            replacement, breaks_in = _describe_marker(marker)
            findings.append(
                Finding(
                    kind="constant",
                    name=f"{owner.__name__}.{node.attr}",
                    detail=f"`{node.value.id}.{node.attr}` is deprecated.",
                    replacement=replacement,
                    breaks_in=breaks_in,
                    locations=[f"{relative}:{node.lineno}"],
                )
            )
    return findings


def static_scan(directory: Path = INTEGRATION_DIR) -> list[Finding]:
    """Scan the whole integration, merging duplicate findings into one entry per deprecated thing."""
    merged: dict[tuple[str, str], Finding] = {}
    for path in sorted(directory.rglob("*.py")):
        for finding in scan_source(path):
            key = (finding.kind, finding.name)
            if existing := merged.get(key):
                existing.locations.extend(finding.locations)
            else:
                merged[key] = finding
    for finding in merged.values():
        finding.locations = sorted(set(finding.locations))
    return list(merged.values())


def run_tests(report_path: Path) -> tuple[list[Finding], int, str]:
    """Run the test suite under the recording plugin.

    Returns the runtime findings, pytest's exit code, and the tail of its output.
    """
    env = dict(os.environ)
    # pytest resolves `-p` plugin names before it applies the `pythonpath` ini setting, so put the
    # repo on the path ourselves.
    env["PYTHONPATH"] = os.pathsep.join(filter(None, [str(REPO_ROOT), env.get("PYTHONPATH", "")]))
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-p",
            "scripts.deprecation_pytest_plugin",
            f"--deprecation-report={report_path}",
        ],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    output = (result.stdout + result.stderr).strip()
    findings = []
    if report_path.exists():
        for entry in json.loads(report_path.read_text()):
            findings.append(
                Finding(
                    kind="runtime",
                    name=entry["message"],
                    detail=entry["message"],
                    breaks_in=entry.get("breaks_in"),
                    locations=[entry.get("logger", "")],
                )
            )
    tail = "\n".join(output.splitlines()[-PYTEST_OUTPUT_LINES:])
    return findings, result.returncode, tail


def render_markdown(result: dict) -> str:
    """Render the report as the body of a GitHub issue."""
    lines = [
        f"Scanned against **Home Assistant {result['ha_version']}** on {result['scanned_at']}.",
        "",
    ]

    static_findings = [Finding(**f) for f in result["static_findings"]]
    if static_findings:
        lines += [
            "### Deprecated constants and enum members in use",
            "",
            "| What | Kind | Use instead | Removed in | Where |",
            "| --- | --- | --- | --- | --- |",
        ]
        for finding in sorted(static_findings, key=lambda f: f.sort_key):
            where = ", ".join(f"`{location}`" for location in finding.locations)
            lines.append(
                f"| `{finding.name}` | {finding.kind} | `{finding.replacement or '?'}` "
                f"| {finding.breaks_in or 'unannounced'} | {where} |"
            )
        lines.append("")

    runtime_findings = [Finding(**f) for f in result["runtime_findings"]]
    if runtime_findings:
        lines += ["### Deprecation warnings logged during the test run", ""]
        for finding in sorted(runtime_findings, key=lambda f: f.sort_key):
            lines.append(f"- {finding.detail}")
        lines.append("")

    if result["tests_ran"] and result["pytest_exit_code"] != 0:
        lines += [
            "### The test suite does not pass against this Home Assistant",
            "",
            "This usually means a deprecation has already turned into a removal.",
            "",
            "```",
            result["pytest_output"],
            "```",
            "",
        ]

    if not lines[2:]:
        lines.append("No deprecated Home Assistant APIs are in use. :tada:")
    return "\n".join(lines).strip() + "\n"


def build_result(skip_tests: bool, report_path: Path) -> dict:
    """Run both passes and return the combined report."""
    runtime_findings: list[Finding] = []
    exit_code = 0
    output = ""
    if not skip_tests:
        runtime_findings, exit_code, output = run_tests(report_path)

    result = {
        "ha_version": ha_version(),
        "scanned_at": datetime.now(UTC).strftime("%Y-%m-%d"),
        "static_findings": [asdict(f) for f in sorted(static_scan(), key=lambda f: f.sort_key)],
        "runtime_findings": [asdict(f) for f in sorted(runtime_findings, key=lambda f: f.sort_key)],
        "tests_ran": not skip_tests,
        "pytest_exit_code": exit_code,
        "pytest_output": output,
    }
    # Recorded rather than left to the exit code: a caller reading the JSON cannot tell an exit
    # status of 1 that means "found something" from one that means the scan itself blew up.
    result["has_findings"] = has_findings(result)
    return result


def has_findings(result: dict) -> bool:
    """Return whether the run turned up anything worth opening an issue about."""
    return bool(
        result["static_findings"]
        or result["runtime_findings"]
        or (result["tests_ran"] and result["pytest_exit_code"] != 0)
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--json", type=Path, help="Write the raw report here.")
    parser.add_argument("--markdown", type=Path, help="Write the rendered report here.")
    parser.add_argument("--skip-tests", action="store_true", help="Only run the static import scan.")
    parser.add_argument(
        "--runtime-report",
        type=Path,
        default=Path("deprecation-runtime.json"),
        help="Where the pytest plugin drops its raw findings.",
    )
    args = parser.parse_args()

    result = build_result(args.skip_tests, args.runtime_report)
    markdown = render_markdown(result)

    if args.json:
        args.json.write_text(json.dumps(result, indent=2) + "\n")
    if args.markdown:
        args.markdown.write_text(markdown)
    print(markdown)

    return 1 if result["has_findings"] else 0


if __name__ == "__main__":
    raise SystemExit(main())

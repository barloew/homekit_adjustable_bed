"""Bring HomeKit Bed up to date with the latest Adjustable Bed release.

Usage:
    python tools/sync_adjustable_bed.py              # latest release, then run the checks
    python tools/sync_adjustable_bed.py --ref v4.2.2 # a specific tag (or branch)
    python tools/sync_adjustable_bed.py --check      # only report whether a newer release exists
    python tools/sync_adjustable_bed.py --since v4.0.2  # compare with an older release
    python tools/sync_adjustable_bed.py --offline    # rebuild from tests/fixtures (no network)
    python tools/sync_adjustable_bed.py --bump minor # also bump the version for a release

Steps:
1. Find the latest release tag of kristofferR/ha-adjustable-bed (git ls-remote).
2. Read the release with a blobless git clone in .cache/ (`git show <tag>:<path>`). Nothing
   from Adjustable Bed is imported or executed: const.py and detection.py are parsed with
   `ast`, the translations with `json`, services.yaml with `yaml.safe_load`.
3. Compare the release with the previous sync (tests/fixtures/adjustable_bed.json; on the first
   run with the release before it): bed types, controllable entities, timed_move motors and
   actions that were added, removed or renamed.
4. Process it in the integration:
   - every entity is classified by detection.py (rule, keyword or fallback); controls without a
     rule are reported for review;
   - field and caption names in en.json/nl.json/strings.json (gen_control_translations.py);
   - TIMED_MOTORS in const.py from the timed_move action;
   - the fixture that tests/test_adjustable_bed_sync.py checks the integration against.
5. Update the documentation: docs/SUPPORTED_BEDS.md, the tested version in README.md and an
   entry in CHANGELOG.md.
6. Run ruff, pyright and pytest (skip with --no-checks).

The report is printed and written to .cache/sync_report.md (the pull request text of the
scheduled workflow).
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import shutil
import subprocess
import sys
import textwrap
from collections import Counter
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

REPO_URL = "https://github.com/kristofferR/ha-adjustable-bed"
UPSTREAM = "custom_components/adjustable_bed"
CACHE = ROOT / ".cache"
CLONE = CACHE / "ha-adjustable-bed"
FIXTURE = ROOT / "tests" / "fixtures" / "adjustable_bed.json"
BEDS_DOC = ROOT / "docs" / "SUPPORTED_BEDS.md"
README = ROOT / "README.md"
CHANGELOG = ROOT / "CHANGELOG.md"
CONST = ROOT / "custom_components" / "homekit_bed" / "const.py"
MANIFEST = ROOT / "custom_components" / "homekit_bed" / "manifest.json"
PYPROJECT = ROOT / "pyproject.toml"
REPORT = CACHE / "sync_report.md"

CONTROL_DOMAINS = ("button", "cover", "light", "number", "select", "switch", "climate")
VERSION_MARK = re.compile(
    r"<!-- adjustable-bed-version -->.*?<!-- /adjustable-bed-version -->", re.DOTALL
)
TAG_RE = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")


# --------------------------------------------------------------------------- git


def _git(*args: str, cwd: Path | None = None) -> str:
    result = subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True, timeout=600
    )
    return result.stdout


def release_tags() -> list[str]:
    """Release tags (vX.Y.Z, no pre-releases), oldest first."""
    out = _git("ls-remote", "--tags", "--refs", REPO_URL)
    tags = [line.rsplit("/", 1)[-1] for line in out.splitlines()]
    tags = [t for t in tags if TAG_RE.match(t)]

    def version_key(tag: str) -> tuple[int, int, int]:
        match = TAG_RE.match(tag)
        assert match
        return int(match[1]), int(match[2]), int(match[3])

    return sorted(tags, key=version_key)


def ensure_clone() -> None:
    """Blobless clone in .cache: history and trees only, file contents on demand."""
    if (CLONE / ".git").exists():
        _git("fetch", "--quiet", "--tags", "--force", "origin", cwd=CLONE)
        return
    CLONE.parent.mkdir(parents=True, exist_ok=True)
    _git("clone", "--quiet", "--filter=blob:none", "--no-checkout", REPO_URL, str(CLONE))


def _show(ref: str, path: str) -> str:
    return _git("show", f"{ref}:{path}", cwd=CLONE)


def _ls(ref: str, path: str) -> list[str]:
    out = _git("ls-tree", "--name-only", f"{ref}:{path}", cwd=CLONE)
    return out.split()


# ------------------------------------------------------------------- extraction


def _bed_type_constants(tree: ast.Module) -> dict[str, str]:
    """BED_TYPE_* = "value" assignments (annotated or not)."""
    found: dict[str, str] = {}
    for node in tree.body:
        target = value = None
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            target, value = node.target.id, node.value
        elif (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
        ):
            target, value = node.targets[0].id, node.value
        if (
            target
            and target.startswith("BED_TYPE_")
            and isinstance(value, ast.Constant)
            and isinstance(value.value, str)
        ):
            found[target] = value.value
    return found


def _assigned(tree: ast.Module, name: str) -> ast.expr | None:
    for node in tree.body:
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.target.id == name:
                return node.value
        elif isinstance(node, ast.Assign):
            if any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
                return node.value
    return None


def extract(ref: str) -> dict[str, Any]:
    """What HomeKit Bed needs to know about one Adjustable Bed release."""
    const_tree = ast.parse(_show(ref, f"{UPSTREAM}/const.py"))
    constants = _bed_type_constants(const_tree)
    detection_tree = ast.parse(_show(ref, f"{UPSTREAM}/detection.py"))
    for name, value in _bed_type_constants(detection_tree).items():
        constants.setdefault(name, value)

    def resolve(node: ast.expr) -> str | None:
        if isinstance(node, ast.Name):
            return constants.get(node.id)
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        return None

    bed_types: dict[str, str] = {}
    supported = _assigned(const_tree, "SUPPORTED_BED_TYPES")
    if isinstance(supported, (ast.List, ast.Tuple)):
        for element in supported.elts:
            if value := resolve(element):
                bed_types[value] = value
    names = _assigned(detection_tree, "BED_TYPE_DISPLAY_NAMES")
    if isinstance(names, ast.Dict):
        for key_node, value_node in zip(names.keys, names.values, strict=True):
            key = resolve(key_node) if key_node is not None else None
            if key and isinstance(value_node, ast.Constant) and isinstance(value_node.value, str):
                bed_types[key] = value_node.value
    if not bed_types:
        raise SystemExit("No bed types found: the Adjustable Bed layout changed, update extract()")

    translations = json.loads(_show(ref, f"{UPSTREAM}/translations/en.json"))
    entities = {
        domain: {key: str(info.get("name") or key) for key, info in sorted(entries.items())}
        for domain, entries in sorted(translations.get("entity", {}).items())
        if domain in CONTROL_DOMAINS
    }

    services = yaml.safe_load(_show(ref, f"{UPSTREAM}/services.yaml")) or {}
    motor_field = services.get("timed_move", {}).get("fields", {}).get("motor", {})
    options = motor_field.get("selector", {}).get("select", {}).get("options", [])
    timed_motors = [o["value"] if isinstance(o, dict) else str(o) for o in options]

    manifest = json.loads(_show(ref, f"{UPSTREAM}/manifest.json"))
    return {
        "ref": ref,
        "version": manifest.get("version", ref.removeprefix("v")),
        "commit": _git("rev-list", "-n", "1", ref, cwd=CLONE).strip(),
        "bed_types": dict(sorted(bed_types.items())),
        "timed_motors": timed_motors,
        "services": sorted(services),
        "bed_guides": sorted(n.removesuffix(".md") for n in _ls(ref, "docs/beds")),
        "entities": entities,
    }


def upstream_translations(ref: str) -> Path:
    """Adjustable Bed's en.json of that release, for the name generator."""
    path = CACHE / f"adjustable_bed_en_{ref}.json"
    path.write_text(_show(ref, f"{UPSTREAM}/translations/en.json"))
    return path


# ------------------------------------------------------------------- comparison


def _flat(snapshot: dict[str, Any]) -> dict[str, str]:
    return {
        f"{domain}.{key}": name
        for domain, entries in snapshot.get("entities", {}).items()
        for key, name in entries.items()
    }


def compare(old: dict[str, Any] | None, new: dict[str, Any]) -> dict[str, Any]:
    old = old or {}
    old_beds, new_beds = old.get("bed_types", {}), new["bed_types"]
    old_ents, new_ents = _flat(old), _flat(new)
    added = sorted(set(new_ents) - set(old_ents))
    removed = sorted(set(old_ents) - set(new_ents))
    # Same name, other key: probably renamed (options of users still use the old key).
    by_name = {(k.split(".")[0], new_ents[k]): k for k in added}
    renamed = []
    for key in removed:
        candidate = by_name.get((key.split(".")[0], old_ents[key]))
        if candidate:
            renamed.append((key, candidate))
    return {
        "from": old.get("version"),
        "to": new["version"],
        "beds_added": {k: new_beds[k] for k in sorted(set(new_beds) - set(old_beds))},
        "beds_removed": {k: old_beds[k] for k in sorted(set(old_beds) - set(new_beds))},
        "beds_renamed": {
            k: (old_beds[k], new_beds[k])
            for k in sorted(set(old_beds) & set(new_beds))
            if old_beds[k] != new_beds[k]
        },
        "entities_added": added,
        "entities_removed": removed,
        "entities_renamed": renamed,
        "names_changed": sorted(
            k for k in set(old_ents) & set(new_ents) if old_ents[k] != new_ents[k]
        ),
        "motors_added": [m for m in new["timed_motors"] if m not in old.get("timed_motors", [])],
        "motors_removed": [m for m in old.get("timed_motors", []) if m not in new["timed_motors"]],
        "services_added": sorted(set(new["services"]) - set(old.get("services", []))),
    }


def classification(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    """How HomeKit Bed maps every controllable entity of the release."""
    from custom_components.homekit_bed.detection import classify

    rows = []
    for domain, entries in snapshot["entities"].items():
        for key, name in entries.items():
            control = classify(domain, key)
            if control is None:
                continue
            rows.append(
                {
                    "domain": domain,
                    "key": key,
                    "base": control.base,
                    "name": name,
                    "hk_type": control.hk_type,
                    "group": control.group,
                    "exposed": control.exposed,
                    "source": control.source,
                }
            )
    return rows


def known_control_ids() -> set[str]:
    """Control ids that already have a name in the integration's en.json."""
    data = json.loads((CONST.parent / "translations" / "en.json").read_text())
    sections = data["options"]["step"]["controls"]["sections"]
    skip = ("captions", "display", "layout", "timed", "add")
    return {
        key
        for name, section in sections.items()
        if name not in skip
        for key in section.get("data", {})
        if not key.startswith(("color_", "label_", "timed_"))
    }


# ------------------------------------------------------------------- processing


def write_fixture(snapshot: dict[str, Any]) -> None:
    FIXTURE.parent.mkdir(parents=True, exist_ok=True)
    FIXTURE.write_text(json.dumps(snapshot, indent=1, ensure_ascii=False) + "\n")


def update_timed_motors(motors: list[str]) -> bool:
    text = CONST.read_text()
    body = "".join(f'    "{m}",\n' for m in motors)
    new = re.sub(
        r"TIMED_MOTORS: Final = \(\n.*?\n\)\n",
        f"TIMED_MOTORS: Final = (\n{body})\n",
        text,
        count=1,
        flags=re.DOTALL,
    )
    if new == text:
        return False
    CONST.write_text(new)
    return True


GROUP_TITLES = {
    "positions": "Adjustable sections",
    "presets": "Quick actions",
    "massage": "Massage",
    "lighting": "Lighting",
    "climate": "Climate",
    "firmness": "Firmness",
    "settings": "Settings",
}
TYPE_TITLES = {
    "cover": "slider",
    "light": "lamp",
    "fan": "fan",
    "momentary": "push button",
    "switch": "switch",
    "select": "switch per option",
    "climate_fan": "fan (climate)",
}


def render_beds_doc(snapshot: dict[str, Any]) -> str:
    """docs/SUPPORTED_BEDS.md, generated from the fixture (tests check it is current)."""
    rows = classification(snapshot)
    lines = [
        "# Supported beds",
        "",
        "<!-- Generated by tools/sync_adjustable_bed.py; do not edit. -->",
        "",
        f"HomeKit Bed is checked against [Adjustable Bed]({REPO_URL}) "
        f"**v{snapshot['version']}** ([`{snapshot['commit'][:7]}`]"
        f"({REPO_URL}/commit/{snapshot['commit']})). Every bed type below works: HomeKit Bed "
        "reads the entities Adjustable Bed creates for your bed, so a bed only gets the controls "
        "it really has. See [Detection](DETECTION.md) for the rules.",
        "",
        f"## Bed types ({len(snapshot['bed_types'])})",
        "",
        "| Bed type | Adjustable Bed id |",
        "|---|---|",
    ]
    for key, name in sorted(snapshot["bed_types"].items(), key=lambda kv: kv[1].casefold()):
        if name == key:  # alias kept for older setups, without a display name
            name = f"{key.replace('_', ' ').title()} (older setups)"
        lines.append(f"| {name.replace('|', '/')} | `{key}` |")
    lines += [
        "",
        f"Bed guides: [Adjustable Bed docs/beds]({REPO_URL}/tree/{snapshot['ref']}/docs/beds).",
        "",
        f"## Controls ({len(rows)} entity keys)",
        "",
        "Per group of the form, the number of entity keys (side variants count separately) and "
        "how they are recognised: by a rule, by a word in the key (a vendor control without a "
        "rule, off by default) or only by its domain (off by default, under Settings).",
        "",
        "| Group | Keys | Rule | Keyword | Domain only | On by default |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for group, title in GROUP_TITLES.items():
        in_group = [r for r in rows if r["group"] == group]
        count = Counter(r["source"] for r in in_group)
        lines.append(
            f"| {title} | {len(in_group)} | {count['rule']} | {count['keyword']} | "
            f"{count['fallback']} | {sum(r['exposed'] for r in in_group)} |"
        )
    types = Counter(r["hk_type"] for r in rows)
    lines += [
        "",
        "HomeKit types: "
        + ", ".join(f"{TYPE_TITLES[t]} {n}" for t, n in sorted(types.items(), key=lambda x: -x[1]))
        + ".",
        "",
        "Timed adjustments (`adjustable_bed.timed_move`): "
        + ", ".join(f"`{m}`" for m in snapshot["timed_motors"])
        + ".",
        "",
        "## Controls without a rule",
        "",
        "Available under *Add controls*, off by default. A rule in `detection.py` can give them a "
        "better type or turn them on by default.",
        "",
        "| Key | Name in Adjustable Bed | Group | HomeKit type |",
        "|---|---|---|---|",
    ]
    seen: set[tuple[str, str]] = set()
    for row in sorted(
        (r for r in rows if r["source"] != "rule"),
        key=lambda r: (list(GROUP_TITLES).index(r["group"]), r["base"]),
    ):
        if (row["domain"], row["base"]) in seen:
            continue
        seen.add((row["domain"], row["base"]))
        name = row["name"].replace("|", "/").replace("{action}", "(action)")
        lines.append(
            f"| `{row['domain']}.{row['base']}` | {name} | {GROUP_TITLES[row['group']]} | "
            f"{TYPE_TITLES[row['hk_type']]} |"
        )
    return "\n".join(lines) + "\n"


def update_readme(version: str) -> bool:
    text = README.read_text()
    marker = (
        "<!-- adjustable-bed-version -->"
        f"[Adjustable Bed]({REPO_URL}) v4 with your bed set up (checked against "
        f"v{version}, see [Supported beds](docs/SUPPORTED_BEDS.md))"
        "<!-- /adjustable-bed-version -->"
    )
    if VERSION_MARK.search(text):
        new = VERSION_MARK.sub(marker, text, count=1)
    else:
        new = re.sub(
            r"\[Adjustable Bed\]\(https://github.com/kristofferR/ha-adjustable-bed\) v4 with "
            r"your bed set up",
            marker,
            text,
            count=1,
        )
    if new == text:
        return False
    README.write_text(new)
    return True


def changelog_lines(diff: dict[str, Any], rows: list[dict[str, Any]], new_ids: set[str]) -> list:
    beds = diff["beds_added"]
    lines = [f"- Synced with Adjustable Bed v{diff['to']}."]
    if beds:
        lines.append(f"  - New bed types: {', '.join(sorted(beds.values(), key=str.casefold))}.")
    if new_ids:
        by_group = Counter(
            r["group"]
            for r in rows
            if r["key"] in new_ids or f"{r['domain']}_{r['key']}" in new_ids
        )
        parts = ", ".join(f"{GROUP_TITLES[g].lower()} {n}" for g, n in by_group.most_common())
        lines.append(f"  - New controls named and grouped: {len(new_ids)} ({parts}).")
    if diff["motors_added"]:
        lines.append(
            "  - Timed adjustments for " + ", ".join(f"`{m}`" for m in diff["motors_added"]) + "."
        )
    return lines


def update_changelog(entry: list[str], version: str | None) -> None:
    text = CHANGELOG.read_text()
    heading = f"## {version}" if version else "## Unreleased"
    lines = []
    for line in entry:
        indent = line[: len(line) - len(line.lstrip())]
        text_ = line.strip().removeprefix("- ")
        lines.append(
            textwrap.fill(
                text_,
                width=100,
                initial_indent=f"{indent}- ",
                subsequent_indent=f"{indent}  ",
                break_on_hyphens=False,
            )
        )
    block = "\n".join(lines)
    # Replace an earlier sync line in the same section instead of stacking them.
    sync_re = re.compile(r"- Synced with Adjustable Bed v[^\n]*\n(?:  [^\n]*\n)*")
    if heading in text:
        start = text.index(heading) + len(heading) + 1
        end = text.find("\n## ", start)
        end = len(text) if end == -1 else end + 1
        section = text[start:end]
        section = sync_re.sub("", section).rstrip("\n")
        section = f"{section}\n{block}\n\n" if section.strip() else f"{block}\n\n"
        text = text[:start] + section + text[end:]
    else:
        first = text.index("\n## ") + 1
        text = text[:first] + f"{heading}\n{block}\n\n" + text[first:]
    CHANGELOG.write_text(text)


def bump_version(part: str) -> str:
    from custom_components.homekit_bed.const import VERSION

    major, minor, patch = (int(x) for x in VERSION.split("."))
    new = f"{major}.{minor + 1}.0" if part == "minor" else f"{major}.{minor}.{patch + 1}"
    for path, pattern, repl in (
        (MANIFEST, r'"version": "[^"]+"', f'"version": "{new}"'),
        (PYPROJECT, r'^version = "[^"]+"', f'version = "{new}"'),
        (CONST, r'^VERSION: Final = "[^"]+"', f'VERSION: Final = "{new}"'),
    ):
        text = path.read_text()
        updated = re.sub(pattern, repl, text, count=1, flags=re.MULTILINE)
        if updated == text:
            raise SystemExit(f"Version not found in {path.name}")
        path.write_text(updated)
    if "## Unreleased" in CHANGELOG.read_text():
        CHANGELOG.write_text(CHANGELOG.read_text().replace("## Unreleased", f"## {new}", 1))
    return new


# ------------------------------------------------------------------- report


def _bullets(items, fmt=str) -> list[str]:
    return [f"- {fmt(i)}" for i in items] or ["- none"]


def render_report(
    diff: dict[str, Any], rows: list[dict[str, Any]], new_ids: set[str], changed: list[str]
) -> str:
    new_review: list[tuple[str, str, str, str, str]] = []
    seen: set[tuple[str, str]] = set()
    for r in rows:
        is_new = r["key"] in new_ids or f"{r['domain']}_{r['key']}" in new_ids
        if r["source"] == "rule" or not is_new or (r["domain"], r["base"]) in seen:
            continue
        seen.add((r["domain"], r["base"]))
        new_review.append((r["domain"], r["base"], r["group"], r["source"], r["name"]))
    lines = [
        f"# Adjustable Bed sync: v{diff['from'] or '?'} → v{diff['to']}",
        "",
        f"## New bed types ({len(diff['beds_added'])})",
        *_bullets(diff["beds_added"].items(), lambda kv: f"{kv[1]} (`{kv[0]}`)"),
    ]
    if diff["beds_removed"]:
        lines += ["", "## Removed bed types", *_bullets(diff["beds_removed"].items())]
    if diff["beds_renamed"]:
        lines += [
            "",
            "## Renamed bed types",
            *_bullets(
                diff["beds_renamed"].items(), lambda kv: f"`{kv[0]}`: {kv[1][0]} → {kv[1][1]}"
            ),
        ]
    lines += [
        "",
        f"## Entities: {len(diff['entities_added'])} added, {len(diff['entities_removed'])} removed "
        f"since v{diff['from'] or '?'}",
        "",
        f"New to HomeKit Bed (no name in the form yet before this sync): {len(new_ids)}.",
    ]
    if diff["entities_renamed"]:
        lines += [
            "",
            "### Probably renamed keys (add a migration to `controls.migrate_renamed`)",
            *_bullets(diff["entities_renamed"], lambda p: f"`{p[0]}` → `{p[1]}`"),
        ]
    if diff["entities_removed"]:
        lines += [
            "",
            "### Removed keys (options that still use them are ignored)",
            *_bullets(diff["entities_removed"], lambda k: f"`{k}`"),
        ]
    lines += [
        "",
        "## Timed adjustments",
        f"- added: {', '.join(diff['motors_added']) or 'none'}",
        f"- removed: {', '.join(diff['motors_removed']) or 'none'}",
        "",
        f"New actions: {', '.join(f'`{s}`' for s in diff['services_added']) or 'none'}.",
        "",
        f"## Review: new controls without a rule ({len(new_review)})",
        "",
        "They work (off by default, under *Add controls*). Add a rule in `detection.py` with a "
        "test when one deserves a better type or should be on by default.",
        "",
        *_bullets(
            new_review,
            lambda r: f'`{r[0]}.{r[1]}` "{r[4]}": {GROUP_TITLES[r[2]]} ({r[3]})',
        ),
        "",
        "## Files changed",
        *_bullets(changed, lambda p: f"`{p}`"),
    ]
    return "\n".join(lines) + "\n"


# ------------------------------------------------------------------- checks


def run_checks() -> bool:
    py = sys.executable
    venv_bin = Path(py).parent
    steps: list[tuple[str, list[str]]] = []
    ruff = shutil.which("ruff", path=str(venv_bin)) or shutil.which("ruff")
    if ruff:
        steps += [
            ("ruff format", [ruff, "format", "custom_components", "tests", "tools"]),
            ("ruff check", [ruff, "check", "custom_components", "tests", "tools"]),
        ]
    else:
        print("ruff not installed: skipped (CI runs it)")
    pyright = shutil.which("pyright", path=str(venv_bin)) or shutil.which("pyright")
    if pyright:
        steps.append(
            ("pyright", [pyright, "--pythonpath", py, "custom_components", "tests"]),
        )
    else:
        print("pyright not installed: skipped (CI runs it)")
    steps.append(("pytest", [py, "-m", "pytest", "-q", "-p", "no:cacheprovider"]))
    ok = True
    for name, cmd in steps:
        result = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
        tail = (result.stdout + result.stderr).strip().splitlines()[-3:]
        print(f"{name}: {'ok' if result.returncode == 0 else 'FAILED'}")
        if result.returncode:
            ok = False
            print("\n".join(f"  {line}" for line in tail))
    return ok


# ------------------------------------------------------------------- main


def _changed_files() -> list[str]:
    try:
        out = _git("status", "--porcelain", cwd=ROOT)
    except subprocess.CalledProcessError, FileNotFoundError:
        return []
    return sorted(line[3:] for line in out.splitlines() if not line[3:].startswith(".cache"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--ref", help="tag or branch of Adjustable Bed (default: latest release)")
    parser.add_argument("--since", help="compare with this release instead of the last sync")
    parser.add_argument("--check", action="store_true", help="only report a newer release")
    parser.add_argument("--offline", action="store_true", help="rebuild from the fixture")
    parser.add_argument("--force", action="store_true", help="sync even if already current")
    parser.add_argument("--bump", choices=("patch", "minor"), help="bump the version")
    parser.add_argument("--no-checks", action="store_true", help="skip ruff, pyright and pytest")
    args = parser.parse_args(argv)

    previous = json.loads(FIXTURE.read_text()) if FIXTURE.exists() else None
    CACHE.mkdir(exist_ok=True)

    if args.offline:
        if previous is None:
            raise SystemExit("No fixture yet: run once without --offline")
        snapshot, baseline, translations = previous, previous, None
    else:
        tags = release_tags()
        ref = args.ref or tags[-1]
        if args.check:
            current = previous["ref"] if previous else None
            if current == ref:
                print(f"Up to date with Adjustable Bed {ref}")
                return 0
            print(f"Adjustable Bed {ref} is available (synced: {current or 'never'})")
            return 1
        if previous and previous["ref"] == ref and not args.force:
            print(f"Already synced with Adjustable Bed {ref} (use --force to redo)")
            return 0
        ensure_clone()
        snapshot = extract(ref)
        baseline = extract(args.since) if args.since else previous
        if baseline is None and ref in tags and tags.index(ref) > 0:
            baseline = extract(tags[tags.index(ref) - 1])
        translations = upstream_translations(ref)

    diff = compare(baseline, snapshot)
    before = known_control_ids()

    from tools import gen_control_translations

    if translations is None:
        translations = CACHE / "adjustable_bed_en_fixture.json"
        translations.write_text(
            json.dumps(
                {
                    "entity": {
                        d: {k: {"name": n} for k, n in e.items()}
                        for d, e in snapshot["entities"].items()
                    }
                }
            )
        )
    write_fixture(snapshot)
    gen_control_translations.main(str(translations))
    update_timed_motors(snapshot["timed_motors"])
    BEDS_DOC.write_text(render_beds_doc(snapshot))
    update_readme(snapshot["version"])

    rows = classification(snapshot)
    new_ids = known_control_ids() - before
    if not args.offline:
        update_changelog(changelog_lines(diff, rows, new_ids), None)
    version = bump_version(args.bump) if args.bump else None

    ok = True if args.no_checks else run_checks()
    report = render_report(diff, rows, new_ids, _changed_files())
    REPORT.write_text(report)
    print()
    print(report)
    if version:
        print(f"Version bumped to {version}")
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())

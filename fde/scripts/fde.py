#!/usr/bin/env python3
"""Local FDE resource tooling. Never executes prompts, models, or shell commands."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import sys
import zipfile

NAME = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
IGNORED = {".git", "__pycache__", ".pytest_cache"}
ENGINES = ("looper", "havoc-hackathon", "dark-factory")
HEADINGS = ("Workflow", "Boundaries", "Evaluation", "Delivery")


def safe_path(value):
    raw = Path(value).expanduser()
    if ".." in raw.parts:
        raise ValueError(f"parent traversal is not allowed: {value}")
    path = raw.absolute()
    for component in (*reversed(path.parents), path):
        if component.is_symlink():
            raise ValueError(f"symlink is not allowed: {component}")
    return path


def ignored(part):
    return part in IGNORED or part == ".ralph-loop" or part.startswith(".ralph-loop-")


def files(root):
    root = safe_path(root)
    if not root.is_dir():
        raise ValueError(f"missing directory: {root}")
    found = []
    for directory, dirs, names in os.walk(root, followlinks=False):
        for name in sorted(dirs + names):
            if ignored(name):
                continue
            path = safe_path(Path(directory) / name)
            mode = path.stat()
            if stat.S_ISREG(mode.st_mode):
                if mode.st_nlink != 1:
                    raise ValueError(f"multiply linked file: {path}")
                found.append(path)
            elif not stat.S_ISDIR(mode.st_mode):
                raise ValueError(f"nonregular resource: {path}")
        dirs[:] = sorted(d for d in dirs if not ignored(d))
    return sorted(found)


def text(path):
    path = safe_path(path)
    if not path.is_file() or path.stat().st_nlink != 1:
        raise ValueError(f"missing or unsafe file: {path}")
    return path.read_text(encoding="utf-8")


def description(value):
    if not value:
        raise ValueError("description is required")
    if value.startswith('"'):
        decoded = json.loads(value)
        if not isinstance(decoded, str) or not decoded.strip():
            raise ValueError("description must be a nonempty string")
    else:
        if (value[0] in "-?:,[]{}#&*!|>'%@`" or value[0].isdigit() or
                value.casefold() in {"null", "~", "true", "false", "yes", "no", "on", "off"} or
                re.search(r":(?:\s|$)|(?:^|\s)#", value)):
            raise ValueError("description must be plain prose or a JSON-quoted string")
        decoded = value
    if any(ord(character) < 32 for character in decoded):
        raise ValueError("description must be a single line without control characters")
    return decoded


def validate(root):
    root = safe_path(root)
    resources = files(root)
    content = text(root / "SKILL.md")
    front = re.match(r"\A---\n(.*?)\n---\n", content, re.S)
    if not front:
        raise ValueError("SKILL.md requires opening name/description frontmatter")
    fields = {}
    for line in front[1].splitlines():
        key, separator, value = line.partition(":")
        if not separator or key in fields or key not in {"name", "description"}:
            raise ValueError("use unique scalar name and description frontmatter")
        fields[key] = value.strip()
    name = fields.get("name", "")
    if not NAME.fullmatch(name) or len(name) > 64:
        raise ValueError("invalid skill name (lowercase kebab-case, max 64)")
    description(fields.get("description", ""))
    body = content[front.end():]
    if "FDE_CUSTOMIZE" in body:
        raise ValueError("scaffold is incomplete; replace its customization marker")
    for heading in HEADINGS:
        match = re.search(rf"^## {heading}\n(.*?)(?=^## |\Z)", body, re.M | re.S)
        if not match or not match[1].strip():
            raise ValueError(f"missing or empty section: {heading}")
    for target in re.findall(r"\[[^\]]+\]\(([^)]+)\)", body):
        if re.match(r"[a-zA-Z][a-zA-Z0-9+.-]*:", target) or target.startswith("#"):
            continue
        relative = Path(target.split("#", 1)[0])
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError(f"unsafe resource link: {target}")
        linked = safe_path(root / relative)
        if not linked.is_file():
            raise ValueError(f"missing linked resource: {target}")
    cases = json.loads(text(root / "eval-cases.json"))
    if not isinstance(cases, list) or not cases:
        raise ValueError("eval-cases.json must be a nonempty array")
    ids, kinds = set(), set()
    for case in cases:
        if not isinstance(case, dict):
            raise ValueError("evaluation cases must be objects")
        case_id, kind = case.get("id"), case.get("kind")
        if not isinstance(case_id, str) or not case_id.strip() or case_id in ids:
            raise ValueError("evaluation case IDs must be unique nonempty strings")
        if kind not in {"positive", "negative", "edge"}:
            raise ValueError("evaluation kind must be positive, negative, or edge")
        if not isinstance(case.get("input"), str) or not case["input"].strip():
            raise ValueError("evaluation input is required")
        expected = case.get("expected")
        if (not isinstance(expected, list) or not expected or
                any(not isinstance(item, str) or not item.strip() for item in expected)):
            raise ValueError("each case needs nonempty expected assertions")
        ids.add(case_id)
        kinds.add(kind)
    if kinds != {"positive", "negative", "edge"}:
        raise ValueError("positive, negative, and edge cases are all required")
    return {"name": name, "resources": len(resources), "cases": len(cases),
            "validation": "structural-only; behavior not executed"}


def scaffold(destination, name, objective):
    if not NAME.fullmatch(name) or len(name) > 64:
        raise ValueError("invalid skill name")
    if not objective.strip() or "\n" in objective or "\r" in objective:
        raise ValueError("objective must be a nonempty single line")
    parent = safe_path(destination)
    target = safe_path(parent / name)
    if target.exists():
        raise ValueError(f"destination exists; refusing overwrite: {target}")
    parent.mkdir(parents=True, exist_ok=True)
    target.mkdir()
    content = (
        f"---\nname: {name}\ndescription: {json.dumps(objective)}\n---\n\n"
        f"# {name}\n\n## Workflow\n\nFDE_CUSTOMIZE: implement {objective}\n\n"
        "## Boundaries\n\nDefine tools, permissions, and untrusted-input handling.\n\n"
        "## Evaluation\n\nExecute eval-cases.json and record actual observations.\n\n"
        "## Delivery\n\nDocument invocation, prerequisites, evidence, and recovery.\n"
    )
    (target / "SKILL.md").write_text(content, encoding="utf-8")
    cases = [{"id": kind, "kind": kind, "input": "", "expected": []}
             for kind in ("positive", "negative", "edge")]
    (target / "eval-cases.json").write_text(json.dumps(cases, indent=2) + "\n")
    return {"path": str(target), "status": "incomplete; customize before validation"}


def package(root, output):
    root, output = safe_path(root), safe_path(output)
    info = validate(root)
    if output.is_relative_to(root):
        raise ValueError("archive must be outside the skill tree")
    if output.exists():
        raise ValueError("archive exists; refusing overwrite")
    resources = files(root)
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in resources:
            archive.write(path, Path(info["name"]) / path.relative_to(root))
    return {"archive": str(output), "resources": len(resources)}


def manifest(root):
    root = safe_path(root)
    return {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in files(root)}


def install(root, skills_root):
    root, skills_root = safe_path(root), safe_path(skills_root)
    info = validate(root)
    target = safe_path(skills_root / info["name"])
    if target.exists():
        raise ValueError(f"destination exists; refusing overwrite: {target}")
    if target.is_relative_to(root) or root.is_relative_to(target):
        raise ValueError("source and installed trees must not overlap")
    resources = files(root)
    skills_root.mkdir(parents=True, exist_ok=True)
    target.mkdir()
    for path in resources:
        relative = path.relative_to(root)
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)
    verify_install(root, skills_root)
    return {"installed": str(target), "resources": len(resources)}


def verify_install(root, skills_root):
    info = validate(root)
    target = safe_path(Path(skills_root).expanduser() / info["name"])
    validate(target)
    if manifest(root) != manifest(target):
        raise ValueError("installed resource tree differs from source")
    return {"installed": str(target), "matches": True}


def doctor(skills_root):
    root = safe_path(skills_root)
    results = {}
    for engine in ENGINES:
        directory = root / engine
        required = ["SKILL.md"]
        if engine == "looper":
            required.append("scripts/pass-ledger.sh")
        if engine == "dark-factory":
            required.append("config.yml")
        missing = [name for name in required if not safe_path(directory / name).is_file()]
        results[engine] = {"path": str(directory), "missing": missing,
                           "status": "blocked" if missing else "present"}
    return {"engines": results, "ready": all(not v["missing"] for v in results.values()),
            "scope": "local files only; auth, models, isolation, and behavior not checked"}


def snapshot(root, installed, dependencies, artifacts=()):
    data = {"source": manifest(root),
            "environment": {"python": sys.version, "platform": sys.platform}}
    if installed:
        data["installed"] = manifest(installed)
    if dependencies:
        base = safe_path(dependencies)
        data["dependencies"] = {}
        for engine, names in {
            "looper": ("SKILL.md", "scripts/pass-ledger.sh"),
            "havoc-hackathon": ("SKILL.md",),
            "dark-factory": ("SKILL.md", "config.yml"),
        }.items():
            for name in names:
                path = safe_path(base / engine / name)
                data["dependencies"][f"{engine}/{name}"] = hashlib.sha256(
                    text(path).encode("utf-8")).hexdigest()
    if artifacts:
        data["artifacts"] = {}
        for value in artifacts:
            path = safe_path(value)
            if not path.is_file() or path.stat().st_nlink != 1:
                raise ValueError(f"missing or unsafe artifact: {path}")
            data["artifacts"][str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
    encoded = json.dumps(data, sort_keys=True, separators=(",", ":"))
    return {"fingerprint": hashlib.sha256(encoded.encode()).hexdigest(), "manifest": data}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("validate", "package", "install", "verify-install"):
        sub = commands.add_parser(command)
        sub.add_argument("root")
        if command == "package":
            sub.add_argument("--output", required=True)
        if command in {"install", "verify-install"}:
            sub.add_argument("--skills-root", default="~/.copilot/skills")
    sub = commands.add_parser("scaffold")
    sub.add_argument("--destination", required=True)
    sub.add_argument("--name", required=True)
    sub.add_argument("--objective", required=True)
    sub = commands.add_parser("doctor")
    sub.add_argument("--skills-root", default="~/.copilot/skills")
    sub = commands.add_parser("snapshot")
    sub.add_argument("--root", required=True)
    sub.add_argument("--installed")
    sub.add_argument("--dependencies")
    sub.add_argument("--artifact", action="append", default=[])
    args = parser.parse_args(argv)
    try:
        if args.command == "validate":
            result = validate(args.root)
        elif args.command == "scaffold":
            result = scaffold(args.destination, args.name, args.objective)
        elif args.command == "package":
            result = package(args.root, args.output)
        elif args.command in {"install", "verify-install"}:
            operation = install if args.command == "install" else verify_install
            result = operation(args.root, args.skills_root)
        elif args.command == "doctor":
            result = doctor(args.skills_root)
        else:
            result = snapshot(args.root, args.installed, args.dependencies, args.artifact)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 2 if args.command == "doctor" and not result["ready"] else 0
    except (ValueError, OSError, TypeError) as error:
        print(f"fde: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())

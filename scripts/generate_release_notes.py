"""Generate friendly GitHub release notes for CI-created releases."""

from __future__ import annotations

import argparse
import os
import subprocess
from pathlib import Path
from urllib.parse import quote

MAX_COMMITS = 25

SECTION_ORDER = [
    "✨ Highlights",
    "🩹 Fixes",
    "📚 Documentation",
    "🧪 Tests",
    "🔧 Maintenance",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kind", choices=["preview", "stable"], required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--base-tag", default="")
    parser.add_argument("--pr-number", default="")
    parser.add_argument("--head-ref", default="")
    parser.add_argument("--base-ref", default="")
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def git_lines(args: list[str]) -> list[str]:
    result = subprocess.run(
        ["git", *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def collect_commit_subjects(base_tag: str) -> list[str]:
    log_args = [
        "log",
        "--no-merges",
        f"--max-count={MAX_COMMITS + 1}",
        "--pretty=format:%s",
    ]
    if base_tag:
        log_args.append(f"{base_tag}..HEAD")

    try:
        subjects = git_lines(log_args)
    except subprocess.CalledProcessError:
        return []

    return [
        subject
        for subject in subjects
        if not subject.lower().startswith("chore(release):")
    ]


def section_for(subject: str) -> str:
    lowered = subject.lower()
    if lowered.startswith(("feat", "feature", "add ")):
        return "✨ Highlights"
    if lowered.startswith(("fix", "bug", "repair")):
        return "🩹 Fixes"
    if lowered.startswith(("doc", "readme")):
        return "📚 Documentation"
    if lowered.startswith(("test", "ci")):
        return "🧪 Tests"
    return "🔧 Maintenance"


def grouped_changes(subjects: list[str]) -> dict[str, list[str]]:
    groups = {section: [] for section in SECTION_ORDER}
    for subject in subjects[:MAX_COMMITS]:
        groups[section_for(subject)].append(subject)
    return groups


def markdown_changes(subjects: list[str], kind: str, pr_number: str) -> str:
    if not subjects:
        if kind == "preview" and pr_number:
            return f"- Preview build for pull request #{pr_number}."
        return "- Includes the latest validated changes since the previous release."

    lines: list[str] = []
    groups = grouped_changes(subjects)
    for section in SECTION_ORDER:
        section_subjects = groups[section]
        if not section_subjects:
            continue
        lines.append(f"### {section}")
        lines.extend(f"- {subject}" for subject in section_subjects)
        lines.append("")

    if len(subjects) > MAX_COMMITS:
        remaining = len(subjects) - MAX_COMMITS
        lines.append(f"_And {remaining} more validated change(s)._")

    return "\n".join(lines).strip()


def safe_cell(value: str) -> str:
    return value.replace("|", "\\|")


def link_targets(base_tag: str, tag: str) -> tuple[str, str, str]:
    repository = os.environ.get("GITHUB_REPOSITORY", "").strip()
    if not repository:
        return "", "", ""

    repository_url = f"https://github.com/{repository}"
    encoded_tag = quote(tag, safe="")
    source_url = f"{repository_url}/releases/tag/{encoded_tag}"
    if base_tag:
        encoded_base = quote(base_tag, safe="")
        compare_url = f"{repository_url}/compare/{encoded_base}...{encoded_tag}"
    else:
        compare_url = f"{repository_url}/commits/{encoded_tag}"
    return repository_url, compare_url, source_url


def badge_line(kind: str) -> str:
    release_badge = (
        "![Preview](https://img.shields.io/badge/release-preview-f59e0b)"
        if kind == "preview"
        else "![Stable](https://img.shields.io/badge/release-stable-2ea44f)"
    )
    return " ".join(
        [
            release_badge,
            "![CI](https://img.shields.io/badge/CI-lint%20%2B%20tests-2563eb)",
            "![Home Assistant](https://img.shields.io/badge/Home%20Assistant-2026.1%2B-41bdf5)",
        ]
    )


def snapshot_table(args: argparse.Namespace) -> str:
    release_type = "Preview prerelease" if args.kind == "preview" else "Stable release"
    base = f"`{args.base_tag}`" if args.base_tag else "Initial release"
    rows = [
        ("Version", f"`{args.version}`"),
        ("Type", release_type),
        ("Base", base),
        ("Validation", "`ruff` lint + full `pytest` suite"),
    ]

    if args.kind == "preview" and args.pr_number:
        rows.extend(
            [
                ("Pull request", f"#{args.pr_number}"),
                ("Branch", f"`{args.head_ref}` → `{args.base_ref}`"),
            ]
        )

    body = "\n".join(f"| {name} | {safe_cell(value)} |" for name, value in rows)
    return f"| Item | Details |\n| --- | --- |\n{body}"


def install_section(kind: str) -> str:
    if kind == "preview":
        return "\n".join(
            [
                "> ⚠️ Preview releases are intended for validation before "
                "they land in `main`.",
                "",
                "1. Download the source archive from this prerelease.",
                "2. Copy `custom_components/vigi_nvr` into a test Home "
                "Assistant instance.",
                "3. Restart Home Assistant and validate the PR scenario you "
                "care about.",
            ]
        )

    return "\n".join(
        [
            "1. In HACS, install or update `TP-Link VIGI NVR` from this release.",
            "2. Restart Home Assistant after updating.",
            "3. Confirm your VIGI entities and webhook sensors come back online.",
        ]
    )


def compose_notes(args: argparse.Namespace) -> str:
    subjects = collect_commit_subjects(args.base_tag)
    changes = markdown_changes(subjects, args.kind, args.pr_number)
    repository_url, compare_url, source_url = link_targets(args.base_tag, args.tag)
    title_icon = "🧪" if args.kind == "preview" else "🚀"
    title_suffix = " Preview" if args.kind == "preview" else ""
    intro = (
        "A preview build for hands-on validation before this work lands in `main`."
        if args.kind == "preview"
        else "A polished release for Home Assistant installations using "
        "TP-Link VIGI NVR."
    )

    links = []
    if compare_url:
        links.append(f"- [Compare changes]({compare_url})")
    if source_url:
        links.append(f"- [Source archive and assets]({source_url})")
    if repository_url:
        links.append(f"- [Repository]({repository_url})")

    return f"""# {title_icon} TP-Link VIGI NVR {args.tag}{title_suffix}

{badge_line(args.kind)}

{intro}

## 🌈 Release Snapshot

{snapshot_table(args)}

## ✨ What's Included

{changes}

## 🏡 Install Or Update

{install_section(args.kind)}

## ✅ Validation

- `python -m ruff check .`
- `python -m pytest`

## 🔗 Links

{chr(10).join(links) if links else "- Release source archive is attached by GitHub."}
"""


def main() -> None:
    args = parse_args()
    notes = compose_notes(args)
    args.output.write_text(notes, encoding="utf-8")


if __name__ == "__main__":
    main()

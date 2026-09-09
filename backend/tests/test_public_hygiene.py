"""Public-repository fixtures must be unmistakably synthetic."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from app.mock_seed import COORDINATORS, STUDENTS_WITH_PROFILES, STUDENTS_WITHOUT_PROFILES

ROOT = Path(__file__).resolve().parents[2]
E2E_CAST = ROOT / "frontend" / "e2e" / "lifecycle.spec.ts"
EMAIL = re.compile(r"(?i)\b[a-z0-9._%+-]+@([a-z0-9.-]+\.[a-z]{2,})\b")
SENSITIVE_SUFFIXES = {
    ".csv",
    ".dump",
    ".key",
    ".ods",
    ".p12",
    ".pem",
    ".pfx",
    ".sql",
    ".xls",
    ".xlsx",
}
SENSITIVE_NAME = re.compile(
    r"(?i)(credential|access[_. -]?key|pre[_. -]?registration|"
    r"student[_. -]?export|private[_. -]?doc)"
)


def public_files() -> list[Path]:
    output = subprocess.check_output(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=ROOT,
    )
    return [
        ROOT / raw.decode()
        for raw in output.split(b"\0")
        if raw and (ROOT / raw.decode()).is_file()
    ]


def test_public_fixture_emails_use_only_reserved_domains() -> None:
    unexpected: list[str] = []
    for path in public_files():
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for domain in EMAIL.findall(text):
            normalized = domain.lower()
            if not (
                normalized in {"example.com", "example.edu"}
                or normalized.endswith((".example.com", ".example.edu", ".example"))
            ):
                unexpected.append(f"{path.relative_to(ROOT)}: @{normalized}")
    assert unexpected == []


def test_public_tree_contains_no_sensitive_exports_or_private_keys() -> None:
    failures: list[str] = []
    for path in public_files():
        relative = path.relative_to(ROOT)
        if path.name == ".env" or path.suffix.lower() in SENSITIVE_SUFFIXES:
            failures.append(str(relative))
        elif SENSITIVE_NAME.search(path.name):
            failures.append(str(relative))
    assert failures == []


def test_demo_seed_uses_numbered_synthetic_identities() -> None:
    students = sorted(
        (*STUDENTS_WITH_PROFILES, *STUDENTS_WITHOUT_PROFILES),
        key=lambda student: student.email,
    )
    assert len(students) == 11
    for index, student in enumerate(students, start=1):
        suffix = f"{index:02d}"
        assert student.full_name == f"Demo Student {suffix}"
        assert student.email == f"demo.student{suffix}@example.edu"
        assert student.roll_number == f"990000{suffix}"

    assert len(COORDINATORS) == 2
    for index, coordinator in enumerate(COORDINATORS, start=1):
        suffix = f"{index:02d}"
        assert coordinator.full_name == f"Demo Coordinator {suffix}"
        assert coordinator.email == f"demo.coordinator{suffix}@example.edu"


def test_lifecycle_fixture_contains_only_synthetic_person_accounts() -> None:
    source = E2E_CAST.read_text(encoding="utf-8")
    institute_accounts = set(
        re.findall(r"[a-z0-9.]+@example[.]edu", source, flags=re.IGNORECASE)
    )
    expected = {"admin@example.edu", "demo.future@example.edu"}
    expected.update(f"demo.student{index:02d}@example.edu" for index in range(1, 12))
    expected.update(f"demo.coordinator{index:02d}@example.edu" for index in range(1, 3))
    assert institute_accounts == expected

    cast = source.split("const students = {", 1)[1].split("} as const;", 1)[0]
    for index in range(1, 12):
        suffix = f"{index:02d}"
        assert f'"demo.student{suffix}@example.edu", "Demo Student {suffix}"' in cast

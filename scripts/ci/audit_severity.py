"""Порог pip-audit (#5): падение только на уязвимостях high и critical.

pip-audit не сообщает серьёзность, поэтому она берётся из OSV по GHSA-идентификатору
(`database_specific.severity`: LOW, MODERATE, HIGH, CRITICAL). Если серьёзность узнать
нельзя (нет GHSA, OSV недоступен), находка считается high: проверка не пропускает
уязвимость из-за сбоя сети.

    python scripts/ci/audit_severity.py audit.json [audit.json ...]
"""

import json
import sys
import urllib.request
from pathlib import Path
from typing import Any

OSV_URL = "https://api.osv.dev/v1/vulns/{id}"
FAILING = {"HIGH", "CRITICAL"}


def osv_severity(ids: list[str]) -> str | None:
    for vuln_id in ids:
        if not vuln_id.startswith("GHSA-"):
            continue
        try:
            with urllib.request.urlopen(OSV_URL.format(id=vuln_id), timeout=20) as response:
                record: dict[str, Any] = json.load(response)
        except OSError:
            return None
        severity = record.get("database_specific", {}).get("severity")
        if isinstance(severity, str):
            return severity.upper()
    return None


def main(paths: list[str]) -> int:
    if not paths:
        print(__doc__)
        return 2
    failing = 0
    seen: set[tuple[str, str, str]] = set()
    for path in paths:
        report = json.loads(Path(path).read_text(encoding="utf-8"))
        for dep in report["dependencies"]:
            for vuln in dep.get("vulns", []):
                key = (dep["name"], dep["version"], vuln["id"])
                if key in seen:
                    continue
                seen.add(key)
                ids = [vuln["id"], *vuln.get("aliases", [])]
                severity = osv_severity(ids)
                level = severity or "UNKNOWN→HIGH"
                fix = ", ".join(vuln.get("fix_versions", [])) or "нет"
                print(f"{level:13} {dep['name']}=={dep['version']} {' '.join(ids)} fix: {fix}")
                if severity is None or severity in FAILING:
                    failing += 1
    if failing:
        print(f"::error::pip-audit: {failing} уязвимостей high/critical")
        return 1
    print(f"pip-audit: high/critical нет (всего находок: {len(seen)})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

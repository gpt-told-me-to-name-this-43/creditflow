"""Сверка демо-данных со спецификацией (issue #6): `python scripts/check_demo_data.py`.

Прогоняет закоммиченные фикстуры ext-sim через настоящий конвейер ядра
(категоризация → FeatureBuilder → RiskEngine → DecisionPolicy) и сравнивает с эталонами
C1–C7. Сама проверка — pytest-тест `api/tests/scoring/test_golden.py`: так она идёт и в CI
(`uv run pytest`), и локально одной командой, без второй копии ожиданий в скрипте.
"""

import subprocess
import sys
from pathlib import Path

API_DIR = Path(__file__).resolve().parent.parent / "api"

if __name__ == "__main__":
    cmd = ["uv", "run", "pytest", "-q", "tests/scoring/test_golden.py"]
    sys.exit(subprocess.call(cmd, cwd=API_DIR))

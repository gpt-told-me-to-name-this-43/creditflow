"""Версии ядра. Пишутся в `scoring_results.engine_version`, `decision_proposals.policy_version`
и входят в `inputs_hash`.

Правило: изменили порог, вес, формулу или правило категоризации — поднимите версию.
`tests/scoring/test_versions.py` хранит отпечаток порогов для каждой версии и падает,
если пороги поменялись без смены версии (критерий issue #6).
"""

ENGINE_VERSION = "risk-1.0.0"
POLICY_VERSION = "policy-1.0.0"
RULES_VERSION = "categorization-v1"

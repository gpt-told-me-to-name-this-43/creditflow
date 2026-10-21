# Alfa Smart Credit

MVP цифрового кредитного конвейера для малого бизнеса (хакатон «Умный кредитный кабинет предпринимателя»): клиент описывает цель кредита, детерминированный Python Risk Engine считает платёж, DSCR и балльный скоринг, Decision Policy формирует рекомендацию, кредитный менеджер принимает решение. Локальная LLM (Qwen через Ollama) только предзаполняет поля и объясняет уже рассчитанные результаты; без неё система работает через ручной ввод и шаблоны.

Все продукты, ставки, пороги и данные компаний — синтетические.

## Документация

- [`docs/design.md`](docs/design.md) — архитектура, Submit-конвейер, Risk Engine, правила Decision Policy, права менеджера, модель данных, API, диаграмма состояний, тестовые сценарии, план реализации.

## Целевой стек

React + TypeScript · Python 3.12+, FastAPI, Pydantic v2, SQLAlchemy 2.x, Alembic · PostgreSQL · Ollama + Qwen с открытыми весами · Docker Compose.

## PR-шаблоны

GitHub автоматически подставляет `.github/PULL_REQUEST_TEMPLATE.md` в новые pull requests. Для специальных шаблонов используйте параметр `template=` в URL создания PR:

- `https://github.com/OWNER/REPO/compare/main...feature/my-branch?expand=1&template=feature.md`
- `https://github.com/OWNER/REPO/compare/main...fix/my-branch?expand=1&template=bugfix.md`

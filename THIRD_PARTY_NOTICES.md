# Third-party model notices

CreditFlow использует модели через настроенный провайдер; веса моделей не входят в
репозиторий или Docker-образ. Replay содержит ответы на синтетические запросы и метаданные
провайдера. OpenAI-compatible означает протокол, а не обязательное использование моделей
OpenAI. Лицензии ниже проверены по опубликованным LICENSE в Hugging Face 2026-10-26.

| Модель / автор | Идентификатор OpenRouter | Источник весов | Лицензия |
|---|---|---|---|
| Qwen3-32B / Qwen (Alibaba Cloud) | `qwen/qwen3-32b` | [Qwen/Qwen3-32B](https://huggingface.co/Qwen/Qwen3-32B) | [Apache License 2.0](https://huggingface.co/Qwen/Qwen3-32B/blob/main/LICENSE) |
| Llama 3.3 70B Instruct / Meta | `meta-llama/llama-3.3-70b-instruct` | [meta-llama/Llama-3.3-70B-Instruct](https://huggingface.co/meta-llama/Llama-3.3-70B-Instruct) | [Llama 3.3 Community License Agreement](https://huggingface.co/meta-llama/Llama-3.3-70B-Instruct/blob/main/LICENSE) |
| gpt-oss-120b / OpenAI | `openai/gpt-oss-120b` | [openai/gpt-oss-120b](https://huggingface.co/openai/gpt-oss-120b) | [Apache License 2.0](https://huggingface.co/openai/gpt-oss-120b/blob/main/LICENSE) |

Модель стенда и сохранённых replay: Llama 3.3. Built with Llama.
Llama 3.3 is licensed under the Llama 3.3 Community License,
Copyright © Meta Platforms, Inc. All Rights Reserved.

Llama — модель с доступными весами и собственной лицензией; её условия отличаются от
Apache-2.0. Применяются также [Acceptable Use Policy](https://huggingface.co/meta-llama/Llama-3.3-70B-Instruct/blob/main/USE_POLICY.md)
и условия выбранного inference-провайдера. Этот файл не заменяет текст лицензий.
При распространении весов или производных материалов нужно сверять условия источника;
проект не заявляет лицензию MIT/Apache на чужие модели.

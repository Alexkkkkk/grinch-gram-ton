# Grok Autopilot для репозитория

Автономный агент: в простое анализирует репозиторий, правит баги, **перед PR
прогоняет тесты и откатывает изменения, если они краснеют**, консолидирует ветки.
Мерж — только через защиту ветки `main` (обязательные проверки
`Lint & Test (Python 3.11)` и `Docker Build Check`).

## Файлы

| Файл | Роль |
|---|---|
| `.github/workflows/grok-idle-audit.yml` | cron `0 */3 * * *` + вручную + `repository_dispatch: grok-audit` |
| `.github/workflows/grok-fix-issue.yml` | метка `grok-fix` или `/grok fix` в issue |
| `.github/workflows/grok-merge-branches.yml` | каждые 6 часов подтягивает ветки открытых PR к `main` |
| `scripts/grok_agent.py` | сам агент: контекст → Grok → **тест-гейт** → правки/откат |
| `scripts/setup_self_hosted_runner.sh` | установка self-hosted runner на 2.27.25.126 |
| `scripts/trigger_audit.sh` | `repository_dispatch` с сервера (cron/хук деплоя) |

## Установка (3 шага)

1. Смержить PR — файлы в ветке `grok/autopilot`.
2. Settings → Secrets and variables → Actions → **New repository secret**:
   `XAI_API_KEY` = ключ из https://console.x.ai
3. Settings → Actions → General → Workflow permissions →
   **Read and write permissions** + галочка **Allow GitHub Actions to create and approve pull requests**.

## Self-hosted runner на 2.27.25.126

На сервере (Ubuntu 22.04, есть docker/git/python3), от root:

```bash
REPO=Alexkkkkk/grinch-gram-ton GH_TOKEN=<PAT> \
  bash scripts/setup_self_hosted_runner.sh
```

Затем в GitHub: Settings → Secrets and variables → Actions → **Variables** →
`GROK_RUNNER` = имя ранера (например `632969.senko.network-gha`) c метками
`self-hosted,linux,x64,senko`. После этого все workflow пойдут на ваш сервер.

## Триггер по простою (repository_dispatch)

```bash
REPO=Alexkkkkk/grinch-gram-ton GH_TOKEN=<PAT> bash scripts/trigger_audit.sh
```

Cron на сервере (запуск аудита, когда нагрузка низкая):

```cron
0 3 * * * REPO=Alexkkkkk/grinch-gram-ton GH_TOKEN=<PAT> bash /opt/grok/trigger_audit.sh
```

## Тест-гейт

`grok_agent.py` сам определяет команду тестов:
`package.json` → `npm ci && npm test`; Python-проект → `pytest`;
иначе `Dockerfile` → `docker build`. Переопределение — переменная репозитория
`GROK_TEST_CMD`. Если тесты падают — все правки агента откатываются (`git checkout -- .`
+ `git clean -fd`), PR не открывается, в отчёте пишется причина.

## API

- Base URL: `https://api.x.ai/v1` (OpenAI-совместимый), `POST /chat/completions`
- Модели: `grok-4.6` (флагман, код), `grok-4.5`, `grok-code-fast-1` (дешёвая)

## Настройки

| Переменная | По умолчанию | Смысл |
|---|---|---|
| `GROK_MODEL` | `grok-4.6` | Модель Grok |
| `GROK_MODE` | `audit` | `audit` / `fix` |
| `GROK_TEST_GATE` | `1` | Откат правок при падении тестов |
| `GROK_TEST_CMD` | автодетект | Своя команда тестов |
| `GROK_MAX_FILES` | `60` | Файлов за прогон |
| `GROK_MAX_BYTES` | `150000` | Лимит контекста |
| `GROK_MAX_EDITS` | `25` | Макс. правок |

## Безопасность

- Авто-мержа нет: только PR, мерж — человек через защиту ветки.
- Тест-гейт откатывает всё, что ломает сборку.
- Пути с `..` отсекаются; файлы >20 КБ не читаются; секреты в модель не уходят.
- Backoff на 429/5xx, таймауты на шагах.

# Grok Autopilot для репозитория

Автономный агент, который в режиме простоя анализирует репозиторий, правит баги,
подтягивает конфиги CI и открывает Pull Request. Мерж — только через защиту ветки
`main` (в вашем репозитории уже включены обязательные проверки
`Lint & Test (Python 3.11)` и `Docker Build Check`).

## Что внутри
- `.github/workflows/grok-idle-audit.yml` — запуск каждые 3 часа (cron) и вручную.
- `.github/workflows/grok-fix-issue.yml` — по метке `grok-fix` или команде `/grok fix` в issue.
- `scripts/grok_agent.py` — сам агент (только stdlib, без зависимостей).

## Установка (3 шага)
1. Скопируйте папки `.github/` и `scripts/` в корень репозитория.
2. Добавьте секрет: Settings → Secrets and variables → Actions → **New repository secret**
   - Name: `XAI_API_KEY`
   - Value: ключ из https://console.x.ai
3. Settings → Actions → General → Workflow permissions → **Read and write permissions**
   и галочка **Allow GitHub Actions to create and approve pull requests**.

## API
- Base URL: `https://api.x.ai/v1` (OpenAI-совместимый)
- Эндпоинт: `POST /chat/completions`
- Модели: `grok-4.6` (флагман, код), `grok-4.5`, `grok-code-fast-1` (дешёвая кодовая).

## Настройки через env
| Переменная | По умолчанию | Смысл |
|---|---|---|
| `GROK_MODEL` | `grok-4.6` | Модель Grok |
| `GROK_MODE` | `audit` | `audit` / `fix` |
| `GROK_MAX_FILES` | `60` | Сколько файлов читать |
| `GROK_MAX_BYTES` | `150000` | Лимит контекста |
| `GROK_MAX_EDITS` | `25` | Макс. правок за прогон |

## Безопасность
- Ветка защищена, авто-мержа нет — всё идёт в PR.
- Секреты из репозитория не передаются в модель (только исходники).
- Повторы при 429/5xx с экспоненциальной задержкой.

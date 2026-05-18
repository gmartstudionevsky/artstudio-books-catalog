# ARTSTUDIO Books Catalog

Готовый комплект для сценария: Google Sheets = рабочий интерфейс отбора книг, GitHub Actions = движок парсинга, PDF-каталог = итоговая презентационная выгрузка.

## Что делает комплект

1. Берет ссылки из Google Sheets.
2. Автоматически приводит лист к рабочей структуре, если там пока просто список ссылок.
3. Парсит название, автора, цену, описание, наличие, тематику и 1–2 изображения.
4. Записывает результат обратно в таблицу, сохраняя исходные ссылки.
5. Формирует аккуратный PDF-каталог с кликабельными ссылками и изображениями.
6. Сохраняет PDF как GitHub Actions artifact и, при наличии `DRIVE_FOLDER_ID`, загружает PDF на Google Drive.

## Быстрый старт

### 1. Создайте репозиторий

Создайте пустой GitHub-репозиторий, например:

```text
artstudio-books-catalog
```

Загрузите в него все файлы из этого комплекта.

### 2. Подготовьте Google service account

1. Создайте проект в Google Cloud.
2. Включите Google Sheets API.
3. Если хотите загружать PDF на Google Drive, включите Google Drive API.
4. Создайте service account и скачайте JSON-ключ.
5. Откройте Google Sheets-файл и выдайте service account доступ `Editor` по email из JSON-ключа.

Текущий spreadsheet ID уже заложен в `.env.example`:

```text
1YbsObqu2pbSR3cSVPTRGvsZdvgCSxAluo5KAY8taNec
```

### 3. Добавьте GitHub Secrets

В GitHub: `Settings → Secrets and variables → Actions → New repository secret`.

Обязательные secrets:

```text
GOOGLE_SERVICE_ACCOUNT_JSON_B64
SPREADSHEET_ID
```

Опционально:

```text
DRIVE_FOLDER_ID
```

Как получить `GOOGLE_SERVICE_ACCOUNT_JSON_B64`:

macOS / Linux:

```bash
base64 -w0 service-account.json
```

Windows PowerShell:

```powershell
[Convert]::ToBase64String([IO.File]::ReadAllBytes("service-account.json")) | Set-Clipboard
```

### 4. Запустите workflow

GitHub → `Actions` → `Update books catalog` → `Run workflow`.

Параметры запуска:

- `force_refresh`: принудительно обновлять уже заполненные строки.
- `max_rows`: ограничение количества строк для теста, например `10`.
- `include_only_checked`: делать PDF только по строкам, где `Включить в PDF = TRUE`.

### 5. Опционально: кнопка в Google Sheets через Apps Script

Откройте Google Sheets → `Extensions → Apps Script`.

Скопируйте код из:

```text
apps_script/Code.gs
```

В Apps Script запустите функцию:

```javascript
setupArtstudioBooksIntegration()
```

Она попросит:

- GitHub owner;
- repo;
- branch;
- workflow file name;
- GitHub token.

После этого в таблице появится меню:

```text
ARTSTUDIO Books → Запустить обновление
```

## Рекомендуемая структура таблицы

Скрипт сам создаст эти колонки, если их нет:

| Колонка | Назначение |
|---|---|
| Ссылка | исходная ссылка на карточку книги |
| Источник | Ozon / Labirint / Book24 / другое |
| Название | название книги |
| Автор | автор, если найден |
| Цена | цена в рублях, если найдена |
| Наличие | есть / нет / неизвестно |
| Краткое описание | сжатое описание для отбора |
| Тематика | архитектура, искусство, театр, Петербург, дизайн и т.д. |
| Подходит для | лаунж / ресепшен / библиотека / номер |
| Визуальная ценность | 1–5 |
| Контекст ARTSTUDIO | 1–5 |
| Приоритет закупки | высокий / средний / низкий |
| Включить в PDF | TRUE / FALSE |
| Картинка 1 | URL первой картинки |
| Картинка 2 | URL второй картинки |
| Статус парсинга | OK / SKIPPED / NEEDS_REVIEW / ERROR |
| Обновлено | дата обновления |
| Комментарий | ручной комментарий |

## Логика тематики

Тематика определяется эвристически по названию и описанию:

- Петербург / Санкт-Петербург / Невский;
- архитектура / urban / city;
- искусство / painting / museum;
- театр / ballet / opera;
- дизайн / interiors / fashion / lifestyle;
- история / heritage.

Если тематика уже заполнена вручную, скрипт не перетирает ее, если не включен `force_refresh`.

## Важные ограничения

- Маркетплейсы могут отдавать разные версии страниц, скрывать цену или картинку, ограничивать запросы и показывать капчу.
- Поэтому в таблице есть статус `NEEDS_REVIEW`: строка остается в работе, но требует ручной проверки.
- PDF строится только по строкам с валидной ссылкой и заполненным названием либо статусом `OK`.

## Локальный запуск

1. Создайте `.env` по примеру `.env.example`.
2. Положите `service-account.json` локально или задайте `GOOGLE_SERVICE_ACCOUNT_JSON_B64`.
3. Установите зависимости:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium
```

4. Запуск:

```bash
python -m books_catalog.main --force-refresh --max-rows 10
```

На Windows можно использовать:

```powershell
scripts\run_local.ps1
```

## Выходные файлы

После запуска:

```text
output/books_catalog.html
output/books_catalog.pdf
output/run_summary.json
```

Если указан `DRIVE_FOLDER_ID`, PDF также будет загружен на Google Drive.

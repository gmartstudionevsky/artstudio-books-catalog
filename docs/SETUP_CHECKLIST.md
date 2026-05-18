# Setup checklist

## Google

- [ ] Создан Google Cloud project.
- [ ] Включен Google Sheets API.
- [ ] Включен Google Drive API, если нужен upload PDF на Drive.
- [ ] Создан service account.
- [ ] JSON key скачан.
- [ ] Google Sheet расшарен на email service account с правом Editor.

## GitHub

- [ ] Создан репозиторий.
- [ ] Загружены файлы комплекта.
- [ ] Добавлен secret `GOOGLE_SERVICE_ACCOUNT_JSON_B64`.
- [ ] Добавлен secret `SPREADSHEET_ID`.
- [ ] Опционально добавлен secret `DRIVE_FOLDER_ID`.
- [ ] Запущен workflow `Update books catalog` в режиме `max_rows = 10`.
- [ ] Проверена таблица: появились колонки, статусы и первые данные.
- [ ] Проверен artifact `books_catalog.pdf`.

## Apps Script

- [ ] Код из `apps_script/Code.gs` вставлен в Extensions → Apps Script.
- [ ] Запущена `setupArtstudioBooksIntegration()`.
- [ ] Таблица перезагружена.
- [ ] Меню `ARTSTUDIO Books` появилось.
- [ ] Тестовый запуск workflow из таблицы прошел успешно.

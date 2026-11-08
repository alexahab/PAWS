# Лапки в домике — Flask + PostgreSQL

Сайт для заявок о пропавших и найденных животных. Frontend: HTML/CSS/Jinja2. Backend: Flask. База данных: PostgreSQL 16 с драйвером psycopg 3.

## Запуск локально (Docker для PostgreSQL)

1. Установите Python 3.10+ и Docker Desktop. Откройте терминал в папке `paws_site`.
2. Запустите базу: `docker compose up -d db`.
3. Создайте окружение: `python -m venv .venv`.
4. Активируйте его: Windows PowerShell: `.venv\Scripts\Activate.ps1`; Linux/macOS: `source .venv/bin/activate`.
5. Установите пакеты: `pip install -r requirements.txt`.
6. Установите переменные окружения (PowerShell):

   ```powershell
   $env:DATABASE_URL='postgresql://paws:paws_dev_password@localhost:5432/paws_db'
   $env:SECRET_KEY='change-this-to-a-long-random-secret'
   $env:ADMIN_EMAIL='admin@example.org'
   $env:ADMIN_PASSWORD='ChangeThis123!'
   ```

7. Инициализируйте таблицы и администратора: `python init_db.py`.
8. Запустите сайт: `python app.py` и откройте `http://127.0.0.1:5000`.

**Linux/macOS:** переменные окружения задаются через `export NAME=value`.

Если PostgreSQL уже установлен локально, создайте пользователя и базу данных самостоятельно и укажите собственный `DATABASE_URL`; Docker необязателен.

## Модель данных

- `users`: пользователи и роли (`user`, `shelter`, `moderator`, `admin`)
- `ads`: объявления, FK `user_id -> users.id`
- `likes`: избранное, составной PK `(user_id, ad_id)`
- `reports`: жалобы, FK на пользователя и объявление

Диаграмма: `database_er.png` / `database_er.svg`.

## Важно

Это учебный MVP. Для размещения в интернете нужны HTTPS, безопасные учетные данные, резервные копии, ограничение частоты запросов, подтверждение email, миграции схемы и дополнительное тестирование безопасности. При повторном редактировании объявления оно снова поступает на модерацию. Изображения хранятся на диске в `static/uploads`, а их имена — в PostgreSQL.

Старая база SQLite не переносится автоматически. Для переноса существующих записей потребуется отдельный скрипт миграции данных и копирование изображений.

import os
import psycopg
from pathlib import Path
from werkzeug.security import generate_password_hash
from app import DATABASE_URL, BASE

with psycopg.connect(DATABASE_URL) as db:
    db.execute((BASE / 'schema.sql').read_text(encoding='utf-8'), prepare=False)
    email = os.getenv('ADMIN_EMAIL')
    password = os.getenv('ADMIN_PASSWORD')
    if email and password:
        if len(password) < 8:
            raise ValueError('ADMIN_PASSWORD слишком короткий')
        db.execute('''INSERT INTO users(name,email,password_hash,role)
                      VALUES(%s,%s,%s,'admin') ON CONFLICT(email) DO NOTHING''',
                   ('Администратор', email.lower(), generate_password_hash(password)))
    db.commit()
print('Схема PostgreSQL создана успешно')

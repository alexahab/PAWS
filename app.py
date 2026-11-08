import os, re, secrets, uuid
import psycopg
from psycopg.rows import dict_row
from psycopg.errors import UniqueViolation
from pathlib import Path
from functools import wraps
from datetime import datetime, timezone
from flask import Flask, render_template, request, redirect, url_for, flash, session, g, abort, send_from_directory
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from PIL import Image, UnidentifiedImageError

BASE = Path(__file__).resolve().parent
DATABASE_URL = os.getenv('DATABASE_URL', 'postgresql://paws:paws_dev_password@localhost:5432/paws_db')
UPLOAD = BASE / 'static' / 'uploads'
UPLOAD.mkdir(parents=True, exist_ok=True)
app = Flask(__name__)
app.config.update(SECRET_KEY=os.getenv('SECRET_KEY', 'dev-only-change-me'), MAX_CONTENT_LENGTH=5*1024*1024, SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax', SESSION_COOKIE_SECURE=os.getenv('COOKIE_SECURE') == '1')
ALLOWED_ROLES = ('user', 'shelter', 'moderator', 'admin')
STATUSES = ('pending', 'published', 'rejected', 'closed')


def get_db():
    if 'db' not in g:
        g.db = psycopg.connect(DATABASE_URL, row_factory=dict_row)
    return g.db

@app.teardown_appcontext
def close_db(_):
    db = g.pop('db', None)
    if db:
        db.close()

@app.before_request
def load_user():
    g.user = None
    if session.get('user_id'):
        g.user = get_db().execute('SELECT * FROM users WHERE id=%s', (session['user_id'],)).fetchone()
        if not g.user or g.user['is_blocked']:
            session.clear(); g.user = None
    if 'csrf' not in session: session['csrf'] = secrets.token_urlsafe(32)
    if request.method in ('POST', 'PUT', 'PATCH', 'DELETE'):
        if not secrets.compare_digest(request.form.get('csrf', ''), session['csrf']):
            abort(400, description='Недействительный CSRF-токен')

@app.context_processor
def context():
    return {'current_user': g.user, 'csrf_token': lambda: session['csrf']}

def login_required(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        if not g.user:
            flash('Войдите в аккаунт', 'warning'); return redirect(url_for('login'))
        return fn(*args, **kwargs)
    return wrapped

def staff_required(fn):
    @wraps(fn)
    @login_required
    def wrapped(*args, **kwargs):
        if g.user['role'] not in ('moderator', 'admin'): abort(403)
        return fn(*args, **kwargs)
    return wrapped

def save_image(file):
    if not file or not file.filename: return None
    if Path(file.filename).suffix.lower() not in ('.jpg', '.jpeg', '.png', '.webp'):
        raise ValueError('Допустимые форматы: JPG, PNG, WEBP')
    try:
        file.stream.seek(0)
        with Image.open(file.stream) as img:
            img.verify()
        file.stream.seek(0)
        with Image.open(file.stream) as img:
            if img.width * img.height > 20_000_000: raise ValueError('Слишком большое изображение')
            img = img.convert('RGB')
            img.thumbnail((1600, 1600))
            filename = f'{uuid.uuid4().hex}.jpg'
            img.save(UPLOAD / filename, 'JPEG', quality=85)
            return filename
    except (UnidentifiedImageError, OSError) as exc:
        raise ValueError('Файл не является корректным изображением') from exc

def validate_ad(form):
    kind = form.get('kind', '')
    name = form.get('animal_name', '').strip()[:80]
    species = form.get('species', '').strip()[:60]
    city = form.get('city', '').strip()[:100]
    district = form.get('district', '').strip()[:100]
    description = form.get('description', '').strip()
    contact = form.get('contact', '').strip()
    if kind not in ('lost', 'found'): raise ValueError('Выберите тип объявления')
    if not species or not city or not district: raise ValueError('Заполните вид животного, город и район')
    if not 20 <= len(description) <= 300: raise ValueError('Описание должно содержать 20–300 символов')
    if not 5 <= len(contact) <= 150: raise ValueError('Укажите способ связи (5–150 символов)')
    return kind, name, species, city, district, description, contact

@app.route('/')
def index():
    db = get_db()
    filters = {k: request.args.get(k, '').strip() for k in ('q','kind','city','species')}
    where = ["a.status='published'"]; args = []
    if filters['q']:
        where.append('(a.description ILIKE %s OR a.animal_name ILIKE %s OR a.district ILIKE %s)')
        args += [f"%{filters['q']}%"]*3
    if filters['kind'] in ('lost', 'found'):
        where.append('a.kind=%s'); args.append(filters['kind'])
    for field in ('city','species'):
        if filters[field]: where.append(f'a.{field} ILIKE %s'); args.append(f"%{filters[field]}%")
    page = max(1, request.args.get('page', 1, type=int) or 1)
    rows = db.execute(f'''SELECT a.*, u.name AS author_name FROM ads a JOIN users u ON a.user_id=u.id
                         WHERE {' AND '.join(where)} ORDER BY a.created_at DESC LIMIT 13 OFFSET %s''', (*args, (page-1)*12)).fetchall()
    return render_template('index.html', ads=rows[:12], has_next=len(rows)>12, page=page, filters=filters)

@app.route('/register', methods=['GET','POST'])
def register():
    if request.method == 'POST':
        name=request.form.get('name','').strip(); email=request.form.get('email','').strip().lower()
        password=request.form.get('password',''); role=request.form.get('role','user')
        if not 2 <= len(name) <= 50 or not re.fullmatch(r'[\w.\-+]+@[\w.\-]+\.[A-Za-z]{2,}', email) or role not in ('user','shelter'):
            flash('Проверьте имя, email и роль', 'error')
        elif len(password)<8 or not re.search(r'\d',password) or not re.search(r'[^\w\s]',password):
            flash('Пароль: от 8 символов, цифра и специальный знак', 'error')
        else:
            try:
                db=get_db(); db.execute('INSERT INTO users(name,email,password_hash,role) VALUES(%s,%s,%s,%s)', (name,email,generate_password_hash(password),role)); db.commit()
                flash('Аккаунт создан. Войдите.', 'success'); return redirect(url_for('login'))
            except UniqueViolation:
                db.rollback()
                flash('Email уже зарегистрирован', 'error')
    return render_template('auth.html', mode='register')

@app.route('/login', methods=['GET','POST'])
def login():
    if request.method=='POST':
        email=request.form.get('email','').strip().lower()
        user=get_db().execute('SELECT * FROM users WHERE email=%s',(email,)).fetchone()
        if not user or user['is_blocked'] or not check_password_hash(user['password_hash'], request.form.get('password','')):
            flash('Неверные данные или аккаунт заблокирован', 'error')
        else:
            session.clear(); session['user_id']=user['id']; session['csrf']=secrets.token_urlsafe(32)
            return redirect(url_for('index'))
    return render_template('auth.html', mode='login')

@app.post('/logout')
@login_required
def logout():
    session.clear(); return redirect(url_for('index'))

@app.route('/ads/new', methods=['GET','POST'])
@login_required
def new_ad():
    if request.method=='POST':
        try:
            values=validate_ad(request.form)
            image=save_image(request.files.get('photo'))
            if not image: raise ValueError('Добавьте фотографию животного')
            db=get_db()
            db.execute('''INSERT INTO ads(user_id,kind,animal_name,species,city,district,description,contact,image_filename,status)
                          VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,'pending')''', (g.user['id'],*values,image))
            db.commit(); flash('Объявление отправлено на модерацию', 'success'); return redirect(url_for('my_ads'))
        except ValueError as e: flash(str(e),'error')
    return render_template('ad_form.html', ad=None)

@app.route('/ads/<int:ad_id>')
def ad_detail(ad_id):
    db=get_db()
    ad=db.execute('SELECT a.*,u.name AS author_name FROM ads a JOIN users u ON u.id=a.user_id WHERE a.id=%s',(ad_id,)).fetchone()
    if not ad: abort(404)
    privileged = g.user and (g.user['id']==ad['user_id'] or g.user['role'] in ('moderator','admin'))
    if ad['status']!='published' and not privileged: abort(404)
    liked = bool(g.user and db.execute('SELECT 1 FROM likes WHERE ad_id=%s AND user_id=%s',(ad_id,g.user['id'])).fetchone())
    return render_template('detail.html', ad=ad, liked=liked, privileged=privileged)

@app.route('/my-ads')
@login_required
def my_ads():
    ads=get_db().execute('SELECT * FROM ads WHERE user_id=%s ORDER BY created_at DESC',(g.user['id'],)).fetchall()
    return render_template('my_ads.html', ads=ads)

@app.route('/ads/<int:ad_id>/edit',methods=['GET','POST'])
@login_required
def edit_ad(ad_id):
    db=get_db(); ad=db.execute('SELECT * FROM ads WHERE id=%s',(ad_id,)).fetchone()
    if not ad: abort(404)
    if ad['user_id']!=g.user['id'] and g.user['role']!='admin': abort(403)
    if ad['status']=='closed': abort(400)
    if request.method=='POST':
        try:
            values=validate_ad(request.form)
            image=save_image(request.files.get('photo')) or ad['image_filename']
            db.execute('''UPDATE ads SET kind=%s,animal_name=%s,species=%s,city=%s,district=%s,description=%s,contact=%s,image_filename=%s,
                         status='pending',rejection_reason=NULL,updated_at=CURRENT_TIMESTAMP WHERE id=%s''', (*values,image,ad_id))
            db.commit(); flash('Изменения отправлены на модерацию', 'success'); return redirect(url_for('my_ads'))
        except ValueError as e: flash(str(e),'error')
    return render_template('ad_form.html',ad=ad)

@app.post('/ads/<int:ad_id>/delete')
@login_required
def delete_ad(ad_id):
    db=get_db(); ad=db.execute('SELECT * FROM ads WHERE id=%s',(ad_id,)).fetchone()
    if not ad: abort(404)
    if ad['user_id']!=g.user['id'] and g.user['role']!='admin': abort(403)
    db.execute('DELETE FROM ads WHERE id=%s',(ad_id,)); db.commit()
    if ad['image_filename']:
        (UPLOAD / ad['image_filename']).unlink(missing_ok=True)
    flash('Объявление удалено', 'success'); return redirect(url_for('my_ads'))

@app.post('/ads/<int:ad_id>/close')
@login_required
def close_ad(ad_id):
    db=get_db(); ad=db.execute('SELECT * FROM ads WHERE id=%s',(ad_id,)).fetchone()
    if not ad: abort(404)
    if ad['user_id']!=g.user['id'] and g.user['role']!='admin': abort(403)
    db.execute("UPDATE ads SET status='closed',updated_at=CURRENT_TIMESTAMP WHERE id=%s",(ad_id,)); db.commit()
    flash('Объявление завершено','success'); return redirect(url_for('my_ads'))

@app.post('/ads/<int:ad_id>/like')
@login_required
def like_ad(ad_id):
    db=get_db()
    if not db.execute("SELECT 1 FROM ads WHERE id=%s AND status='published'",(ad_id,)).fetchone(): abort(404)
    if db.execute('SELECT 1 FROM likes WHERE user_id=%s AND ad_id=%s',(g.user['id'],ad_id)).fetchone():
        db.execute('DELETE FROM likes WHERE user_id=%s AND ad_id=%s',(g.user['id'],ad_id))
    else: db.execute('INSERT INTO likes(user_id,ad_id) VALUES(%s,%s)',(g.user['id'],ad_id))
    db.commit(); return redirect(url_for('ad_detail',ad_id=ad_id))

@app.route('/favorites')
@login_required
def favorites():
    ads=get_db().execute('''SELECT a.* FROM ads a JOIN likes l ON l.ad_id=a.id WHERE l.user_id=%s AND a.status='published' ORDER BY l.created_at DESC''',(g.user['id'],)).fetchall()
    return render_template('my_ads.html',ads=ads,favorites=True)

@app.post('/ads/<int:ad_id>/report')
@login_required
def report_ad(ad_id):
    reason=request.form.get('reason','').strip()
    if not 10 <= len(reason) <= 500: abort(400, 'Причина жалобы: 10–500 символов')
    db=get_db()
    if not db.execute("SELECT 1 FROM ads WHERE id=%s AND status='published'",(ad_id,)).fetchone(): abort(404)
    db.execute('INSERT INTO reports(user_id,ad_id,reason) VALUES(%s,%s,%s)',(g.user['id'],ad_id,reason)); db.commit()
    flash('Жалоба отправлена', 'success'); return redirect(url_for('ad_detail',ad_id=ad_id))

@app.route('/moderation')
@staff_required
def moderation():
    db=get_db()
    ads=db.execute("SELECT a.*,u.name AS author_name FROM ads a JOIN users u ON a.user_id=u.id WHERE a.status='pending' ORDER BY a.created_at").fetchall()
    reports=db.execute('SELECT r.*,a.animal_name,a.id AS listing_id FROM reports r JOIN ads a ON a.id=r.ad_id ORDER BY r.created_at DESC LIMIT 30').fetchall()
    return render_template('moderation.html',ads=ads,reports=reports)

@app.post('/moderation/<int:ad_id>')
@staff_required
def moderate(ad_id):
    decision=request.form.get('decision'); reason=request.form.get('reason','').strip()
    if decision not in ('published','rejected'): abort(400)
    if decision=='rejected' and not 5 <= len(reason) <= 300:
        flash('Укажите причину отклонения (5–300 символов)', 'error'); return redirect(url_for('moderation'))
    db=get_db()
    cur=db.execute('UPDATE ads SET status=%s,rejection_reason=%s,updated_at=CURRENT_TIMESTAMP WHERE id=%s AND status=%s',
                   (decision,reason if decision=='rejected' else None,ad_id,'pending'))
    db.commit()
    if not cur.rowcount: abort(404)
    flash('Решение сохранено', 'success'); return redirect(url_for('moderation'))

@app.errorhandler(413)
def too_large(_): return 'Файл больше 5 МБ',413

if __name__=='__main__':
    if app.config['SECRET_KEY']=='dev-only-change-me': print('WARNING: set SECRET_KEY before deployment')
    app.run(debug=os.getenv('FLASK_DEBUG')=='1')

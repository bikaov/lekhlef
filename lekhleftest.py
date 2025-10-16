import os
import sys
from flask import Flask, g, render_template_string, request, redirect, url_for, flash, session
import sqlite3
from datetime import datetime
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
import json

# --------- Configuration for EXE conversion ---------
def get_application_path():
    """الحصول على مسار التطبيق سواء كان exe أو script عادي"""
    if getattr(sys, 'frozen', False):
        # إذا كان التطبيق محول إلى exe
        return os.path.dirname(sys.executable)
    else:
        # إذا كان يعمل كسكريبت عادي
        return os.path.dirname(os.path.abspath(__file__))

APP_DIR = get_application_path()
MAIN_DB_PATH = os.path.join(APP_DIR, 'main_system.db')  # قاعدة البيانات الرئيسية للمستخدمين والمحلات
STORES_DIR = os.path.join(APP_DIR, 'stores_data')  # مجلد قواعد بيانات المحلات

# إعداد Flask مع مسارات صحيحة للتحويل
app = Flask(__name__, 
           static_folder=os.path.join(APP_DIR, 'static'),
           template_folder=os.path.join(APP_DIR, 'templates'))
app.secret_key = 'change_this_to_random_secret'

# --------- Authentication helpers ---------
def login_required(f):
    """ديكوراتور لحماية الصفحات التي تتطلب تسجيل دخول"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('يجب تسجيل الدخول أولاً للوصول إلى هذه الصفحة.')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def store_required(f):
    """ديكوراتور لحماية الصفحات التي تتطلب اختيار محل"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'store_id' not in session:
            flash('يجب اختيار محل أولاً للوصول إلى هذه الصفحة.')
            return redirect(url_for('select_store'))
        return f(*args, **kwargs)
    return decorated_function

def check_store_permission(user_id, store_id, required_permission='viewer'):
    """التحقق من صلاحيات المستخدم على المحل"""
    db = get_main_db()
    c = db.cursor()
    
    # التحقق من صلاحيات المستخدم
    c.execute('''SELECT permission_level FROM store_permissions 
                WHERE user_id = ? AND store_id = ?''', (user_id, store_id))
    permission = c.fetchone()
    
    if not permission:
        return False
    
    # ترتيب الصلاحيات
    permission_levels = {'viewer': 1, 'editor': 2, 'manager': 3, 'owner': 4}
    user_level = permission_levels.get(permission['permission_level'], 0)
    required_level = permission_levels.get(required_permission, 1)
    
    return user_level >= required_level

def is_admin(user_id):
    """التحقق من كون المستخدم مدير"""
    db = get_main_db()
    c = db.cursor()
    c.execute('SELECT username FROM users WHERE id = ?', (user_id,))
    result = c.fetchone()
    return result and result['username'] == 'admin'

def admin_required(f):
    """ديكوريتور للتحقق من صلاحيات المدير"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('user_id'):
            flash('❌ يجب تسجيل الدخول أولاً.')
            return redirect(url_for('login'))
        
        if not is_admin(session['user_id']):
            flash('❌ ليس لديك صلاحية للوصول إلى هذه الصفحة.')
            return redirect(url_for('index'))
        
        return f(*args, **kwargs)
    return decorated_function

def get_current_user():
    """الحصول على بيانات المستخدم الحالي"""
    if 'user_id' not in session:
        return None
    db = get_main_db()
    c = db.cursor()
    c.execute('SELECT * FROM users WHERE id = ?', (session['user_id'],))
    return c.fetchone()

def get_current_store():
    """الحصول على بيانات المحل الحالي"""
    if 'store_id' not in session:
        return None
    db = get_main_db()
    c = db.cursor()
    c.execute('SELECT * FROM stores WHERE id = ?', (session['store_id'],))
    return c.fetchone()

def get_store_db_path(store_id):
    """الحصول على مسار قاعدة بيانات المحل"""
    return os.path.join(STORES_DIR, f'store_{store_id}.db')

def ensure_stores_directory():
    """التأكد من وجود مجلد المحلات"""
    if not os.path.exists(STORES_DIR):
        os.makedirs(STORES_DIR)

def get_main_db():
    """الحصول على اتصال قاعدة البيانات الرئيسية"""
    db = getattr(g, '_main_database', None)
    if db is None:
        ensure_main_database_exists()
        db = g._main_database = sqlite3.connect(MAIN_DB_PATH)
        db.row_factory = sqlite3.Row
    return db

def get_store_db():
    """الحصول على اتصال قاعدة بيانات المحل الحالي"""
    if 'store_id' not in session:
        return None
    
    store_db = getattr(g, '_store_database', None)
    if store_db is None:
        store_db_path = get_store_db_path(session['store_id'])
        ensure_store_database_exists(session['store_id'])
        store_db = g._store_database = sqlite3.connect(store_db_path)
        store_db.row_factory = sqlite3.Row
    return store_db

# --------- DB helpers ---------
def ensure_main_database_exists():
    """التأكد من وجود قاعدة البيانات الرئيسية وإنشاؤها إذا لم تكن موجودة"""
    if not os.path.exists(MAIN_DB_PATH):
        # إنشاء قاعدة البيانات الرئيسية الجديدة
        db = sqlite3.connect(MAIN_DB_PATH)
        db.row_factory = sqlite3.Row
        c = db.cursor()
        
        # إنشاء جدول المستخدمين
        c.execute('''CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE NOT NULL,
                    email TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    full_name TEXT NOT NULL,
                    phone TEXT,
                    role TEXT DEFAULT 'user',
                    created_at TEXT NOT NULL,
                    last_login TEXT,
                    is_active INTEGER DEFAULT 1
                )''')
        
        # إنشاء جدول المحلات
        c.execute('''CREATE TABLE IF NOT EXISTS stores (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    store_name TEXT NOT NULL,
                    owner_id INTEGER NOT NULL,
                    store_type TEXT DEFAULT 'library',
                    address TEXT,
                    phone TEXT,
                    email TEXT,
                    description TEXT,
                    created_at TEXT NOT NULL,
                    is_active INTEGER DEFAULT 1,
                    FOREIGN KEY (owner_id) REFERENCES users (id)
                )''')
        
        # إضافة حقل الوصف إذا لم يكن موجوداً (للقواعد الموجودة)
        try:
            c.execute('ALTER TABLE stores ADD COLUMN description TEXT')
        except:
            pass  # الحقل موجود بالفعل
        
        # إنشاء جدول صلاحيات المستخدمين على المحلات
        c.execute('''CREATE TABLE IF NOT EXISTS store_permissions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    store_id INTEGER NOT NULL,
                    permission_level TEXT DEFAULT 'viewer',
                    granted_at TEXT NOT NULL,
                    FOREIGN KEY (user_id) REFERENCES users (id),
                    FOREIGN KEY (store_id) REFERENCES stores (id),
                    UNIQUE(user_id, store_id)
                )''')
        
        # إنشاء مستخدم إداري افتراضي
        admin_exists = c.execute('SELECT COUNT(*) FROM users WHERE username = ?', ('admin',)).fetchone()[0]
        if admin_exists == 0:
            admin_password = generate_password_hash('admin123')
            current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            c.execute('''INSERT INTO users (username, email, password_hash, full_name, role, created_at) 
                        VALUES (?, ?, ?, ?, ?, ?)''', 
                     ('admin', 'admin@maktaba.com', admin_password, 'مدير النظام', 'admin', current_time))
            
            # إنشاء محل افتراضي للمدير
            admin_id = c.lastrowid
            c.execute('''INSERT INTO stores (store_name, owner_id, store_type, phone, address, email, description, created_at) 
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)''', 
                     ('مكتبة لخلف', admin_id, 'library', '0676904111', 'شارع المعرفة، وسط المدينة', 'info@maktaba-lekhlef.com', 'مكتبة متخصصة في جميع المواد التعليمية والقرطاسية', current_time))
            
            # إعطاء صلاحيات كاملة للمدير على المحل
            store_id = c.lastrowid
            c.execute('''INSERT INTO store_permissions (user_id, store_id, permission_level, granted_at) 
                        VALUES (?, ?, ?, ?)''', 
                     (admin_id, store_id, 'owner', current_time))
        
        db.commit()
        db.close()

def ensure_store_database_exists(store_id):
    """التأكد من وجود قاعدة بيانات المحل وإنشاؤها إذا لم تكن موجودة"""
    ensure_stores_directory()
    store_db_path = get_store_db_path(store_id)
    
    if not os.path.exists(store_db_path):
        # إنشاء قاعدة بيانات المحل الجديدة
        db = sqlite3.connect(store_db_path)
        db.row_factory = sqlite3.Row
        c = db.cursor()
        
        # إنشاء جداول المحل
        c.execute('''CREATE TABLE IF NOT EXISTS items (id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT UNIQUE, name TEXT, buy_price REAL DEFAULT 0, sell_price REAL DEFAULT 0, qty INTEGER DEFAULT 0)''')
        c.execute('''CREATE TABLE IF NOT EXISTS customers (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, phone TEXT, note TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS suppliers (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, phone TEXT, note TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS sales (id INTEGER PRIMARY KEY AUTOINCREMENT, customer_id INTEGER, date TEXT, total REAL)''')
        c.execute('''CREATE TABLE IF NOT EXISTS sale_items (id INTEGER PRIMARY KEY AUTOINCREMENT, sale_id INTEGER, item_id INTEGER, qty INTEGER, price REAL)''')
        c.execute('''CREATE TABLE IF NOT EXISTS purchases (id INTEGER PRIMARY KEY AUTOINCREMENT, supplier_id INTEGER, date TEXT, total REAL)''')
        c.execute('''CREATE TABLE IF NOT EXISTS purchase_items (id INTEGER PRIMARY KEY AUTOINCREMENT, purchase_id INTEGER, item_id INTEGER, qty INTEGER, price REAL)''')
        c.execute('''CREATE TABLE IF NOT EXISTS debts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    entity_type TEXT NOT NULL,
                    entity_id INTEGER NOT NULL,
                    original_amount REAL NOT NULL,
                    paid_amount REAL DEFAULT 0,
                    remaining_amount REAL NOT NULL,
                    date_created TEXT NOT NULL,
                    date_updated TEXT,
                    note TEXT
                )''')
        
        db.commit()
        db.close()

def get_db():
    """دالة للحصول على قاعدة بيانات المحل الحالي (للتوافق مع الكود القديم)"""
    return get_store_db()

@app.teardown_appcontext
def close_connection(exception):
    # إغلاق قاعدة البيانات الرئيسية
    main_db = getattr(g, '_main_database', None)
    if main_db is not None:
        main_db.close()
    
    # إغلاق قاعدة بيانات المحل
    store_db = getattr(g, '_store_database', None)
    if store_db is not None:
        store_db.close()

def init_db():
    """تهيئة قواعد البيانات"""
    ensure_main_database_exists()

with app.app_context():
    init_db()

# --------- Base template (Hyperspace integrated with new styles) ---------
base_html = """
<!DOCTYPE HTML>
<html lang="ar" dir="rtl">
<head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1, user-scalable=no" />
     <title>مكتبة لخلف</title>
    <link href="https://fonts.googleapis.com/css2?family=Cairo:wght@400;700&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="/static/assets/css/main.css" />
    <noscript><link rel="stylesheet" href="/static/assets/css/noscript.css" /></noscript>
    <style>
      /* تعديلات RTL وتطبيق الخط الجديد */
      body {
          direction: rtl;
          text-align: right;
          font-family: 'Cairo', sans-serif; /* تطبيق الخط */
      }
      /* تحسين حجم وشكل عناوين الأقسام */
      .inner h1, .inner h2, .inner h3 { margin-bottom: 0.75rem; font-weight: 700; }
      
      /* تحسين مظهر الجدول الافتراضي */
      .table-wrapper { overflow-x: auto; } /* لمعالجة الجداول الكبيرة */
      table { width: 100%; border-collapse: collapse; margin: 0 0 2em 0; }
      table th, table td { padding: 0.75em; border: solid 1px rgba(255, 255, 255, 0.2); }
      table thead th { background: rgba(255, 255, 255, 0.1); color: #fff; }
      table.alt tbody tr:nth-child(2n) { background-color: rgba(255, 255, 255, 0.03); }
      
      /* تحسين أزرار القائمة الجانبية */
      #sidebar nav ul li a {
          display: block;
          padding: 0.6rem 0.75rem;
          color: rgba(255, 255, 255, 0.85);
          transition: 0.2s ease-in-out;
      }
      #sidebar nav ul li a:hover {
          color: #ffffff;
          background-color: rgba(255, 255, 255, 0.1);
      }
      /* تنسيق خاص للأزرار لتبدو مميزة */
      .button.primary {
          background-color: #5599FF !important; /* أزرق مميز */
          color: #fff !important;
      }
      .button.secondary {
          background-color: #f7786b !important; /* أحمر أو برتقالي للعمليات الثانوية/الإلغاء */
          color: #fff !important;
      }
      /* تنسيق حقول الإدخال */
      .form-control, select {
          background: rgba(255, 255, 255, 0.05) !important;
          border: solid 1px rgba(255, 255, 255, 0.2) !important;
          color: #fff !important;
          /* Hyperspace overrides */
          width: 100% !important;
          padding: 0.75em 1em;
          -moz-appearance: none;
          -webkit-appearance: none;
          -ms-appearance: none;
          appearance: none;
          border-radius: 4px;
          border: none;
          border: solid 1px transparent;
      }
      /* تنسيق الـ Form الأساسي من Hyperspace */
      .form {
          margin: 0 0 2em 0;
      }
      .form .fields {
          display: -webkit-box;
          display: -ms-flexbox;
          display: flex;
          -ms-flex-wrap: wrap;
          flex-wrap: wrap;
          width: calc(100% + 3em);
          margin: -1.5em 0 2em -1.5em;
      }
      .form .field {
          -webkit-box-flex: 0;
          -ms-flex: 0 0 auto;
          flex: 0 0 auto;
          padding: 1.5em 0 0 1.5em;
          width: 100%;
      }
      .form .field.half {
          width: 50%;
      }
    </style>
</head>
<body class="is-preload">

    <section id="sidebar">
        <div class="inner">
            <nav>
                <ul>
                    {% if session.user_id %}
                    <li><a href="/profile">👤 {{ session.username }}</a></li>
                    {% if session.store_id %}
                    <li><a href="/select_store">🏪 {{ session.store_name }}</a></li>
                    {% else %}
                    <li><a href="/select_store">🏪 اختيار محل</a></li>
                    {% endif %}
                    <li><a href="/logout" style="color: #ff6b6b; font-weight: bold;">🚪 تسجيل الخروج</a></li>
                    <li><hr style="border-color: rgba(255,255,255,0.2); margin: 10px 0;"></li>
                    {% else %}
                    <li><a href="/login">🔑 تسجيل الدخول</a></li>
                    <li><hr style="border-color: rgba(255,255,255,0.2); margin: 10px 0;"></li>
                    {% endif %}
                    <li><a href="/">🏠 الرئيسية</a></li>
                    {% if session.store_id %}
                    <li><a href="/pos">💵 نقطة البيع</a></li>
                    <li><a href="/items">📦 المخزون</a></li>
                    <li><a href="/purchases">🧾 المشتريات</a></li>
                    <li><a href="/customers">👥 الزبائن</a></li>
                    <li><a href="/suppliers">🚚 الموردين</a></li>
                    <li><a href="/debts">💰 الديون</a></li> 
                    <li><a href="/invoices">🧮 الفواتير</a></li>
                    <li><a href="/store_settings">⚙️ إعدادات المحل</a></li>
                    {% endif %}
                    {% if session.user_id and session.username == 'admin' %}
                    <li><hr style="border-color: rgba(255,255,255,0.2); margin: 10px 0;"></li>
                    <li><a href="/admin/users" style="color: #ffd700; font-weight: bold;">👑 إدارة المستخدمين</a></li>
                    {% endif %}
                </ul>
            </nav>
        </div>
    </section>

    <div id="wrapper">

        <section id="intro" class="wrapper style1 fade-up">
            <div class="inner">
            </div>
        </section>

        {% with messages = get_flashed_messages() %}
            {% if messages %}
            <section class="wrapper style3 fade-up">
                <div class="inner">
                    <ul class="actions">
                    {% for message in messages %}
                        <li class="button small primary">{{ message }}</li> 
                    {% endfor %}
                    </ul>
                </div>
            </section>
            {% endif %}
        {% endwith %}

        %%CONTENT%%

    </div>

    <footer id="footer" class="wrapper style1-alt">
        <div class="inner">
            <ul class="menu">
                <li>تصميم القالب: <a href="https://html5up.net">HTML5 UP</a></li>
            </ul>
        </div>
    </footer>

    <script src="/static/assets/js/jquery.min.js"></script>
    <script src="/static/assets/js/jquery.scrollex.min.js"></script>
    <script src="/static/assets/js/jquery.scrolly.min.js"></script>
    <script src="/static/assets/js/browser.min.js"></script>
    <script src="/static/assets/js/breakpoints.min.js"></script>
    <script src="/static/assets/js/util.js"></script>
    <script src="/static/assets/js/main.js"></script>
</body>
</html>
"""

# --------- Authentication Routes ---------
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        if not username or not password:
            flash('❌ يرجى إدخال اسم المستخدم وكلمة المرور.')
            return redirect(url_for('login'))
        
        db = get_main_db()
        c = db.cursor()
        c.execute('SELECT * FROM users WHERE username = ? AND is_active = 1', (username,))
        user = c.fetchone()
        
        if user and check_password_hash(user['password_hash'], password):
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['full_name'] = user['full_name']
            session['role'] = user['role']
            
            # تحديث آخر تسجيل دخول
            current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            c.execute('UPDATE users SET last_login = ? WHERE id = ?', (current_time, user['id']))
            db.commit()
            
            # التحقق من وجود محلات للمستخدم
            c.execute('''SELECT COUNT(*) FROM stores s 
                        LEFT JOIN store_permissions sp ON s.id = sp.store_id 
                        WHERE (s.owner_id = ? OR sp.user_id = ?) AND s.is_active = 1''', 
                     (user['id'], user['id']))
            stores_count = c.fetchone()[0]
            
            if stores_count == 0:
                flash(f'✅ مرحباً {user["full_name"]}! تم تسجيل الدخول بنجاح. أنشئ محل جديد للبدء.')
                return redirect(url_for('create_store'))
            elif stores_count == 1:
                # إذا كان لديه محل واحد فقط، اختياره تلقائياً
                c.execute('''SELECT s.* FROM stores s 
                            LEFT JOIN store_permissions sp ON s.id = sp.store_id 
                            WHERE (s.owner_id = ? OR sp.user_id = ?) AND s.is_active = 1 
                            LIMIT 1''', (user['id'], user['id']))
                store = c.fetchone()
                if store:
                    session['store_id'] = store['id']
                    session['store_name'] = store['store_name']
                    session['store_type'] = store['store_type']
                    ensure_store_database_exists(store['id'])
                    flash(f'✅ مرحباً {user["full_name"]}! تم تسجيل الدخول بنجاح. تم اختيار محل "{store["store_name"]}" تلقائياً.')
                    return redirect(url_for('index'))
            
            flash(f'✅ مرحباً {user["full_name"]}! تم تسجيل الدخول بنجاح.')
            return redirect(url_for('select_store'))
        else:
            flash('❌ اسم المستخدم أو كلمة المرور غير صحيحة.')
            return redirect(url_for('login'))
    
    # صفحة تسجيل الدخول
    page = '''
    <section class="wrapper style1 fade-up">
        <div class="inner">
            <h2>🔑 تسجيل الدخول</h2>
             <p>أدخل بياناتك للوصول إلى النظام</p>
            
            <form method="post" class="form">
                <div class="fields">
                    <div class="field">
                        <label for="username">اسم المستخدم</label>
                        <input type="text" name="username" id="username" class="form-control" 
                               placeholder="أدخل اسم المستخدم" required>
                    </div>
                    <div class="field">
                        <label for="password">كلمة المرور</label>
                        <input type="password" name="password" id="password" class="form-control" 
                               placeholder="أدخل كلمة المرور" required>
                    </div>
                </div>
                <ul class="actions">
                    <li><button type="submit" class="button primary">🔑 تسجيل الدخول</button></li>
                    <li><a href="/register" class="button secondary">📝 إنشاء حساب جديد</a></li>
                </ul>
            </form>
            
        </div>
    </section>
    '''
    return render_template_string(base_html.replace('%%CONTENT%%', page))

@app.route('/register', methods=['GET', 'POST'])
def register_disabled():
    """صفحة التسجيل معطلة - إنشاء الحسابات متاح للمدير فقط"""
    # إظهار رسالة أن التسجيل معطل
    flash('🚫 التسجيل غير متاح. إنشاء الحسابات متاح للمدير فقط.', 'info')
    
    page = '''
    <section class="wrapper style1 fade-up">
        <div class="inner">
            <h2>🚫 التسجيل غير متاح</h2>
            <p>إنشاء الحسابات الجديدة متاح للمدير فقط</p>
            <p>يرجى التواصل مع المدير لإنشاء حساب جديد</p>
            
            <div style="background-color: #f8f9fa; padding: 20px; border-radius: 8px; margin: 20px 0; border-left: 4px solid #ffc107;">
                <h3 style="color: #856404; margin-top: 0;">👑 للمدير:</h3>
                <p style="margin-bottom: 0;">يمكن للمدير إنشاء حسابات جديدة من خلال:</p>
                <ul style="margin: 10px 0;">
                    <li>تسجيل الدخول بحساب المدير</li>
                    <li>الذهاب إلى "👑 إدارة المستخدمين"</li>
                    <li>الضغط على "➕ إضافة مستخدم جديد"</li>
                </ul>
            </div>
            
            <ul class="actions">
                <li><a href="/login" class="button primary">🔑 تسجيل الدخول</a></li>
                <li><a href="/" class="button secondary">العودة للرئيسية</a></li>
            </ul>
        </div>
    </section>
    '''
    return render_template_string(base_html.replace('%%CONTENT%%', page))

@app.route('/logout')
def logout():
    if 'user_id' in session:
        username = session.get('username', 'المستخدم')
        session.clear()
        flash(f'✅ تم تسجيل الخروج بنجاح. وداعاً {username}!')
    return redirect(url_for('index'))

@app.route('/profile')
@login_required
def profile():
    user = get_current_user()
    if not user:
        flash('❌ خطأ في تحميل بيانات المستخدم.')
        return redirect(url_for('login'))
    
    page = f'''
    <section class="wrapper style1 fade-up">
        <div class="inner">
            <h2>👤 الملف الشخصي</h2>
            
            <div class="fields">
                <div class="field">
                    <div style="background: rgba(255,255,255,0.1); padding: 2rem; border-radius: 10px; margin-bottom: 2rem;">
                        <h3>معلومات الحساب</h3>
                        <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 1rem; margin-top: 1rem;">
                            <div><strong>اسم المستخدم:</strong> {user['username']}</div>
                            <div><strong>الاسم الكامل:</strong> {user['full_name']}</div>
                            <div><strong>البريد الإلكتروني:</strong> {user['email']}</div>
                            <div><strong>رقم الهاتف:</strong> {user['phone'] or 'غير محدد'}</div>
                            <div><strong>الدور:</strong> {user['role']}</div>
                            <div><strong>تاريخ الإنشاء:</strong> {user['created_at'][:10]}</div>
                            <div><strong>آخر تسجيل دخول:</strong> {user['last_login'][:16] if user['last_login'] else 'لم يتم تسجيل الدخول بعد'}</div>
                        </div>
                    </div>
                </div>
            </div>
            
            <ul class="actions">
                <li><a href="/edit_profile" class="button primary">✏️ تعديل الملف الشخصي</a></li>
                <li><a href="/change_password" class="button secondary">🔒 تغيير كلمة المرور</a></li>
                <li><a href="/" class="button">🏠 العودة للرئيسية</a></li>
            </ul>
        </div>
    </section>
    '''
    return render_template_string(base_html.replace('%%CONTENT%%', page))

@app.route('/edit_profile', methods=['GET', 'POST'])
@login_required
def edit_profile():
    user = get_current_user()
    if not user:
        flash('❌ خطأ في تحميل بيانات المستخدم.')
        return redirect(url_for('login'))
    
    if request.method == 'POST':
        full_name = request.form.get('full_name')
        email = request.form.get('email')
        phone = request.form.get('phone')
        
        if not full_name or not email:
            flash('❌ الاسم الكامل والبريد الإلكتروني مطلوبان.')
            return redirect(url_for('edit_profile'))
        
        db = get_main_db()
        c = db.cursor()
        
        # التحقق من عدم وجود البريد الإلكتروني لدى مستخدم آخر
        c.execute('SELECT COUNT(*) FROM users WHERE email = ? AND id != ?', (email, user['id']))
        if c.fetchone()[0] > 0:
            flash('❌ البريد الإلكتروني مستخدم من قبل مستخدم آخر.')
            return redirect(url_for('edit_profile'))
        
        try:
            c.execute('UPDATE users SET full_name = ?, email = ?, phone = ? WHERE id = ?', 
                     (full_name, email, phone, user['id']))
            db.commit()
            
            # تحديث الجلسة
            session['full_name'] = full_name
            
            flash('✅ تم تحديث الملف الشخصي بنجاح.')
            return redirect(url_for('profile'))
        except Exception as e:
            flash(f'❌ خطأ في تحديث الملف الشخصي: {str(e)}')
            return redirect(url_for('edit_profile'))
    
    page = f'''
    <section class="wrapper style1 fade-up">
        <div class="inner">
            <h2>✏️ تعديل الملف الشخصي</h2>
            
            <form method="post" class="form">
                <div class="fields">
                    <div class="field">
                        <label for="full_name">الاسم الكامل *</label>
                        <input type="text" name="full_name" id="full_name" class="form-control" 
                               value="{user['full_name']}" required>
                    </div>
                    <div class="field half">
                        <label for="email">البريد الإلكتروني *</label>
                        <input type="email" name="email" id="email" class="form-control" 
                               value="{user['email']}" required>
                    </div>
                    <div class="field half">
                        <label for="phone">رقم الهاتف</label>
                        <input type="text" name="phone" id="phone" class="form-control" 
                               value="{user['phone'] or ''}" placeholder="رقم الهاتف (اختياري)">
                    </div>
                </div>
                <ul class="actions">
                    <li><button type="submit" class="button primary">💾 حفظ التغييرات</button></li>
                    <li><a href="/profile" class="button secondary">إلغاء</a></li>
                </ul>
            </form>
        </div>
    </section>
    '''
    return render_template_string(base_html.replace('%%CONTENT%%', page))

@app.route('/change_password', methods=['GET', 'POST'])
@login_required
def change_password():
    if request.method == 'POST':
        current_password = request.form.get('current_password')
        new_password = request.form.get('new_password')
        confirm_password = request.form.get('confirm_password')
        
        if not all([current_password, new_password, confirm_password]):
            flash('❌ يرجى ملء جميع الحقول.')
            return redirect(url_for('change_password'))
        
        if new_password != confirm_password:
            flash('❌ كلمة المرور الجديدة وتأكيدها غير متطابقتين.')
            return redirect(url_for('change_password'))
        
        if len(new_password) < 6:
            flash('❌ كلمة المرور الجديدة يجب أن تكون 6 أحرف على الأقل.')
            return redirect(url_for('change_password'))
        
        user = get_current_user()
        if not user:
            flash('❌ خطأ في تحميل بيانات المستخدم.')
            return redirect(url_for('login'))
        
        if not check_password_hash(user['password_hash'], current_password):
            flash('❌ كلمة المرور الحالية غير صحيحة.')
            return redirect(url_for('change_password'))
        
        db = get_main_db()
        c = db.cursor()
        new_password_hash = generate_password_hash(new_password)
        
        try:
            c.execute('UPDATE users SET password_hash = ? WHERE id = ?', (new_password_hash, user['id']))
            db.commit()
            flash('✅ تم تغيير كلمة المرور بنجاح.')
            return redirect(url_for('profile'))
        except Exception as e:
            flash(f'❌ خطأ في تغيير كلمة المرور: {str(e)}')
            return redirect(url_for('change_password'))
    
    page = '''
    <section class="wrapper style1 fade-up">
        <div class="inner">
            <h2>🔒 تغيير كلمة المرور</h2>
            
            <form method="post" class="form">
                <div class="fields">
                    <div class="field">
                        <label for="current_password">كلمة المرور الحالية *</label>
                        <input type="password" name="current_password" id="current_password" class="form-control" 
                               placeholder="أدخل كلمة المرور الحالية" required>
                    </div>
                    <div class="field half">
                        <label for="new_password">كلمة المرور الجديدة *</label>
                        <input type="password" name="new_password" id="new_password" class="form-control" 
                               placeholder="6 أحرف على الأقل" required minlength="6">
                    </div>
                    <div class="field half">
                        <label for="confirm_password">تأكيد كلمة المرور الجديدة *</label>
                        <input type="password" name="confirm_password" id="confirm_password" class="form-control" 
                               placeholder="أعد إدخال كلمة المرور الجديدة" required>
                    </div>
                </div>
                <ul class="actions">
                    <li><button type="submit" class="button primary">🔒 تغيير كلمة المرور</button></li>
                    <li><a href="/profile" class="button secondary">إلغاء</a></li>
                </ul>
            </form>
        </div>
    </section>
    '''
    return render_template_string(base_html.replace('%%CONTENT%%', page))

@app.route('/select_store')
@login_required
def select_store():
    """صفحة اختيار المحل"""
    user = get_current_user()
    if not user:
        flash('❌ خطأ في تحميل بيانات المستخدم.')
        return redirect(url_for('login'))
    
    db = get_main_db()
    c = db.cursor()
    
    # جلب المحلات التي يملكها المستخدم أو لديه صلاحيات عليها
    c.execute('''SELECT s.*, sp.permission_level 
                FROM stores s 
                LEFT JOIN store_permissions sp ON s.id = sp.store_id 
                WHERE (s.owner_id = ? OR sp.user_id = ?) AND s.is_active = 1
                ORDER BY s.store_name''', (user['id'], user['id']))
    stores = c.fetchall()
    
    page = '''
    <section class="wrapper style1 fade-up">
        <div class="inner">
            <h2>🏪 اختيار المحل</h2>
            <p>اختر المحل الذي تريد العمل عليه</p>
            
            <div class="fields">
                <div class="field">
                    <a href="/create_store" class="button primary">➕ إنشاء محل جديد</a>
                </div>
                <div class="field">
                    <a href="/test_store" class="button secondary">🧪 إنشاء محل تجريبي</a>
                </div>
            </div>
            
            <div class="table-wrapper">
                <table class="alt">
                    <thead>
                        <tr>
                            <th>اسم المحل</th>
                            <th>نوع المحل</th>
                            <th>صلاحياتك</th>
                            <th>تاريخ الإنشاء</th>
                            <th>إجراءات</th>
                        </tr>
                    </thead>
                    <tbody>
                        {% for store in stores %}
                        <tr>
                            <td><strong>{{store['store_name']}}</strong></td>
                            <td>{{store['store_type']}}</td>
                            <td>
                                {% if store['owner_id'] == user['id'] %}
                                    <span style="color: #4CAF50;">👑 مالك</span>
                                {% elif store['permission_level'] == 'manager' %}
                                    <span style="color: #2196F3;">👨‍💼 مدير</span>
                                {% elif store['permission_level'] == 'editor' %}
                                    <span style="color: #FF9800;">✏️ محرر</span>
                                {% else %}
                                    <span style="color: #9E9E9E;">👁️ مشاهد</span>
                                {% endif %}
                            </td>
                            <td>{{store['created_at'][:10]}}</td>
                            <td>
                                <a href="/switch_store/{{store['id']}}" class="button primary small">اختيار</a>
                                {% if store['owner_id'] == user['id'] %}
                                <a href="/delete_store/{{store['id']}}" class="button small" style="background-color: #ff6b6b; margin-left: 5px;" 
                                   onclick="return confirm('هل أنت متأكد من حذف هذا المحل؟ سيتم حذف جميع البيانات المرتبطة به نهائياً!')">🗑️ حذف</a>
                                {% endif %}
                            </td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
            
            {% if not stores %}
            <div style="text-align: center; padding: 2rem; background: rgba(255,255,255,0.1); border-radius: 10px; margin-top: 2rem;">
                <h3>لا توجد محلات متاحة</h3>
                <p>أنشئ محل جديد للبدء</p>
                <a href="/create_store" class="button primary">إنشاء محل جديد</a>
            </div>
            {% endif %}
        </div>
    </section>
    '''
    return render_template_string(base_html.replace('%%CONTENT%%', page), stores=stores, user=user)

@app.route('/create_store', methods=['GET', 'POST'])
@login_required
def create_store():
    """صفحة إنشاء محل جديد"""
    user = get_current_user()
    if not user:
        flash('❌ خطأ في تحميل بيانات المستخدم.')
        return redirect(url_for('login'))
    
    if request.method == 'POST':
        store_name = request.form.get('store_name')
        store_type = request.form.get('store_type', 'library')
        address = request.form.get('address')
        phone = request.form.get('phone')
        email = request.form.get('email')
        description = request.form.get('description')
        
        if not store_name:
            flash('❌ اسم المحل مطلوب.')
            return redirect(url_for('create_store'))
        
        db = get_main_db()
        c = db.cursor()
        
        # التحقق من عدم وجود محل بنفس الاسم للمستخدم
        c.execute('SELECT COUNT(*) FROM stores WHERE store_name = ? AND owner_id = ?', (store_name, user['id']))
        if c.fetchone()[0] > 0:
            flash('❌ لديك محل بنفس الاسم مسبقاً.')
            return redirect(url_for('create_store'))
        
        try:
            current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            c.execute('''INSERT INTO stores (store_name, owner_id, store_type, address, phone, email, description, created_at) 
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)''', 
                     (store_name, user['id'], store_type, address, phone, email, description, current_time))
            
            store_id = c.lastrowid
            
            # إعطاء صلاحيات كاملة للمالك
            c.execute('''INSERT INTO store_permissions (user_id, store_id, permission_level, granted_at) 
                        VALUES (?, ?, ?, ?)''', 
                     (user['id'], store_id, 'owner', current_time))
            
            db.commit()
            
            # إنشاء قاعدة بيانات المحل
            ensure_store_database_exists(store_id)
            
            flash(f'✅ تم إنشاء المحل "{store_name}" بنجاح.')
            return redirect(url_for('switch_store', store_id=store_id))
            
        except Exception as e:
            flash(f'❌ خطأ في إنشاء المحل: {str(e)}')
            return redirect(url_for('create_store'))
    
    page = '''
    <section class="wrapper style1 fade-up">
        <div class="inner">
            <h2>➕ إنشاء محل جديد</h2>
            <p>أنشئ محل جديد لإدارة أعمالك</p>
            
            <form method="post" class="form">
                <div class="fields">
                    <div class="field">
                        <label for="store_name">اسم المحل *</label>
                        <input type="text" name="store_name" id="store_name" class="form-control" 
                               placeholder="مثال: مكتبة النور، متجر الأقلام، إلخ" required>
                    </div>
                    <div class="field half">
                        <label for="store_type">نوع المحل</label>
                        <select name="store_type" id="store_type" class="form-select">
                            <option value="library">مكتبة</option>
                            <option value="stationery">قرطاسية</option>
                            <option value="bookstore">مكتبة كتب</option>
                            <option value="general">متجر عام</option>
                            <option value="other">أخرى</option>
                        </select>
                    </div>
                    <div class="field half">
                        <label for="phone">رقم الهاتف</label>
                        <input type="text" name="phone" id="phone" class="form-control" 
                               placeholder="رقم هاتف المحل (اختياري)">
                    </div>
                    <div class="field">
                        <label for="address">العنوان</label>
                        <input type="text" name="address" id="address" class="form-control" 
                               placeholder="عنوان المحل (اختياري)">
                    </div>
                    <div class="field">
                        <label for="email">البريد الإلكتروني</label>
                        <input type="email" name="email" id="email" class="form-control" 
                               placeholder="بريد المحل الإلكتروني (اختياري)">
                    </div>
                    <div class="field">
                        <label for="description">وصف المحل</label>
                        <textarea name="description" id="description" class="form-control" rows="3" 
                                  placeholder="وصف مختصر عن المحل ونوع المنتجات (اختياري)"></textarea>
                    </div>
                </div>
                <ul class="actions">
                    <li><button type="submit" class="button primary">➕ إنشاء المحل</button></li>
                    <li><a href="/select_store" class="button secondary">إلغاء</a></li>
                </ul>
            </form>
        </div>
    </section>
    '''
    return render_template_string(base_html.replace('%%CONTENT%%', page))

@app.route('/test_store')
@login_required
def test_store():
    """إنشاء محل تجريبي للاختبار"""
    user = get_current_user()
    if not user:
        flash('❌ خطأ في تحميل بيانات المستخدم.')
        return redirect(url_for('login'))
    
    db = get_main_db()
    c = db.cursor()
    
    try:
        current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        # إنشاء محل تجريبي
        c.execute('''INSERT INTO stores (store_name, owner_id, store_type, phone, address, email, description, created_at) 
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)''', 
                 ('مكتبة النور التجريبية', user['id'], 'library', '0555123456', 'شارع النور، حي الأمل', 'noor@test.com', 'مكتبة تجريبية لاختبار النظام', current_time))
        
        store_id = c.lastrowid
        
        # إعطاء صلاحيات كاملة للمالك
        c.execute('''INSERT INTO store_permissions (user_id, store_id, permission_level, granted_at) 
                    VALUES (?, ?, ?, ?)''', 
                 (user['id'], store_id, 'owner', current_time))
        
        db.commit()
        
        # إنشاء قاعدة بيانات المحل
        ensure_store_database_exists(store_id)
        
        flash('✅ تم إنشاء محل تجريبي بنجاح.')
        return redirect(url_for('switch_store', store_id=store_id))
        
    except Exception as e:
        flash(f'❌ خطأ في إنشاء المحل التجريبي: {str(e)}')
        return redirect(url_for('select_store'))

@app.route('/switch_store/<int:store_id>')
@login_required
def switch_store(store_id):
    """تبديل إلى محل محدد"""
    user = get_current_user()
    if not user:
        flash('❌ خطأ في تحميل بيانات المستخدم.')
        return redirect(url_for('login'))
    
    # التحقق من صلاحيات المستخدم على المحل
    if not check_store_permission(user['id'], store_id, 'viewer'):
        flash('❌ ليس لديك صلاحية للوصول إلى هذا المحل.')
        return redirect(url_for('select_store'))
    
    db = get_main_db()
    c = db.cursor()
    c.execute('SELECT * FROM stores WHERE id = ? AND is_active = 1', (store_id,))
    store = c.fetchone()
    
    if not store:
        flash('❌ المحل غير موجود أو غير نشط.')
        return redirect(url_for('select_store'))
    
    # تحديث الجلسة
    session['store_id'] = store['id']
    session['store_name'] = store['store_name']
    session['store_type'] = store['store_type']
    
    # إنشاء قاعدة بيانات المحل إذا لم تكن موجودة
    ensure_store_database_exists(store_id)
    
    flash(f'✅ تم التبديل إلى محل "{store["store_name"]}" بنجاح.')
    return redirect(url_for('index'))

@app.route('/delete_store/<int:store_id>')
@login_required
def delete_store(store_id):
    """حذف محل"""
    user = get_current_user()
    if not user:
        flash('❌ خطأ في تحميل بيانات المستخدم.')
        return redirect(url_for('login'))
    
    db = get_main_db()
    c = db.cursor()
    
    # التحقق من أن المستخدم هو مالك المحل
    c.execute('SELECT * FROM stores WHERE id = ? AND owner_id = ?', (store_id, user['id']))
    store = c.fetchone()
    
    if not store:
        flash('❌ المحل غير موجود أو ليس لديك صلاحية لحذفه.')
        return redirect(url_for('select_store'))
    
    try:
        # حذف المحل من قاعدة البيانات الرئيسية
        c.execute('DELETE FROM stores WHERE id = ?', (store_id,))
        c.execute('DELETE FROM store_permissions WHERE store_id = ?', (store_id,))
        
        # حذف قاعدة بيانات المحل
        store_db_path = get_store_db_path(store_id)
        if os.path.exists(store_db_path):
            os.remove(store_db_path)
        
        db.commit()
        
        # إذا كان المحل المحذوف هو المحل المحدد حالياً، إزالة الجلسة
        if session.get('store_id') == store_id:
            session.pop('store_id', None)
            session.pop('store_name', None)
            session.pop('store_type', None)
        
        flash(f'✅ تم حذف محل "{store["store_name"]}" وجميع بياناته بنجاح.')
        
    except Exception as e:
        flash(f'❌ خطأ في حذف المحل: {str(e)}')
    
    return redirect(url_for('select_store'))

@app.route('/store_settings', methods=['GET', 'POST'])
@login_required
@store_required
def store_settings():
    """صفحة إعدادات المحل"""
    user = get_current_user()
    store = get_current_store()
    
    if not user or not store:
        flash('❌ خطأ في تحميل بيانات المحل.')
        return redirect(url_for('index'))
    
    # التحقق من صلاحيات المستخدم (يجب أن يكون مالك أو مدير)
    if not check_store_permission(user['id'], store['id'], 'manager'):
        flash('❌ ليس لديك صلاحية لتعديل إعدادات المحل.')
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        store_name = request.form.get('store_name')
        store_type = request.form.get('store_type')
        address = request.form.get('address')
        phone = request.form.get('phone')
        email = request.form.get('email')
        description = request.form.get('description')
        
        if not store_name:
            flash('❌ اسم المحل مطلوب.')
            return redirect(url_for('store_settings'))
        
        db = get_main_db()
        c = db.cursor()
        
        # التحقق من عدم وجود محل بنفس الاسم للمستخدم
        c.execute('SELECT COUNT(*) FROM stores WHERE store_name = ? AND owner_id = ? AND id != ?', 
                 (store_name, user['id'], store['id']))
        if c.fetchone()[0] > 0:
            flash('❌ لديك محل بنفس الاسم مسبقاً.')
            return redirect(url_for('store_settings'))
        
        try:
            c.execute('''UPDATE stores SET store_name = ?, store_type = ?, address = ?, 
                        phone = ?, email = ?, description = ? WHERE id = ?''', 
                     (store_name, store_type, address, phone, email, description, store['id']))
            db.commit()
            
            # تحديث الجلسة
            session['store_name'] = store_name
            session['store_type'] = store_type
            
            flash('✅ تم تحديث إعدادات المحل بنجاح.')
            return redirect(url_for('store_settings'))
            
        except Exception as e:
            flash(f'❌ خطأ في تحديث إعدادات المحل: {str(e)}')
            return redirect(url_for('store_settings'))
    
    page = f'''
    <section class="wrapper style1 fade-up">
        <div class="inner">
            <h2>⚙️ إعدادات المحل</h2>
            <p>تعديل معلومات المحل: <strong>{store['store_name']}</strong></p>
            
            <form method="post" class="form">
                <div class="fields">
                    <div class="field">
                        <label for="store_name">اسم المحل *</label>
                        <input type="text" name="store_name" id="store_name" class="form-control" 
                               value="{store['store_name']}" required>
                    </div>
                    <div class="field half">
                        <label for="store_type">نوع المحل</label>
                        <select name="store_type" id="store_type" class="form-select">
                            <option value="library" {'selected' if store['store_type'] == 'library' else ''}>مكتبة</option>
                            <option value="stationery" {'selected' if store['store_type'] == 'stationery' else ''}>قرطاسية</option>
                            <option value="bookstore" {'selected' if store['store_type'] == 'bookstore' else ''}>مكتبة كتب</option>
                            <option value="general" {'selected' if store['store_type'] == 'general' else ''}>متجر عام</option>
                            <option value="other" {'selected' if store['store_type'] == 'other' else ''}>أخرى</option>
                        </select>
                    </div>
                    <div class="field half">
                        <label for="phone">رقم الهاتف</label>
                        <input type="text" name="phone" id="phone" class="form-control" 
                               value="{store['phone'] or ''}" placeholder="رقم هاتف المحل">
                    </div>
                    <div class="field">
                        <label for="address">العنوان</label>
                        <input type="text" name="address" id="address" class="form-control" 
                               value="{store['address'] or ''}" placeholder="عنوان المحل">
                    </div>
                    <div class="field">
                        <label for="email">البريد الإلكتروني</label>
                        <input type="email" name="email" id="email" class="form-control" 
                               value="{store['email'] or ''}" placeholder="بريد المحل الإلكتروني">
                    </div>
                    <div class="field">
                        <label for="description">وصف المحل</label>
                        <textarea name="description" id="description" class="form-control" rows="3" 
                                  placeholder="وصف مختصر عن المحل ونوع المنتجات">{store['description'] or ''}</textarea>
                    </div>
                </div>
                <ul class="actions">
                    <li><button type="submit" class="button primary">💾 حفظ التغييرات</button></li>
                    <li><a href="/" class="button secondary">العودة للرئيسية</a></li>
                </ul>
            </form>
        </div>
    </section>
    '''
    return render_template_string(base_html.replace('%%CONTENT%%', page))

# --------- Home: now serves only stats (no CMS check) ---------
@app.route('/')
def index():
    user = get_current_user()
    store = get_current_store()
    
    # إذا لم يكن المستخدم مسجل دخول
    if not user:
        page = '''
        <section class="wrapper style1 fade-up">
            <div class="inner">
                <ul class="actions">
                    <li><a href="/login" class="button primary">🔑 تسجيل الدخول</a></li>
                </ul>
            </div>
        </section>
        '''
        return render_template_string(base_html.replace('%%CONTENT%%', page))
    
    # إذا لم يكن هناك محل محدد
    if not store:
        page = f'''
        <section class="wrapper style1 fade-up">
            <div class="inner">
                <p>يجب اختيار محل للبدء.</p>
                <ul class="actions">
                    <li><a href="/select_store" class="button primary">🏪 اختيار محل</a></li>
                    <li><a href="/create_store" class="button secondary">➕ إنشاء محل جديد</a></li>
                </ul>
            </div>
        </section>
        '''
        return render_template_string(base_html.replace('%%CONTENT%%', page))
    
    # إذا كان هناك محل محدد، عرض الإحصائيات
    db = get_store_db()
    if db:
        c = db.cursor()
        c.execute('SELECT COUNT(*) as cnt FROM items'); items_count = c.fetchone()['cnt']
        c.execute('SELECT COUNT(*) as cnt FROM sales'); sales_count = c.fetchone()['cnt']
        c.execute("SELECT COALESCE(SUM(total),0) as sumt FROM sales")
        total_sales = c.fetchone()['sumt']
    else:
        items_count = sales_count = total_sales = 0

    # صفحة الرئيسية بتصميم Hyperspace (sections)
    welcome_message = f"""
    <section class="wrapper style3 fade-up">
        <div class="inner">
            <h2>مرحباً {user['full_name']}! 👋</h2>
            <p>مرحباً بك في <strong>{store['store_name']}</strong>. يمكنك الآن الوصول إلى جميع الميزات المتاحة.</p>
        </div>
    </section>
    """
    
    page = f"""
    {welcome_message}
    <section id="one" class="wrapper style2 spotlights">
      <section>
        <a href="/items" class="image"><img src="/static/images/pic01.jpg" alt="" data-position="center center" /></a>
        <div class="content">
          <div class="inner">
            <h2>الأصناف</h2>
            <p>عدد الأصناف المسجلة: <strong>{items_count}</strong></p>
            <ul class="actions">
              <li><a href="/items" class="button">عرض الأصناف</a></li>
            </ul>
          </div>
        </div>
      </section>

      <section>
        <a href="/invoices" class="image"><img src="/static/images/pic02.jpg" alt="" data-position="top center" /></a>
        <div class="content">
          <div class="inner">
            <h2>الفواتير</h2>
            <p>عدد الفواتير: <strong>{sales_count}</strong></p>
            <ul class="actions">
              <li><a href="/invoices" class="button">عرض الفواتير</a></li>
            </ul>
          </div>
        </div>
      </section>

      <section>
        <a href="/stats" class="image"><img src="/static/images/pic03.jpg" alt="" data-position="25% 25%" /></a>
        <div class="content">
          <div class="inner">
            <h2>المبيعات</h2>
            <p>إجمالي المبيعات: <strong>{total_sales} د.ج</strong></p>
            <ul class="actions">
              <li><a href="/stats" class="button">عرض الإحصائيات</a></li>
              <li><a href="/pos" class="button primary">اذهب لنقطة البيع</a></li>
            </ul>
          </div>
        </div>
      </section>
    </section>
    """
    return render_template_string(base_html.replace('%%CONTENT%%', page))

# --------- POS (نقطة البيع) ----- 
@app.route('/pos', methods=['GET','POST'])
@login_required
@store_required
def pos():
    db = get_db(); c = db.cursor()
    if request.method == 'POST':
        item_ids = request.form.getlist('item_id')
        qtys = request.form.getlist('qty')
        prices = request.form.getlist('price')
        customer_id = request.form.get('customer_id') or None
        new_customer_name = request.form.get('new_customer_name')
        
        # إذا تم إدخال اسم زبون جديد، احفظه أولاً
        if customer_id == 'new' and new_customer_name:
            c.execute('INSERT INTO customers (name) VALUES (?)', (new_customer_name,))
            customer_id = c.lastrowid
            db.commit()
        
        total = 0
        for i,q,p in zip(item_ids, qtys, prices):
            total += int(q) * float(p)
        date = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        c.execute('INSERT INTO sales (customer_id,date,total) VALUES (?,?,?)', (customer_id, date, total))
        sale_id = c.lastrowid
        for i,q,p in zip(item_ids, qtys, prices):
            iid = int(i); qq = int(q); pp = float(p)
            c.execute('INSERT INTO sale_items (sale_id,item_id,qty,price) VALUES (?,?,?,?)', (sale_id, iid, qq, pp))
            c.execute('UPDATE items SET qty = qty - ? WHERE id = ?', (qq, iid))
        db.commit()
        flash('تم تسجيل عملية البيع.')
        return redirect(url_for('invoice', id=sale_id))
    c.execute('SELECT * FROM items ORDER BY name'); items = c.fetchall()
    c.execute('SELECT * FROM customers ORDER BY name'); customers = c.fetchall()
    page = '''
    <section class="wrapper style1 fade-up"><div class="inner">
    <div class="row">
      <div class="col-8">
        <h3>نقطة البيع</h3>
        <form method="post" id="pos-form">
          <div class="fields">
            <div class="field">
              <label for="product-search">🔍 البحث عن منتج:</label>
              <input type="text" id="product-search" class="form-control" placeholder="اكتب اسم المنتج أو الكود للبحث...">
            </div>
          </div>
          <div class="fields">
            <div class="field fourty"><select id="product-select" class="form-select"><option value="">-- اختر صنف --</option>{% for it in items %}<option data-price="{{it['sell_price']}}" data-name="{{it['name']}}" data-code="{{it['code']}}" value="{{it['id']}}">{{it['name']}} ({{it['code']}}) - {{it['qty']}}</option>{% endfor %}</select></div>
            <div class="field quarter"><input id="product-qty" type="number" class="form-control" value="1" min="1"></div>
            <div class="field"><button id="add-btn" type="button" class="button primary fit">أضف</button></div>
          </div>

          <div class="table-wrapper">
          <table class="alt" id="cart-table">
            <thead><tr><th>اسم</th><th>سعر</th><th>كمية</th><th>المجموع</th><th>إجراء</th></tr></thead>
            <tbody></tbody>
          </table>
          </div>

          <div class="fields">
            <div class="field half">
              <label>زبون (اختياري)</label>
              <select name="customer_id" id="customer-select" class="form-select">
                <option value="">-- عميل عام --</option>
                {% for cu in customers %}<option value="{{cu['id']}}">{{cu['name']}}</option>{% endfor %}
                <option value="new">+ إضافة زبون جديد</option>
              </select>
            </div>
            <div class="field half" id="new-customer-fields" style="display: none;">
              <label>اسم الزبون الجديد</label>
              <input type="text" id="new-customer-name" class="form-control" placeholder="أدخل اسم الزبون">
            </div>
            <div class="field half text-left">
              <h4>المجموع الكلي: <span id="total">0.00</span> د.ج</h4>
              <button type="submit" class="button primary">✅ تأكيد البيع واطبع الفاتورة</button>
            </div>
          </div>
        </form>
      </div>
      <div class="col-4">
        <h5>منتجات سريعة</h5>
        <ul class="actions small fit">
          {% for it in items %}
            <li><button class="button small quick-add fit" data-id="{{it['id']}}" data-price="{{it['sell_price']}}">{{it['name']}} ({{it['qty']}})</button></li>
          {% endfor %}
        </ul>
      </div>
    </div>
    </div></section>

    <script>
      const itemsData = {};
      const allOptions = [];
      document.querySelectorAll('#product-select option').forEach(opt=>{ 
        if(opt.value) {
          itemsData[opt.value] = {name: opt.textContent, price: parseFloat(opt.dataset.price)};
          allOptions.push(opt);
        }
      });
      
      // وظيفة البحث
      document.getElementById('product-search').addEventListener('input', function() {
        const searchTerm = this.value.toLowerCase();
        const select = document.getElementById('product-select');
        
        // إخفاء جميع الخيارات
        allOptions.forEach(option => {
          option.style.display = 'none';
        });
        
        // إظهار الخيارات المطابقة
        allOptions.forEach(option => {
          const name = option.dataset.name ? option.dataset.name.toLowerCase() : '';
          const code = option.dataset.code ? option.dataset.code.toLowerCase() : '';
          const text = option.textContent.toLowerCase();
          
          if (name.includes(searchTerm) || code.includes(searchTerm) || text.includes(searchTerm)) {
            option.style.display = 'block';
          }
        });
        
        // إعادة تعيين القيمة المختارة إذا لم تعد متاحة
        if (select.value && select.selectedOptions[0].style.display === 'none') {
          select.value = '';
        }
      });
      
      function recalc(){
        let total = 0;
        document.querySelectorAll('#cart-table tbody tr').forEach(tr=>{
          const price = parseFloat(tr.dataset.price);
          const qty = parseInt(tr.querySelector('.c-qty').value);
          const line = price * qty;
          tr.querySelector('.c-line').textContent = line.toFixed(2);
          total += line;
        });
        document.getElementById('total').textContent = total.toFixed(2);
      }
      document.getElementById('add-btn').addEventListener('click', ()=>{
        const sel = document.getElementById('product-select'); const id = sel.value; if(!id) return;
        const qty = parseInt(document.getElementById('product-qty').value)||1; const price = itemsData[id].price; const name = itemsData[id].name;
        addRow(id, name, price, qty);
      });
      function addRow(id,name,price,qty){
        const tbody = document.querySelector('#cart-table tbody');
        let existing = tbody.querySelector('tr[data-id="'+id+'"]');
        if(existing){ const qinput = existing.querySelector('.c-qty'); qinput.value = parseInt(qinput.value) + qty; recalc(); return; }
        const tr = document.createElement('tr'); tr.dataset.id = id; tr.dataset.price = price;
        tr.innerHTML = `<td>${name}</td><td>${price.toFixed(2)}</td><td><input name="qty" class="form-control c-qty" value="${qty}" min="1"></td><td class="c-line">${(price*qty).toFixed(2)}</td><td><button type="button" class="button small secondary remove">❌</button></td>`;
        tbody.appendChild(tr);
        tr.querySelector('.remove').addEventListener('click', ()=>{ tr.remove(); recalc(); });
        tr.querySelector('.c-qty').addEventListener('change', recalc);
        recalc();
      }
      document.querySelectorAll('.quick-add').forEach(btn=>{ btn.addEventListener('click', ()=>{ const id = btn.dataset.id; const price = parseFloat(btn.dataset.price); const name = btn.textContent.trim().split(' (')[0]; addRow(id, name, price, 1); }); });
      
      // التعامل مع إضافة زبون جديد
      document.getElementById('customer-select').addEventListener('change', function() {
        const newCustomerFields = document.getElementById('new-customer-fields');
        if (this.value === 'new') {
          newCustomerFields.style.display = 'block';
          document.getElementById('new-customer-name').focus();
        } else {
          newCustomerFields.style.display = 'none';
        }
      });
      
      document.getElementById('pos-form').addEventListener('submit', function(e){
        const tbody = document.querySelector('#cart-table tbody');
        if(tbody.children.length === 0){ e.preventDefault(); alert('لا يوجد منتجات في السلة'); return false; }
        
        // التحقق من إدخال اسم زبون جديد
        const customerSelect = document.getElementById('customer-select');
        const newCustomerName = document.getElementById('new-customer-name');
        if (customerSelect.value === 'new' && !newCustomerName.value.trim()) {
          e.preventDefault();
          alert('يرجى إدخال اسم الزبون الجديد');
          newCustomerName.focus();
          return false;
        }
        
        const form = this; document.querySelectorAll('.hidden-input').forEach(n=>n.remove());
        Array.from(tbody.children).forEach(tr=>{
          const id = tr.dataset.id; const price = tr.dataset.price; const qty = tr.querySelector('.c-qty').value;
          const inp1 = document.createElement('input'); inp1.type='hidden'; inp1.name='item_id'; inp1.value=id; inp1.className='hidden-input';
          const inp2 = document.createElement('input'); inp2.type='hidden'; inp2.name='price'; inp2.value=price; inp2.className='hidden-input';
          const inp3 = document.createElement('input'); inp3.type='hidden'; inp3.name='qty'; inp3.value=qty; inp3.className='hidden-input';
          form.appendChild(inp1); form.appendChild(inp2); form.appendChild(inp3);
        });
        
        // إضافة اسم الزبون الجديد إذا تم إدخاله
        if (customerSelect.value === 'new' && newCustomerName.value.trim()) {
          const newCustomerInput = document.createElement('input');
          newCustomerInput.type = 'hidden';
          newCustomerInput.name = 'new_customer_name';
          newCustomerInput.value = newCustomerName.value.trim();
          form.appendChild(newCustomerInput);
        }
      });
    </script>
    '''
    return render_template_string(base_html.replace('%%CONTENT%%', page), items=items, customers=customers)

# --------- Invoice view/print ---------
@app.route('/invoice/<int:id>')
@login_required
@store_required
def invoice(id):
    db = get_db(); c = db.cursor()
    c.execute('SELECT s.*, c.name as cust_name FROM sales s LEFT JOIN customers c ON c.id=s.customer_id WHERE s.id=?', (id,))
    s = c.fetchone()
    if not s: return 'غير موجود'
    c.execute('SELECT si.*, it.name FROM sale_items si LEFT JOIN items it ON it.id=si.item_id WHERE si.sale_id=?', (id,))
    lines = c.fetchall()
    
    page = '''
    <section class="wrapper style1 fade-up">
        <div class="inner">
            <div class="invoice-container" id="invoice-content" style="width: 210mm; margin: 0 auto; background: white; padding: 10mm; box-sizing: border-box; font-family: 'Cairo', Arial, sans-serif;">
                <!-- ترويسة الفاتورة -->
                <div class="invoice-header text-center" style="border-bottom: 2px solid #000; padding-bottom: 8px; margin-bottom: 15px;">
                    <h1 style="color: #000; margin: 0; font-size: 26px; font-weight: bold;">{{store['store_name']}}</h1>
                    <h2 style="color: #000; margin: 3px 0 10px 0; font-size: 20px; font-weight: bold;">فاتورة بيع</h2>
                    
                    <div style="display: flex; justify-content: space-between; background: #f0f0f0; padding: 8px; border-radius: 4px; font-size: 14px; border: 1px solid #000;">
                        <div style="font-weight: bold;"><strong>رقم الفاتورة:</strong> #{{s['id']}}</div>
                        <div style="font-weight: bold;"><strong>التاريخ:</strong> {{s['date'][:16]}}</div>
                    </div>
                </div>

                <!-- معلومات الزبون -->
                <div style="margin-bottom: 15px; padding: 8px; background: #f8f8f8; border-radius: 4px; border: 1px solid #000;">
                    <h4 style="margin: 0 0 6px 0; color: #000; font-size: 16px; font-weight: bold;">معلومات الزبون</h4>
                    <p style="margin: 0; font-size: 14px; color: #000;"><strong>الاسم:</strong> {{s['cust_name'] or 'عميل عام'}}</p>
                </div>

                <!-- جدول المنتجات -->
                <div style="margin: 15px 0;">
                    <table style="width: 100%; border-collapse: collapse; font-size: 12px; border: 2px solid #000;">
                        <thead style="background: #e0e0e0; color: #000;">
                            <tr>
                                <th style="padding: 8px 6px; text-align: right; width: 50%; border: 1px solid #000; font-weight: bold;">الصنف</th>
                                <th style="padding: 8px 6px; text-align: center; width: 15%; border: 1px solid #000; font-weight: bold;">السعر</th>
                                <th style="padding: 8px 6px; text-align: center; width: 15%; border: 1px solid #000; font-weight: bold;">الكمية</th>
                                <th style="padding: 8px 6px; text-align: center; width: 20%; border: 1px solid #000; font-weight: bold;">المجموع</th>
                            </tr>
                        </thead>
                        <tbody>
                            {% for l in lines %}
                            <tr>
                                <td style="padding: 6px 6px; text-align: right; border: 1px solid #000; color: #000; font-weight: normal;">{{l['name']}}</td>
                                <td style="padding: 6px 6px; text-align: center; border: 1px solid #000; color: #000; font-weight: normal;">{{ '%.2f' % l['price'] }} د.ج</td>
                                <td style="padding: 6px 6px; text-align: center; border: 1px solid #000; color: #000; font-weight: normal;">{{l['qty']}}</td>
                                <td style="padding: 6px 6px; text-align: center; border: 1px solid #000; color: #000; font-weight: normal;">{{ '%.2f' % (l['price'] * l['qty']) }} د.ج</td>
                            </tr>
                            {% endfor %}
                            
                            <!-- أسطر فارغة أقل -->
                            {% for i in range(8 - lines|length) %}
                            <tr>
                                <td style="padding: 6px 6px; border: 1px solid #000; color: #000;">&nbsp;</td>
                                <td style="padding: 6px 6px; border: 1px solid #000; color: #000;">&nbsp;</td>
                                <td style="padding: 6px 6px; border: 1px solid #000; color: #000;">&nbsp;</td>
                                <td style="padding: 6px 6px; border: 1px solid #000; color: #000;">&nbsp;</td>
                            </tr>
                            {% endfor %}
                        </tbody>
                    </table>
                </div>

                <!-- المجموع والتوقيع -->
                <div style="display: flex; justify-content: space-between; margin-top: 20px; align-items: flex-start;">
                    <!-- المجموع الكلي -->
                    <div style="flex: 1; margin-left: 15px;">
                        <div style="background: #f0f0f0; padding: 15px; border-radius: 4px; text-align: center; border: 2px solid #000;">
                            <h4 style="margin: 0 0 10px 0; color: #000; font-size: 16px; font-weight: bold;">المجموع الكلي</h4>
                            <div style="font-size: 22px; font-weight: bold; color: #000;">{{ '%.2f' % s['total'] }} د.ج</div>
                        </div>
                    </div>

                    <!-- توقيع البائع فقط -->
                    <div style="flex: 1; text-align: center;">
                        <div style="border-top: 2px solid #000; width: 200px; margin: 0 auto; padding-top: 40px;">
                            <p style="margin: 0; font-size: 14px; color: #000; font-weight: bold;">توقيع البائع</p>
                        </div>
                    </div>
                </div>

                <!-- ملاحظات وإشعارات -->
                <div style="margin-top: 20px; padding: 12px; background: #f8f8f8; border: 1px solid #000; border-radius: 4px; font-size: 11px;">
                    <h5 style="color: #000; margin: 0 0 8px 0; font-size: 14px; font-weight: bold; text-align: center;">شروط وإشعارات:</h5>
                    <div style="display: flex; justify-content: space-between; gap: 15px;">
                        <div style="flex: 1;">
                            <p style="margin: 4px 0; color: #000; line-height: 1.4;">
                                • المرتجعات خلال 7 أيام من تاريخ الشراء<br>
                                • يرجى فحص المنتج قبل المغادرة<br>
                                • لا يوجد استرداد نقدي
                            </p>
                        </div>
                        <div style="flex: 1; text-align: right;">
                            <p style="margin: 4px 0; color: #000; line-height: 1.4;">
                                • للاستفسار: <strong style="font-size: 12px;">{{store['phone'] or '0676904111'}}</strong><br>
                                • الاستبدال بشروط وأحكام<br>
                                • الفاتورة واجبة الدفع فوراً<br>
                                • ختم المكتبة ضروري
                            </p>
                        </div>
                    </div>
                </div>

                <!-- تذييل الفاتورة -->
                <div style="margin-top: 15px; text-align: center; padding-top: 10px; border-top: 1px solid #000; font-size: 11px; color: #000;">
                    <p style="margin: 0; font-weight: bold;">{{store['store_name']}} - جميع المواد التعليمية والقرطاسية - هاتف: {{store['phone'] or '0676904111'}}</p>
                    <p style="margin: 3px 0 0 0; font-size: 10px;">شكراً لثقتكم ونرحب بزيارتكم دائماً</p>
                </div>
            </div>

            <!-- أزرار التحكم -->
            <div class="text-center mt-3 actions" style="margin-top: 20px;">
                <button class="button primary" onclick="printInvoice()">🖨️ طباعة الفاتورة</button>
                <a class="button secondary" href="/pos">رجوع لنقطة البيع</a>
                <a class="button" href="/invoices">عرض جميع الفواتير</a>
            </div>
        </div>
    </section>

    <style>
        @media print {
            body, html {
                margin: 0 !important;
                padding: 0 !important;
                background: white !important;
                width: 210mm;
                height: 297mm;
            }
            
            * {
                color: #000 !important;
                font-weight: normal;
            }
            
            .wrapper, .inner, .invoice-container {
                margin: 0 !important;
                padding: 0 !important;
                width: 210mm !important;
                box-shadow: none !important;
                background: white !important;
            }
            
            #invoice-content {
                width: 210mm !important;
                margin: 0 auto !important;
                padding: 10mm !important;
                box-sizing: border-box;
                border: none !important;
            }
            
            .actions, .actions *,
            #sidebar, #footer,
            .wrapper.style1-alt {
                display: none !important;
            }
            
            /* تحسين مظهر الجدول عند الطباعة */
            table, th, td {
                border: 1px solid #000 !important;
                color: #000 !important;
                background: white !important;
            }
            
            th {
                background: #e0e0e0 !important;
                color: #000 !important;
                font-weight: bold !important;
            }
            
            td {
                background: white !important;
                color: #000 !important;
                font-weight: normal !important;
            }
        }
        
        .invoice-container {
            background: white;
            border-radius: 8px;
            box-shadow: 0 0 15px rgba(0,0,0,0.1);
            border: 1px solid #ccc;
        }
        
        @page {
            size: A4;
            margin: 0;
        }
        
        /* ضمان طباعة الفاتورة في ورقة واحدة */
        @media print {
            body {
                -webkit-print-color-adjust: exact;
                print-color-adjust: exact;
            }
            
            .invoice-container {
                page-break-inside: avoid;
                break-inside: avoid;
            }
            
            /* تقليل المسافات للطباعة */
            .invoice-header {
                margin-bottom: 10px !important;
            }
            
            .invoice-container > div {
                margin-bottom: 8px !important;
            }
            
            /* تقليل حجم الخط قليلاً للطباعة */
            .invoice-container {
                font-size: 12px !important;
            }
            
            .invoice-container h1 {
                font-size: 22px !important;
            }
            
            .invoice-container h2 {
                font-size: 18px !important;
            }
        }
    </style>

    <script>
        function printInvoice() {
            window.print();
        }
    </script>
    '''
    store = get_current_store()
    return render_template_string(base_html.replace('%%CONTENT%%', page), s=s, lines=lines, store=store)

# --------- Invoices list ---------
@app.route('/invoices')
@login_required
@store_required
def invoices():
    db = get_db(); c = db.cursor()
    c.execute('SELECT s.*, c.name as cust_name FROM sales s LEFT JOIN customers c ON c.id=s.customer_id ORDER BY date DESC')
    rows = c.fetchall()
    page = '''
    <section class="wrapper style3 fade-up">
        <div class="inner">
            <div class="d-flex justify-content-between mb-2">
                <h3>الفواتير السابقة</h3>
            </div>
            <div class="table-wrapper">
                <table class="alt">
                    <thead>
                        <tr>
                            <th>رقم</th>
                            <th>تاريخ</th>
                            <th>زبون</th>
                            <th>المجموع</th>
                            <th>اجراء</th>
                        </tr>
                    </thead>
                    <tbody>
                        {% for r in rows %}
                        <tr>
                            <td>{{r['id']}}</td>
                            <td>{{r['date']}}</td>
                            <td>{{r['cust_name'] or 'عام'}}</td>
                            <td>{{r['total']}}</td>
                            <td>
                                <a class="button small" href="/invoice/{{r['id']}}" target="_blank">عرض/طباعة</a>
                                <a class="button small primary" href="/invoices/edit/{{r['id']}}">تعديل</a>
                                <a class="button small secondary" href="/invoices/delete/{{r['id']}}" onclick="return confirm('هل أنت متأكد من حذف هذه الفاتورة؟')">حذف</a>
                            </td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
        </div>
    </section>
    '''
    return render_template_string(base_html.replace('%%CONTENT%%', page), rows=rows)

# --------- Edit Invoice ---------
@app.route('/invoices/edit/<int:id>', methods=['GET', 'POST'])
@login_required
@store_required
def edit_invoice(id):
    db = get_db(); c = db.cursor()
    
    # جلب بيانات الفاتورة
    c.execute('SELECT s.*, c.name as cust_name FROM sales s LEFT JOIN customers c ON c.id=s.customer_id WHERE s.id=?', (id,))
    invoice = c.fetchone()
    if not invoice:
        flash('❌ الفاتورة غير موجودة.')
        return redirect(url_for('invoices'))
    
    # جلب عناصر الفاتورة
    c.execute('SELECT si.*, it.name, it.code FROM sale_items si LEFT JOIN items it ON it.id=si.item_id WHERE si.sale_id=?', (id,))
    invoice_items = c.fetchall()
    
    if request.method == 'POST':
        # تحديث بيانات الفاتورة الأساسية
        customer_id = request.form.get('customer_id') or None
        date = request.form.get('date')
        
        # جلب العناصر القديمة لتحديث المخزون
        c.execute('SELECT item_id, qty FROM sale_items WHERE sale_id=?', (id,))
        old_items = c.fetchall()
        
        # إرجاع الكميات القديمة للمخزون
        for old_item in old_items:
            c.execute('UPDATE items SET qty = qty + ? WHERE id = ?', (old_item['qty'], old_item['item_id']))
        
        # تحديث الفاتورة
        c.execute('UPDATE sales SET customer_id=?, date=? WHERE id=?', (customer_id, date, id))
        
        # حذف العناصر القديمة
        c.execute('DELETE FROM sale_items WHERE sale_id=?', (id,))
        
        # إضافة العناصر الجديدة
        item_ids = request.form.getlist('item_id')
        qtys = request.form.getlist('qty')
        prices = request.form.getlist('price')
        
        total = 0
        for i, q, p in zip(item_ids, qtys, prices):
            if i and q and p:  # التأكد من وجود القيم
                item_id = int(i)
                qty = int(q)
                price = float(p)
                total += qty * price
                
                # إضافة العنصر
                c.execute('INSERT INTO sale_items (sale_id, item_id, qty, price) VALUES (?, ?, ?, ?)', 
                         (id, item_id, qty, price))
                
                # خصم الكمية الجديدة من المخزون
                c.execute('UPDATE items SET qty = qty - ? WHERE id = ?', (qty, item_id))
        
        # تحديث المجموع الكلي
        c.execute('UPDATE sales SET total=? WHERE id=?', (total, id))
        
        db.commit()
        flash('✅ تم تعديل الفاتورة بنجاح.')
        return redirect(url_for('invoice', id=id))
    
    # جلب البيانات المطلوبة للنموذج
    c.execute('SELECT * FROM customers ORDER BY name')
    customers = c.fetchall()
    c.execute('SELECT * FROM items ORDER BY name')
    items = c.fetchall()
    
    page = '''
    <section class="wrapper style1 fade-up">
        <div class="inner">
            <h3>تعديل الفاتورة رقم {{invoice['id']}}</h3>
            
            <form method="post" class="form">
                <div class="fields">
                    <div class="field half">
                        <label for="customer_id">الزبون</label>
                        <select name="customer_id" id="customer_id" class="form-select">
                            <option value="">-- عميل عام --</option>
                            {% for c in customers %}
                            <option value="{{c['id']}}" {% if c['id'] == invoice['customer_id'] %}selected{% endif %}>{{c['name']}}</option>
                            {% endfor %}
                        </select>
                    </div>
                    <div class="field half">
                        <label for="date">التاريخ</label>
                        <input type="datetime-local" name="date" id="date" class="form-control" 
                               value="{{invoice['date'][:16]}}" required>
                    </div>
                </div>
                
                <h4>عناصر الفاتورة</h4>
                <div class="fields">
                    <div class="field">
                        <label for="item-search">🔍 البحث عن منتج:</label>
                        <input type="text" id="item-search" class="form-control" placeholder="اكتب اسم المنتج أو الكود للبحث...">
                    </div>
                </div>
                <div class="table-wrapper">
                    <table class="alt" id="invoice-items-table">
                        <thead>
                            <tr>
                                <th>الصنف</th>
                                <th>السعر</th>
                                <th>الكمية</th>
                                <th>المجموع</th>
                                <th>إجراء</th>
                            </tr>
                        </thead>
                        <tbody>
                            {% for item in invoice_items %}
                            <tr data-item-id="{{item['item_id']}}">
                                <td>
                                    <select name="item_id" class="form-select item-select" required>
                                        <option value="">-- اختر صنف --</option>
                                        {% for it in items %}
                                        <option value="{{it['id']}}" data-price="{{it['sell_price']}}" 
                                                {% if it['id'] == item['item_id'] %}selected{% endif %}>
                                            {{it['name']}} ({{it['code']}})
                                        </option>
                                        {% endfor %}
                                    </select>
                                </td>
                                <td>
                                    <input type="number" step="0.01" name="price" class="form-control price-input" 
                                           value="{{item['price']}}" required>
                                </td>
                                <td>
                                    <input type="number" name="qty" class="form-control qty-input" 
                                           value="{{item['qty']}}" min="1" required>
                                </td>
                                <td class="line-total">{{item['price'] * item['qty']}}</td>
                                <td>
                                    <button type="button" class="button small secondary remove-item">حذف</button>
                                </td>
                            </tr>
                            {% endfor %}
                        </tbody>
                    </table>
                </div>
                
                <div class="fields">
                    <div class="field">
                        <button type="button" class="button primary" id="add-item">إضافة صنف</button>
                    </div>
                    <div class="field">
                        <h4>المجموع الكلي: <span id="total-amount">{{invoice['total']}}</span> د.ج</h4>
                    </div>
                </div>
                
                <ul class="actions">
                    <li><button type="submit" class="button primary">💾 حفظ التعديلات</button></li>
                    <li><a href="/invoices" class="button secondary">إلغاء</a></li>
                </ul>
            </form>
        </div>
    </section>
    
    <script>
        // وظيفة البحث في المنتجات
        document.getElementById('item-search').addEventListener('input', function() {
            const searchTerm = this.value.toLowerCase();
            const selects = document.querySelectorAll('.item-select');
            
            selects.forEach(select => {
                const options = select.querySelectorAll('option');
                options.forEach(option => {
                    if (option.value === '') {
                        option.style.display = 'block'; // إظهار الخيار الافتراضي
                        return;
                    }
                    
                    const text = option.textContent.toLowerCase();
                    if (text.includes(searchTerm)) {
                        option.style.display = 'block';
                    } else {
                        option.style.display = 'none';
                    }
                });
            });
        });
        
        // إضافة صنف جديد
        document.getElementById('add-item').addEventListener('click', function() {
            const tbody = document.querySelector('#invoice-items-table tbody');
            const newRow = document.createElement('tr');
            newRow.innerHTML = `
                <td>
                    <select name="item_id" class="form-select item-select" required>
                        <option value="">-- اختر صنف --</option>
                        {% for it in items %}
                        <option value="{{it['id']}}" data-price="{{it['sell_price']}}">
                            {{it['name']}} ({{it['code']}})
                        </option>
                        {% endfor %}
                    </select>
                </td>
                <td>
                    <input type="number" step="0.01" name="price" class="form-control price-input" required>
                </td>
                <td>
                    <input type="number" name="qty" class="form-control qty-input" value="1" min="1" required>
                </td>
                <td class="line-total">0.00</td>
                <td>
                    <button type="button" class="button small secondary remove-item">حذف</button>
                </td>
            `;
            tbody.appendChild(newRow);
            
            // إضافة مستمعي الأحداث للصف الجديد
            setupRowEvents(newRow);
        });
        
        // حذف صف
        function setupRowEvents(row) {
            // حذف الصف
            row.querySelector('.remove-item').addEventListener('click', function() {
                row.remove();
                calculateTotal();
            });
            
            // تحديث السعر عند تغيير الصنف
            row.querySelector('.item-select').addEventListener('change', function() {
                const selectedOption = this.options[this.selectedIndex];
                const price = selectedOption.dataset.price || 0;
                row.querySelector('.price-input').value = price;
                calculateLineTotal(row);
            });
            
            // تحديث المجموع عند تغيير السعر أو الكمية
            row.querySelector('.price-input').addEventListener('input', calculateLineTotal.bind(null, row));
            row.querySelector('.qty-input').addEventListener('input', calculateLineTotal.bind(null, row));
        }
        
        // حساب مجموع الصف
        function calculateLineTotal(row) {
            const price = parseFloat(row.querySelector('.price-input').value) || 0;
            const qty = parseInt(row.querySelector('.qty-input').value) || 0;
            const total = price * qty;
            row.querySelector('.line-total').textContent = total.toFixed(2);
            calculateTotal();
        }
        
        // حساب المجموع الكلي
        function calculateTotal() {
            let total = 0;
            document.querySelectorAll('.line-total').forEach(cell => {
                total += parseFloat(cell.textContent) || 0;
            });
            document.getElementById('total-amount').textContent = total.toFixed(2);
        }
        
        // إعداد مستمعي الأحداث للصفوف الموجودة
        document.querySelectorAll('#invoice-items-table tbody tr').forEach(setupRowEvents);
    </script>
    '''
    
    return render_template_string(base_html.replace('%%CONTENT%%', page), 
                                invoice=invoice, invoice_items=invoice_items, 
                                customers=customers, items=items)

# --------- Delete Invoice ---------
@app.route('/invoices/delete/<int:id>')
@login_required
@store_required
def delete_invoice(id):
    db = get_db(); c = db.cursor()
    
    # جلب عناصر الفاتورة لإرجاع الكميات للمخزون
    c.execute('SELECT item_id, qty FROM sale_items WHERE sale_id=?', (id,))
    items = c.fetchall()
    
    # إرجاع الكميات للمخزون
    for item in items:
        c.execute('UPDATE items SET qty = qty + ? WHERE id = ?', (item['qty'], item['item_id']))
    
    # حذف عناصر الفاتورة
    c.execute('DELETE FROM sale_items WHERE sale_id=?', (id,))
    
    # حذف الفاتورة
    c.execute('DELETE FROM sales WHERE id=?', (id,))
    
    db.commit()
    flash('✅ تم حذف الفاتورة بنجاح وإرجاع الكميات للمخزون.')
    return redirect(url_for('invoices'))

# --------- Items management (inventory) ---------
@app.route('/items')
@login_required
@store_required
def items():
    db = get_db(); c = db.cursor(); c.execute('SELECT * FROM items ORDER BY name'); rows = c.fetchall()
    page = '''<section class="wrapper style1 fade-up"><div class="inner"><div class="d-flex justify-content-between mb-2"><h3>المخزون</h3><a class="button primary" href="/items/add">أضف صنف</a></div><div class="table-wrapper"><table class="alt"><thead><tr><th>كود</th><th>اسم</th><th>سعر شراء</th><th>سعر بيع</th><th>كمية</th><th>اجراء</th></tr></thead><tbody>{% for r in rows %}<tr><td>{{r['code']}}</td><td>{{r['name']}}</td><td>{{r['buy_price']}}</td><td>{{r['sell_price']}}</td><td>{{r['qty']}}</td><td><a class="button small" href="/items/edit/{{r['id']}}">تعديل</a> <a class="button small secondary" href="/items/delete/{{r['id']}}" onclick="return confirm('هل أنت متأكد من حذف هذا الصنف؟')">حذف</a></td></tr>{% endfor %}</tbody></table></div></div></section>'''
    return render_template_string(base_html.replace('%%CONTENT%%', page), rows=rows)

@app.route('/items/add', methods=['GET','POST'])
@login_required
@store_required
def items_add():
    if request.method=='POST':
        code = request.form.get('code'); name = request.form.get('name')
        buy = float(request.form.get('buy_price') or 0); sell = float(request.form.get('sell_price') or 0);
        qty = int(request.form.get('qty') or 0)
        db = get_db(); c = db.cursor()
        try:
            c.execute('INSERT INTO items (code,name,buy_price,sell_price,qty) VALUES (?,?,?,?,?)', (code,name,buy,sell,qty))
            db.commit()
        except Exception as e:
            if 'UNIQUE constraint failed' in str(e):
                flash(f'❌ خطأ: الكود "{code}" موجود مسبقاً.')
            else:
                flash(f"❌ خطأ: {e}")
            return redirect(url_for('items_add'))
        flash('✅ تم إضافة الصنف بنجاح.')
        return redirect(url_for('items'))
    
    page = '''
    <section class="wrapper style1 fade-up"><div class="inner">
        <h3>أضف صنف جديد</h3>
        <form method="post" class="form">
            <div class="fields">
                <div class="field half">
                    <label for="code">كود الصنف</label>
                    <input type="text" name="code" id="code" class="form-control" placeholder="الكود" required>
                </div>
                <div class="field half">
                    <label for="name">اسم الصنف</label>
                    <input type="text" name="name" id="name" class="form-control" placeholder="الاسم" required>
                </div>
                <div class="field half">
                    <label for="buy_price">سعر الشراء</label>
                    <input type="number" step="0.01" name="buy_price" id="buy_price" class="form-control" value="0">
                </div>
                <div class="field half">
                    <label for="sell_price">سعر البيع</label>
                    <input type="number" step="0.01" name="sell_price" id="sell_price" class="form-control" value="0">
                </div>
                <div class="field">
                    <label for="qty">الكمية الأولية</label>
                    <input type="number" name="qty" id="qty" class="form-control" value="0">
                </div>
            </div>
            <ul class="actions">
                <li><button type="submit" class="button primary">💾 حفظ الصنف</button></li>
                <li><a href="/items" class="button secondary">إلغاء</a></li>
            </ul>
        </form>
    </div></section>
    '''
    return render_template_string(base_html.replace('%%CONTENT%%', page))

@app.route('/items/edit/<int:id>', methods=['GET','POST'])
@login_required
@store_required
def items_edit(id):
    db = get_db(); c = db.cursor(); c.execute('SELECT * FROM items WHERE id=?', (id,)); r = c.fetchone()
    if not r: return 'غير موجود'
    if request.method=='POST':
        code = request.form.get('code'); name = request.form.get('name')
        buy = float(request.form.get('buy_price') or 0); sell = float(request.form.get('sell_price') or 0); qty = int(request.form.get('qty') or 0)
        try:
            c.execute('UPDATE items SET code=?,name=?,buy_price=?,sell_price=?,qty=? WHERE id=?', (code,name,buy,sell,qty,id)); db.commit();
        except Exception as e:
            if 'UNIQUE constraint failed' in str(e):
                flash(f'❌ خطأ: الكود "{code}" موجود مسبقاً لصنف آخر.')
            else:
                flash(f"❌ خطأ: {e}")
            return redirect(url_for('items_edit', id=id))
        flash('✅ تم تعديل الصنف بنجاح.')
        return redirect(url_for('items'))

    page = f"""
    <section class="wrapper style1 fade-up"><div class="inner">
        <h3>تعديل صنف: {r['name']}</h3>
        <form method="post" class="form">
            <div class="fields">
                <div class="field half">
                    <label for="code">كود الصنف</label>
                    <input type="text" name="code" id="code" class="form-control" value="{r['code']}">
                </div>
                <div class="field half">
                    <label for="name">اسم الصنف</label>
                    <input type="text" name="name" id="name" class="form-control" value="{r['name']}">
                </div>
                <div class="field half">
                    <label for="buy_price">سعر الشراء</label>
                    <input type="number" step="0.01" name="buy_price" id="buy_price" class="form-control" value="{r['buy_price']}">
                </div>
                <div class="field half">
                    <label for="sell_price">سعر البيع</label>
                    <input type="number" step="0.01" name="sell_price" id="sell_price" class="form-control" value="{r['sell_price']}">
                </div>
                <div class="field">
                    <label for="qty">الكمية المتوفرة</label>
                    <input type="number" name="qty" id="qty" class="form-control" value="{r['qty']}">
                </div>
            </div>
            <ul class="actions">
                <li><button type="submit" class="button primary">💾 حفظ التعديلات</button></li>
                <li><a href="/items" class="button secondary">إلغاء</a></li>
            </ul>
        </form>
    </div></section>
    """
    return render_template_string(base_html.replace('%%CONTENT%%', page))

# --------- Delete Item ---------
@app.route('/items/delete/<int:id>')
@login_required
@store_required
def delete_item(id):
    db = get_db(); c = db.cursor()
    
    # التحقق من وجود الصنف
    c.execute('SELECT * FROM items WHERE id=?', (id,))
    item = c.fetchone()
    if not item:
        flash('❌ الصنف غير موجود.')
        return redirect(url_for('items'))
    
    # التحقق من وجود الصنف في الفواتير أو المشتريات
    c.execute('SELECT COUNT(*) as count FROM sale_items WHERE item_id=?', (id,))
    sales_count = c.fetchone()['count']
    c.execute('SELECT COUNT(*) as count FROM purchase_items WHERE item_id=?', (id,))
    purchases_count = c.fetchone()['count']
    
    # حذف الصنف حتى لو كان مستخدم في فواتير أو مشتريات
    c.execute('DELETE FROM items WHERE id=?', (id,))
    db.commit()
    
    if sales_count > 0 or purchases_count > 0:
        flash(f'✅ تم حذف الصنف "{item["name"]}" بنجاح. (كان مستخدم في {sales_count + purchases_count} عملية بيع أو شراء)')
    else:
        flash(f'✅ تم حذف الصنف "{item["name"]}" بنجاح.')
    return redirect(url_for('items'))

# --------- Customers & Suppliers (simple) ---------
@app.route('/customers', methods=['GET','POST'])
@login_required
@store_required
def customers():
    db = get_db(); c = db.cursor()
    if request.method=='POST':
        name = request.form.get('name'); phone = request.form.get('phone')
        c.execute('INSERT INTO customers (name,phone) VALUES (?,?)', (name,phone)); db.commit(); flash('✅ تم إضافة الزبون.'); return redirect(url_for('customers'))
    c.execute('SELECT * FROM customers ORDER BY name'); rows = c.fetchall()
    page = '''
    <section class="wrapper style1 fade-up"><div class="inner">
    <h3>إدارة الزبائن</h3>
    <form method="post" class="form">
        <div class="fields">
            <div class="field half"><input type="text" name="name" class="form-control" placeholder="اسم الزبون" required></div>
            <div class="field half"><input type="text" name="phone" class="form-control" placeholder="رقم الهاتف"></div>
        </div>
        <ul class="actions"><li><button class="button primary">أضف زبون جديد</button></li></ul>
    </form>
    <hr/>
    <div class="table-wrapper">
    <table class="alt">
        <thead><tr><th>الاسم</th><th>الهاتف</th><th>إجراء</th></tr></thead>
        <tbody>
        {% for r in rows %}
        <tr>
            <td>{{r['name']}}</td>
            <td>{{r['phone']}}</td>
            <td><a class="button small" href="#">تعديل</a></td>
        </tr>
        {% endfor %}
        </tbody>
    </table>
    </div>
    </div></section>
    '''
    return render_template_string(base_html.replace('%%CONTENT%%', page), rows=rows)

@app.route('/suppliers', methods=['GET','POST'])
@login_required
@store_required
def suppliers():
    db = get_db(); c = db.cursor()
    if request.method=='POST':
        name = request.form.get('name'); phone = request.form.get('phone')
        c.execute('INSERT INTO suppliers (name,phone) VALUES (?,?)', (name,phone)); db.commit(); flash('✅ تم إضافة المورد.'); return redirect(url_for('suppliers'))
    c.execute('SELECT * FROM suppliers ORDER BY name'); rows = c.fetchall()
    page = '''
    <section class="wrapper style1 fade-up"><div class="inner">
    <h3>إدارة الموردين</h3>
    <form method="post" class="form">
        <div class="fields">
            <div class="field half"><input type="text" name="name" class="form-control" placeholder="اسم المورد" required></div>
            <div class="field half"><input type="text" name="phone" class="form-control" placeholder="رقم الهاتف"></div>
        </div>
        <ul class="actions"><li><button class="button primary">أضف مورد جديد</button></li></ul>
    </form>
    <hr/>
    <div class="table-wrapper">
    <table class="alt">
        <thead><tr><th>الاسم</th><th>الهاتف</th><th>إجراء</th></tr></thead>
        <tbody>
        {% for r in rows %}
        <tr>
            <td>{{r['name']}}</td>
            <td>{{r['phone']}}</td>
            <td><a class="button small" href="#">تعديل</a></td>
        </tr>
        {% endfor %}
        </tbody>
    </table>
    </div>
    </div></section>
    '''
    return render_template_string(base_html.replace('%%CONTENT%%', page), rows=rows)

# --------- Purchases ---------
@app.route('/purchases', methods=['GET','POST'])
@login_required
@store_required
def purchases():
    db = get_db(); c = db.cursor()
    if request.method=='POST':
        supplier_id = request.form.get('supplier_id') or None
        item_ids = request.form.getlist('item_id')
        qtys = request.form.getlist('qty')
        prices = request.form.getlist('price')
        total = 0
        for i,q,p in zip(item_ids,qtys,prices): total += int(q)*float(p)
        date = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        c.execute('INSERT INTO purchases (supplier_id,date,total) VALUES (?,?,?)', (supplier_id,date,total))
        pid = c.lastrowid
        for i,q,p in zip(item_ids,qtys,prices):
            c.execute('INSERT INTO purchase_items (purchase_id,item_id,qty,price) VALUES (?,?,?,?)', (pid,int(i),int(q),float(p)))
            c.execute('UPDATE items SET qty = qty + ? WHERE id = ?', (int(q), int(i)))
        db.commit(); flash('✅ تم تسجيل سند التوريد.'); return redirect(url_for('purchases'))
    c.execute('SELECT * FROM items ORDER BY name'); items = c.fetchall(); c.execute('SELECT * FROM suppliers ORDER BY name'); suppliers = c.fetchall()
    
    # تم تعديل HTML صفحة التوريد لتكون أكثر تناسقاً
    page = '''
    <section class="wrapper style1 fade-up"><div class="inner">
    <h3>تسجيل سند توريد جديد</h3>
    <form method="post" class="form">
        <div class="fields">
            <div class="field">
                <label>المورد (اختياري)</label>
                <select name="supplier_id" class="form-select">
                    <option value="">-- اختر مورد --</option>
                    {% for s in suppliers %}<option value="{{s['id']}}">{{s['name']}}</option>{% endfor %}
                </select>
            </div>
        </div>
        
        <h5>اختر الأصناف المشتراة</h5>
        <div class="fields">
            <div class="field">
                <label for="purchase-search">🔍 البحث عن منتج:</label>
                <input type="text" id="purchase-search" class="form-control" placeholder="اكتب اسم المنتج أو الكود للبحث...">
            </div>
        </div>
        <div class="table-wrapper">
        <table class="alt">
            <thead>
                <tr>
                    <th>اختيار</th>
                    <th>اسم</th>
                    <th>سعر الشراء</th>
                    <th>الكمية</th>
                </tr>
            </thead>
            <tbody>
            {% for it in items %}
                <tr>
                    <td><input type='checkbox' id='chk-{{it["id"]}}' onchange='toggleRow(this,{{it["id"]}})'></td>
                    <td>{{it['name']}}</td>
                    <td><input name='price' value='{{it["buy_price"]}}' class='form-control price-{{it["id"]}}' disabled></td>
                    <td><input name='qty' value='1' class='form-control qty-{{it["id"]}}' disabled></td>
                    <input type='hidden' name='item_id' value='{{it["id"]}}'>
                </tr>
            {% endfor %}
            </tbody>
        </table>
        </div>
        <ul class="actions">
            <li><button class="button primary">💾 تسجيل سند التوريد</button></li>
        </ul>
    </form>
    </div></section>
    
    <script>
    // وظيفة البحث في المنتجات للمشتريات
    document.getElementById('purchase-search').addEventListener('input', function() {
        const searchTerm = this.value.toLowerCase();
        const rows = document.querySelectorAll('table tbody tr');
        
        rows.forEach(row => {
            const nameCell = row.querySelector('td:nth-child(2)');
            if (nameCell) {
                const name = nameCell.textContent.toLowerCase();
                if (name.includes(searchTerm)) {
                    row.style.display = 'table-row';
                } else {
                    row.style.display = 'none';
                }
            }
        });
    });
    
    // تفعيل/تعطيل حقول الإدخال عند اختيار الصنف
    function toggleRow(chk, id) {
        document.querySelector('.price-' + id).disabled = !chk.checked;
        document.querySelector('.qty-' + id).disabled = !chk.checked;
    }
    // إزالة الأصناف غير المختارة قبل الإرسال
    document.querySelector('form').addEventListener('submit', function(e) {
        document.querySelectorAll('input[type="checkbox"]').forEach(function(chk) {
            if (!chk.checked) {
                // إزالة الحقول المخفية للصنف غير المختار
                const id = chk.id.split('-')[1];
                document.querySelector('.price-' + id).remove();
                document.querySelector('.qty-' + id).remove();
                document.querySelectorAll('input[name="item_id"]').forEach(function(input) {
                    if (input.value == id) input.remove();
                });
            }
        });
    });
    </script>
    '''
    return render_template_string(base_html.replace('%%CONTENT%%', page), items=items, suppliers=suppliers)


# --------- Debts Management (NEW) ---------

@app.route('/debts', methods=['GET', 'POST'])
@login_required
@store_required
def debts():
    db = get_db(); c = db.cursor()

    # --- Handle POST for Adding New Debt ---
    if request.method == 'POST':
        if 'action' in request.form and request.form['action'] == 'add_debt':
            entity_type = request.form.get('entity_type')
            entity_id = request.form.get('entity_id')
            amount = float(request.form.get('amount') or 0)
            notes = request.form.get('notes')
            date = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

            if amount <= 0 or not entity_id or not entity_type:
                flash('❌ خطأ: يجب تحديد الطرف وقيمة الدين موجبة.')
                return redirect(url_for('debts'))

            try:
                c.execute('INSERT INTO debts (entity_type, entity_id, original_amount, date_created, notes) VALUES (?, ?, ?, ?, ?)',
                          (entity_type, entity_id, amount, date, notes))
                db.commit()
                flash(f'✅ تم تسجيل دين جديد بنجاح.')
            except Exception as e:
                flash(f"❌ خطأ في قاعدة البيانات: {e}")
            return redirect(url_for('debts'))

    # --- Handle GET (Listing Debts) ---
    
    # 1. Fetch Open Customer Debts (Receivables)
    c.execute('''
        SELECT d.id, d.original_amount, d.paid_amount, d.date_created, d.notes, c.name 
        FROM debts d 
        LEFT JOIN customers c ON c.id = d.entity_id 
        WHERE d.entity_type = 'customer' AND d.status = 'open' 
        ORDER BY d.date_created DESC
    ''')
    customer_debts = c.fetchall()

    # 2. Fetch Open Supplier Debts (Payables)
    c.execute('''
        SELECT d.id, d.original_amount, d.paid_amount, d.date_created, d.notes, s.name 
        FROM debts d 
        LEFT JOIN suppliers s ON s.id = d.entity_id 
        WHERE d.entity_type = 'supplier' AND d.status = 'open' 
        ORDER BY d.date_created DESC
    ''')
    supplier_debts = c.fetchall()
    
    # 3. Fetch entities for the "Add Debt" form
    c.execute('SELECT id, name FROM customers ORDER BY name')
    customers = c.fetchall()
    c.execute('SELECT id, name FROM suppliers ORDER BY name')
    suppliers = c.fetchall()

    page = '''
    <section class="wrapper style1 fade-up"><div class="inner">
        <h3>💰 إدارة الديون</h3>

        <h4 style="margin-top: 2em;">إضافة دين جديد (دين يدوي/سلفة)</h4>
        <form method="post" class="form">
            <input type="hidden" name="action" value="add_debt">
            <div class="fields">
                <div class="field quarter">
                    <label for="entity_type">نوع الطرف</label>
                    <select name="entity_type" id="entity_type" class="form-select" required>
                        <option value="">-- اختر --</option>
                        <option value="customer">زبون (دين لك)</option>
                        <option value="supplier">مورد (دين عليك)</option>
                    </select>
                </div>
                <div class="field quarter">
                    <label for="entity_id">الطرف</label>
                    <select name="entity_id" id="entity_id" class="form-select" required>
                        <option value="">-- اختر الطرف --</option>
                    </select>
                </div>
                <div class="field quarter">
                    <label for="amount">قيمة الدين</label>
                    <input type="number" step="0.01" name="amount" id="amount" class="form-control" placeholder="المبلغ" required min="0.01">
                </div>
                <div class="field quarter">
                    <label for="notes">ملاحظات (اختياري)</label>
                    <input type="text" name="notes" id="notes" class="form-control" placeholder="مثل: فاتورة رقم 123">
                </div>
            </div>
            <ul class="actions">
                <li><button type="submit" class="button primary">➕ تسجيل الدين</button></li>
            </ul>
        </form>
        <hr />
        
        <h4>ديون لنا (مستحقات من الزبائن)</h4>
        <div class="table-wrapper">
            <table class="alt">
                <thead><tr><th>#</th><th>الزبون</th><th>الأصل</th><th>المدفوع</th><th>المتبقي</th><th>تاريخ</th><th>ملاحظات</th><th>إجراء</th></tr></thead>
                <tbody>
                {% for d in customer_debts %}
                    {% set remaining = d['original_amount'] - d['paid_amount'] %}
                    {% if remaining > 0 %}
                    <tr>
                        <td>{{ d['id'] }}</td>
                        <td>{{ d['name'] }}</td>
                        <td>{{ '%.2f' % d['original_amount'] }}</td>
                        <td>{{ '%.2f' % d['paid_amount'] }}</td>
                        <td><strong>{{ '%.2f' % remaining }}</strong></td>
                        <td>{{ d['date_created'].split(' ')[0] }}</td>
                        <td>{{ d['notes'] or '' }}</td>
                        <td>
                            <button class="button small primary" onclick="document.getElementById('pay-debt-{{d['id']}}').style.display='table-row'">تسديد</button>
                        </td>
                    </tr>
                    <tr style="display:none;" id="pay-debt-{{d['id']}}">
                        <td colspan="8">
                            <form method="post" action="{{ url_for('pay_debt', id=d['id']) }}" style="margin: 0;">
                                <div class="fields" style="padding-top: 0.5em;">
                                    <div class="field quarter">
                                        <input type="number" step="0.01" name="payment_amount" class="form-control" placeholder="قيمة التسديد (بحد أقصى {{ '%.2f' % remaining }})" required max="{{ '%.2f' % remaining }}" min="0.01">
                                    </div>
                                    <div class="field quarter">
                                        <button type="submit" class="button small primary">إتمام التسديد</button>
                                    </div>
                                    <div class="field quarter">
                                        <button type="button" class="button small secondary" onclick="document.getElementById('pay-debt-{{d['id']}}').style.display='none'">إلغاء</button>
                                    </div>
                                </div>
                            </form>
                        </td>
                    </tr>
                    {% endif %}
                {% endfor %}
                {% if not customer_debts %}<tr><td colspan="8">لا توجد ديون مستحقة حالياً.</td></tr>{% endif %}
                </tbody>
            </table>
        </div>
        
        <h4 style="margin-top: 3em;">ديون علينا (مستحقات للموردين)</h4>
        <div class="table-wrapper">
            <table class="alt">
                <thead><tr><th>#</th><th>المورد</th><th>الأصل</th><th>المدفوع</th><th>المتبقي</th><th>تاريخ</th><th>ملاحظات</th><th>إجراء</th></tr></thead>
                <tbody>
                {% for d in supplier_debts %}
                    {% set remaining = d['original_amount'] - d['paid_amount'] %}
                    {% if remaining > 0 %}
                    <tr>
                        <td>{{ d['id'] }}</td>
                        <td>{{ d['name'] }}</td>
                        <td>{{ '%.2f' % d['original_amount'] }}</td>
                        <td>{{ '%.2f' % d['paid_amount'] }}</td>
                        <td><strong>{{ '%.2f' % remaining }}</strong></td>
                        <td>{{ d['date_created'].split(' ')[0] }}</td>
                        <td>{{ d['notes'] or '' }}</td>
                        <td>
                            <button class="button small primary" onclick="document.getElementById('pay-supplier-debt-{{d['id']}}').style.display='table-row'">تسديد</button>
                        </td>
                    </tr>
                    <tr style="display:none;" id="pay-supplier-debt-{{d['id']}}">
                        <td colspan="8">
                            <form method="post" action="{{ url_for('pay_debt', id=d['id']) }}" style="margin: 0;">
                                <div class="fields" style="padding-top: 0.5em;">
                                    <div class="field quarter">
                                        <input type="number" step="0.01" name="payment_amount" class="form-control" placeholder="قيمة التسديد (بحد أقصى {{ '%.2f' % remaining }})" required max="{{ '%.2f' % remaining }}" min="0.01">
                                    </div>
                                    <div class="field quarter">
                                        <button type="submit" class="button small primary">إتمام التسديد</button>
                                    </div>
                                    <div class="field quarter">
                                        <button type="button" class="button small secondary" onclick="document.getElementById('pay-supplier-debt-{{d['id']}}').style.display='none'">إلغاء</button>
                                    </div>
                                </div>
                            </form>
                        </td>
                    </tr>
                    {% endif %}
                {% endfor %}
                {% if not supplier_debts %}<tr><td colspan="8">لا توجد ديون مستحقة حالياً.</td></tr>{% endif %}
                </tbody>
            </table>
        </div>

    </div></section>
    
    <script>
    const customersData = [
        {% for c in customers %}{id: {{ c['id'] }}, name: '{{ c['name'] }}'},{% endfor %}
    ];
    const suppliersData = [
        {% for s in suppliers %}{id: {{ s['id'] }}, name: '{{ s['name'] }}'},{% endfor %}
    ];
    
    // Function to populate the entity dropdown based on selected type
    document.getElementById('entity_type').addEventListener('change', function() {
        const entityType = this.value;
        const entitySelect = document.getElementById('entity_id');
        entitySelect.innerHTML = '<option value="">-- اختر الطرف --</option>'; // Reset

        let data = [];
        if (entityType === 'customer') {
            data = customersData;
        } else if (entityType === 'supplier') {
            data = suppliersData;
        }

        data.forEach(entity => {
            const option = document.createElement('option');
            option.value = entity.id;
            option.textContent = entity.name;
            entitySelect.appendChild(option);
        });
    });
    </script>
    '''
    return render_template_string(base_html.replace('%%CONTENT%%', page), 
                                  customer_debts=customer_debts, 
                                  supplier_debts=supplier_debts,
                                  customers=customers,
                                  suppliers=suppliers)

@app.route('/debts/pay/<int:id>', methods=['POST'])
@login_required
@store_required
def pay_debt(id):
    db = get_db(); c = db.cursor()
    payment_amount = float(request.form.get('payment_amount') or 0)
    
    if payment_amount <= 0:
        flash('❌ خطأ: يجب أن تكون قيمة التسديد موجبة.')
        return redirect(url_for('debts'))

    c.execute('SELECT original_amount, paid_amount FROM debts WHERE id = ?', (id,))
    debt = c.fetchone()

    if not debt:
        flash('❌ خطأ: الدين غير موجود.')
        return redirect(url_for('debts'))

    remaining = debt['original_amount'] - debt['paid_amount']
    
    if payment_amount > remaining:
        flash(f'❌ خطأ: لا يمكن تسديد مبلغ أكبر من المتبقي. المبلغ المتبقي هو: {remaining:.2f} د.ج')
        return redirect(url_for('debts'))

    new_paid = debt['paid_amount'] + payment_amount
    status = 'paid' if new_paid >= debt['original_amount'] else 'open'

    c.execute('UPDATE debts SET paid_amount = ?, status = ? WHERE id = ?', (new_paid, status, id))
    db.commit()

    if status == 'paid':
        flash(f'✅ تم تسديد الدين رقم {id} بالكامل ({payment_amount:.2f} د.ج).')
    else:
        flash(f'✅ تم تسجيل تسديد جزئي للدين رقم {id} بقيمة {payment_amount:.2f} د.ج. المتبقي: {(debt['original_amount'] - new_paid):.2f} د.ج.')
        
    return redirect(url_for('debts'))

# --------- Stats ---------
@app.route('/stats')
@login_required
@store_required
def stats():
    db = get_store_db(); c = db.cursor()
    c.execute("SELECT COALESCE(SUM(total),0) as ssum FROM sales"); ssum = c.fetchone()['ssum']
    c.execute("SELECT COALESCE(SUM(total),0) as psum FROM purchases"); psum = c.fetchone()['psum']
    c.execute('SELECT COALESCE(SUM(qty*buy_price),0) as stock_value FROM items'); stock_value = c.fetchone()['stock_value']
    
    # Calculate Net Debts (Receivables - Payables)
    c.execute("SELECT COALESCE(SUM(original_amount - paid_amount), 0) FROM debts WHERE entity_type = 'customer' AND status = 'open'")
    receivables = c.fetchone()[0]
    c.execute("SELECT COALESCE(SUM(original_amount - paid_amount), 0) FROM debts WHERE entity_type = 'supplier' AND status = 'open'")
    payables = c.fetchone()[0]
    net_debts = receivables - payables # Positive means money is owed to you

    page = f'''
    <section class="wrapper style3 fade-up"><div class="inner">
    <h3>الإحصائيات والتقارير</h3>
    <ul class="actions">
        <li class="button primary fit">مجموع المبيعات: {ssum} د.ج</li>
        <li class="button secondary fit">مجموع المشتريات: {psum} د.ج</li>
        <li class="button fit">الربح التقريبي (مبيعات - مشتريات): {ssum - psum} د.ج</li>
        <li class="button fit">قيمة المخزون (سعر الشراء * الكمية): {stock_value} د.ج</li>
        <li class="button fit" style="background-color: #6c757d;">صافي الديون (لك - عليك): {net_debts:.2f} د.ج</li>
    </ul>
    <p style="text-align: center; margin-top: 1em;">
        (ديون لك: {receivables:.2f} د.ج) - (ديون عليك: {payables:.2f} د.ج)
    </p>
    </div></section>'''
    return render_template_string(base_html.replace('%%CONTENT%%', page))

# --------- Admin Routes ---------
@app.route('/admin/users')
@admin_required
def admin_users():
    """صفحة إدارة المستخدمين للمدير"""
    db = get_main_db()
    c = db.cursor()
    
    # الحصول على جميع المستخدمين
    c.execute('''SELECT u.*, COUNT(s.id) as stores_count 
                 FROM users u 
                 LEFT JOIN stores s ON u.id = s.owner_id 
                 GROUP BY u.id 
                 ORDER BY u.created_at DESC''')
    users = c.fetchall()
    
    page = f'''
    <section class="wrapper style1 fade-up">
        <div class="inner">
            <h2>👑 إدارة المستخدمين</h2>
            <p>إدارة جميع الحسابات المسجلة في النظام</p>
            
            <div class="table-wrapper">
                <table class="alt">
                    <thead>
                        <tr>
                            <th>المعرف</th>
                            <th>اسم المستخدم</th>
                            <th>الاسم الكامل</th>
                            <th>البريد الإلكتروني</th>
                            <th>الهاتف</th>
                            <th>عدد المحلات</th>
                            <th>تاريخ التسجيل</th>
                            <th>آخر دخول</th>
                            <th>الإجراءات</th>
                        </tr>
                    </thead>
                    <tbody>
    '''
    
    for user in users:
        stores_count = user['stores_count'] if user['stores_count'] else 0
        last_login = user['last_login'] if user['last_login'] else 'لم يسجل دخول'
        created_at = user['created_at'][:10] if user['created_at'] else 'غير محدد'
        
        page += f'''
                        <tr>
                            <td>{user['id']}</td>
                            <td>
                                {user['username']}
                                {'<span style="color: #ffd700;">👑</span>' if user['username'] == 'admin' else ''}
                            </td>
                            <td>{user['full_name'] or 'غير محدد'}</td>
                            <td>{user['email'] or 'غير محدد'}</td>
                            <td>{user['phone'] or 'غير محدد'}</td>
                            <td>{stores_count}</td>
                            <td>{created_at}</td>
                            <td>{last_login}</td>
                            <td>
                                <a href="/admin/users/edit/{user['id']}" class="button small primary">✏️ تعديل</a>
                                {'<a href="/admin/users/delete/' + str(user['id']) + '" class="button small" style="background-color: #ff6b6b;" onclick="return confirm(\'هل أنت متأكد من حذف هذا المستخدم؟\')">🗑️ حذف</a>' if user['username'] != 'admin' else '<span style="color: #999;">لا يمكن حذف المدير</span>'}
                            </td>
                        </tr>
        '''
    
    page += '''
                    </tbody>
                </table>
            </div>
            
            <ul class="actions">
                <li><a href="/admin/users/add" class="button primary">➕ إضافة مستخدم جديد</a></li>
                <li><a href="/" class="button secondary">العودة للرئيسية</a></li>
            </ul>
        </div>
    </section>
    '''
    
    return render_template_string(base_html.replace('%%CONTENT%%', page))

@app.route('/admin/users/add', methods=['GET', 'POST'])
@admin_required
def admin_add_user():
    """إضافة مستخدم جديد من قبل المدير"""
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        full_name = request.form.get('full_name')
        email = request.form.get('email')
        phone = request.form.get('phone')
        
        if not username or not password:
            flash('❌ اسم المستخدم وكلمة المرور مطلوبان.')
            return redirect(url_for('admin_add_user'))
        
        db = get_main_db()
        c = db.cursor()
        
        # التحقق من عدم وجود اسم مستخدم مكرر
        c.execute('SELECT COUNT(*) FROM users WHERE username = ?', (username,))
        if c.fetchone()[0] > 0:
            flash('❌ اسم المستخدم موجود مسبقاً.')
            return redirect(url_for('admin_add_user'))
        
        try:
            # تشفير كلمة المرور
            password_hash = generate_password_hash(password)
            current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            
            # إضافة المستخدم
            c.execute('''INSERT INTO users (username, password_hash, full_name, email, phone, created_at) 
                        VALUES (?, ?, ?, ?, ?, ?)''', 
                     (username, password_hash, full_name, email, phone, current_time))
            
            db.commit()
            flash('✅ تم إضافة المستخدم بنجاح.')
            return redirect(url_for('admin_users'))
            
        except Exception as e:
            flash(f'❌ خطأ في إضافة المستخدم: {str(e)}')
            return redirect(url_for('admin_add_user'))
    
    page = '''
    <section class="wrapper style1 fade-up">
        <div class="inner">
            <h2>➕ إضافة مستخدم جديد</h2>
            <p>إضافة حساب جديد للنظام</p>
            
            <form method="post" class="form">
                <div class="fields">
                    <div class="field half">
                        <label for="username">اسم المستخدم *</label>
                        <input type="text" name="username" id="username" class="form-control" required>
                    </div>
                    <div class="field half">
                        <label for="password">كلمة المرور *</label>
                        <input type="password" name="password" id="password" class="form-control" required>
                    </div>
                    <div class="field">
                        <label for="full_name">الاسم الكامل</label>
                        <input type="text" name="full_name" id="full_name" class="form-control">
                    </div>
                    <div class="field half">
                        <label for="email">البريد الإلكتروني</label>
                        <input type="email" name="email" id="email" class="form-control">
                    </div>
                    <div class="field half">
                        <label for="phone">رقم الهاتف</label>
                        <input type="text" name="phone" id="phone" class="form-control">
                    </div>
                </div>
                <ul class="actions">
                    <li><button type="submit" class="button primary">💾 إضافة المستخدم</button></li>
                    <li><a href="/admin/users" class="button secondary">العودة</a></li>
                </ul>
            </form>
        </div>
    </section>
    '''
    
    return render_template_string(base_html.replace('%%CONTENT%%', page))

@app.route('/admin/users/edit/<int:user_id>', methods=['GET', 'POST'])
@admin_required
def admin_edit_user(user_id):
    """تعديل بيانات مستخدم من قبل المدير"""
    db = get_main_db()
    c = db.cursor()
    
    # الحصول على بيانات المستخدم
    c.execute('SELECT * FROM users WHERE id = ?', (user_id,))
    user = c.fetchone()
    
    if not user:
        flash('❌ المستخدم غير موجود.')
        return redirect(url_for('admin_users'))
    
    if request.method == 'POST':
        username = request.form.get('username')
        full_name = request.form.get('full_name')
        email = request.form.get('email')
        phone = request.form.get('phone')
        new_password = request.form.get('new_password')
        
        if not username:
            flash('❌ اسم المستخدم مطلوب.')
            return redirect(url_for('admin_edit_user', user_id=user_id))
        
        # التحقق من عدم وجود اسم مستخدم مكرر (عدا المستخدم الحالي)
        c.execute('SELECT COUNT(*) FROM users WHERE username = ? AND id != ?', (username, user_id))
        if c.fetchone()[0] > 0:
            flash('❌ اسم المستخدم موجود مسبقاً.')
            return redirect(url_for('admin_edit_user', user_id=user_id))
        
        try:
            # تحديث البيانات
            if new_password:
                password_hash = generate_password_hash(new_password)
                c.execute('''UPDATE users SET username = ?, password_hash = ?, full_name = ?, 
                            email = ?, phone = ? WHERE id = ?''', 
                         (username, password_hash, full_name, email, phone, user_id))
            else:
                c.execute('''UPDATE users SET username = ?, full_name = ?, email = ?, phone = ? 
                            WHERE id = ?''', 
                         (username, full_name, email, phone, user_id))
            
            db.commit()
            flash('✅ تم تحديث بيانات المستخدم بنجاح.')
            return redirect(url_for('admin_users'))
            
        except Exception as e:
            flash(f'❌ خطأ في تحديث المستخدم: {str(e)}')
            return redirect(url_for('admin_edit_user', user_id=user_id))
    
    page = f'''
    <section class="wrapper style1 fade-up">
        <div class="inner">
            <h2>✏️ تعديل بيانات المستخدم</h2>
            <p>تعديل بيانات: <strong>{user['username']}</strong></p>
            
            <form method="post" class="form">
                <div class="fields">
                    <div class="field half">
                        <label for="username">اسم المستخدم *</label>
                        <input type="text" name="username" id="username" class="form-control" 
                               value="{user['username']}" required>
                    </div>
                    <div class="field half">
                        <label for="new_password">كلمة مرور جديدة (اتركها فارغة للاحتفاظ بالحالية)</label>
                        <input type="password" name="new_password" id="new_password" class="form-control">
                    </div>
                    <div class="field">
                        <label for="full_name">الاسم الكامل</label>
                        <input type="text" name="full_name" id="full_name" class="form-control" 
                               value="{user['full_name'] or ''}">
                    </div>
                    <div class="field half">
                        <label for="email">البريد الإلكتروني</label>
                        <input type="email" name="email" id="email" class="form-control" 
                               value="{user['email'] or ''}">
                    </div>
                    <div class="field half">
                        <label for="phone">رقم الهاتف</label>
                        <input type="text" name="phone" id="phone" class="form-control" 
                               value="{user['phone'] or ''}">
                    </div>
                </div>
                <ul class="actions">
                    <li><button type="submit" class="button primary">💾 حفظ التغييرات</button></li>
                    <li><a href="/admin/users" class="button secondary">العودة</a></li>
                </ul>
            </form>
        </div>
    </section>
    '''
    
    return render_template_string(base_html.replace('%%CONTENT%%', page))

@app.route('/admin/users/delete/<int:user_id>')
@admin_required
def admin_delete_user(user_id):
    """حذف مستخدم من قبل المدير"""
    db = get_main_db()
    c = db.cursor()
    
    # الحصول على بيانات المستخدم
    c.execute('SELECT username FROM users WHERE id = ?', (user_id,))
    user = c.fetchone()
    
    if not user:
        flash('❌ المستخدم غير موجود.')
        return redirect(url_for('admin_users'))
    
    if user['username'] == 'admin':
        flash('❌ لا يمكن حذف حساب المدير.')
        return redirect(url_for('admin_users'))
    
    try:
        # حذف المستخدم وجميع بياناته
        c.execute('DELETE FROM users WHERE id = ?', (user_id,))
        c.execute('DELETE FROM stores WHERE owner_id = ?', (user_id,))
        c.execute('DELETE FROM store_permissions WHERE user_id = ?', (user_id,))
        
        db.commit()
        flash('✅ تم حذف المستخدم بنجاح.')
        
    except Exception as e:
        flash(f'❌ خطأ في حذف المستخدم: {str(e)}')
    
    return redirect(url_for('admin_users'))

if __name__ == '__main__':
    print('Lekhlef Library - Starting Application')
    print('=' * 50)
    
    # فتح المتصفح تلقائياً
    import threading
    import webbrowser
    import time
    
    def open_browser():
        time.sleep(2)
        webbrowser.open('http://127.0.0.1:5000')
    
    browser_thread = threading.Thread(target=open_browser)
    browser_thread.daemon = True
    browser_thread.start()
    
    print('Starting application...')
    print('Browser will open automatically in 2 seconds')
    print('To stop: Close command window or press Ctrl+C')
    print('=' * 50)
    
    # إعدادات للنشر على الإنترنت
    port = int(os.environ.get('PORT', 5000))
    debug = os.environ.get('FLASK_ENV') != 'production'
    
    app.run(host='0.0.0.0', port=port, debug=debug, use_reloader=False)
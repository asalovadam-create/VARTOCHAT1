import random
import time
import os
import re
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from flask_socketio import SocketIO, emit, join_room
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.config['SECRET_KEY'] = 'varto-chat-2025-super-secret-key-very-long'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///data.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'
socketio = SocketIO(app, async_mode='threading', cors_allowed_origins="*")

UPLOAD_FOLDER = 'static/uploads/avatars'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

pending_codes = {}
user_sockets = {}

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    phone = db.Column(db.String(20), unique=True, nullable=False)
    username = db.Column(db.String(80), unique=True, nullable=False)
    name = db.Column(db.String(120), nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    avatar = db.Column(db.String(300), default='/static/default_avatar.png')
    last_seen = db.Column(db.DateTime, default=datetime.utcnow)
    is_online = db.Column(db.Boolean, default=False)
    show_last_seen = db.Column(db.Boolean, default=True)
    show_online = db.Column(db.Boolean, default=True)

class Chat(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    room_key = db.Column(db.String(100), unique=True, nullable=False)
    is_archived = db.Column(db.Boolean, default=False)

class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    chat_id = db.Column(db.Integer, db.ForeignKey('chat.id'), nullable=False)
    sender_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    content = db.Column(db.Text)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    is_read = db.Column(db.Boolean, default=False)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# ====================== КОНТЕКСТ + ДЕМО ======================
with app.app_context():
    db.create_all()

    demo = [
        ("+79161234567", "Анна Смирнова", "anna", "123456"),
        ("+79876543210", "Максим Иванов", "max", "123456"),
        ("+10000000000", "Grok by xAI", "grok", "grok"),
    ]
    for phone, name, username, pwd in demo:
        if not User.query.filter_by(phone=phone).first():
            u = User(phone=phone, username=username, name=name, password_hash=generate_password_hash(pwd))
            db.session.add(u)
            db.session.commit()

def get_or_create_chat(u1, u2):
    if u1 > u2: u1, u2 = u2, u1
    key = f"chat_{u1}_{u2}"
    chat = Chat.query.filter_by(room_key=key).first()
    if not chat:
        chat = Chat(room_key=key)
        db.session.add(chat)
        db.session.commit()
    return chat

def is_valid_username(username):
    username = username.strip()
    if len(username) < 4:
        return False, "Логин должен быть минимум 4 символа"
    if not re.match(r'^[a-zA-Z][a-zA-Z0-9]*$', username):
        return False, "Логин может содержать только английские буквы и цифры и не может начинаться с цифры"
    return True, ""

# ====================== РЕГИСТРАЦИЯ ======================
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        phone = request.form.get('phone', '').strip()
        password = request.form.get('password', '').strip()

        print("\n" + "="*60)
        print(f"🔐 ПОПЫТКА ВХОДА")
        print(f"   Телефон: '{phone}'")
        print(f"   Пароль : '{password}'")

        user = User.query.filter_by(phone=phone).first()

        if user:
            print(f"✅ Пользователь НАЙДЕН: {user.name} (id={user.id})")
            print(f"   Хэш в базе: {user.password_hash[:60]}...")  # первые 60 символов
            print(f"   Длина хэша: {len(user.password_hash)}")

            is_correct = check_password_hash(user.password_hash, password)
            print(f"   check_password_hash = {is_correct}")

            if is_correct:
                login_user(user)
                user.is_online = True
                user.last_seen = datetime.utcnow()
                db.session.commit()
                print(f"🎉 УСПЕШНЫЙ ВХОД! Редирект на главную...")
                return redirect(url_for('index'))
        else:
            print(f"❌ Пользователь с номером {phone} НЕ НАЙДЕН")

        print("❌ Вход НЕ удался — показываем ошибку")
        flash('Неверный номер или пароль', 'error')

    return render_template('login.html')

@app.route('/register_step1', methods=['POST'])
def register_step1():
    phone = request.form['phone'].strip()
    name = request.form['name'].strip()
    username_raw = request.form['username'].strip()
    username = username_raw.lstrip('@').lower()   # автоматически убираем @

    valid, error_msg = is_valid_username(username)
    if not valid:
        return jsonify({'success': False, 'error': error_msg})

    if User.query.filter_by(phone=phone).first():
        return jsonify({'success': False, 'error': 'Номер уже зарегистрирован'})
    if User.query.filter_by(username=username).first():
        return jsonify({'success': False, 'error': 'Username уже занят'})

    code = str(random.randint(100000, 999999))
    pending_codes[phone] = {'code': code, 'name': name, 'username': username}
    print(f"\n📲 VARTOCHAT — КОД ДЛЯ {phone}: \033[92m{code}\033[0m\n")
    return jsonify({'success': True})

@app.route('/register_step2', methods=['POST'])
def register_step2():
    phone = request.form['phone']
    code = request.form['code']
    password = request.form['password']

    if phone not in pending_codes or pending_codes[phone]['code'] != code:
        return jsonify({'success': False, 'error': 'Неверный код'})

    data = pending_codes.pop(phone)
    user = User(phone=phone, username=data['username'], name=data['name'], password_hash=generate_password_hash(password))
    db.session.add(user)
    db.session.commit()

    login_user(user)
    user.is_online = True
    db.session.commit()
    return jsonify({'success': True})

# ====================== ОСНОВНЫЕ СТРАНИЦЫ ======================
@app.route('/')
@login_required
def index():
    return render_template('index.html')

@app.route('/profile')
@login_required
def profile():
    return render_template('profile.html', user=current_user)

@app.route('/update_profile', methods=['POST'])
@login_required
def update_profile():
    current_user.name = request.form['name'].strip()
    new_username = request.form.get('username', '').strip()
    if new_username and new_username != current_user.username:
        if User.query.filter_by(username=new_username).first():
            flash('Username занят', 'error')
        else:
            current_user.username = new_username
    current_user.show_last_seen = 'show_last_seen' in request.form
    current_user.show_online = 'show_online' in request.form
    if 'avatar' in request.files:
        f = request.files['avatar']
        if f.filename:
            filename = secure_filename(f.filename)
            path = os.path.join(UPLOAD_FOLDER, f"{current_user.id}_{int(time.time())}_{filename}")
            f.save(path)
            current_user.avatar = f'/static/uploads/avatars/{current_user.id}_{int(time.time())}_{filename}'
    db.session.commit()
    flash('Профиль обновлён!', 'success')
    return redirect(url_for('profile'))

@app.route('/logout')
def logout():
    if current_user.is_authenticated:
        current_user.is_online = False
        current_user.last_seen = datetime.utcnow()
        db.session.commit()
    logout_user()
    return redirect(url_for('login'))

# ====================== API ======================
@app.route('/api/chats')
@login_required
def get_chats():
    chats = []
    for c in Chat.query.filter_by(is_archived=False).all():
        if str(current_user.id) in c.room_key:
            parts = c.room_key.replace('chat_', '').split('_')
            partner_id = int(parts[0]) if int(parts[0]) != current_user.id else int(parts[1])
            partner = User.query.get(partner_id)
            if partner:
                # Последнее сообщение и время
                last_msg = Message.query.filter_by(chat_id=c.id).order_by(Message.timestamp.desc()).first()
                last_message = last_msg.content if last_msg else "Нет сообщений"
                if len(last_message) > 40:
                    last_message = last_message[:37] + "..."
                last_time = last_msg.timestamp.strftime('%H:%M') if last_msg else ''

                unread = Message.query.filter_by(chat_id=c.id, sender_id=partner_id, is_read=False).count()

                chats.append({
                    'id': partner.id,
                    'name': partner.name,
                    'username': partner.username,
                    'avatar': partner.avatar,
                    'online': partner.is_online if partner.show_online else False,
                    'unread': unread,
                    'last_message': last_message,
                    'last_time': last_time
                })
    # Сортируем по времени (самые новые сверху)
    chats.sort(key=lambda x: x.get('last_time', '00:00'), reverse=True)
    return jsonify(chats)


@app.route('/api/chat/<int:partner_id>')
@login_required
def get_chat(partner_id):
    chat = get_or_create_chat(current_user.id, partner_id)
    partner = User.query.get(partner_id)  # ← добавили

    msgs = Message.query.filter_by(chat_id=chat.id).order_by(Message.timestamp).all()

    return jsonify({
        'chat_id': chat.id,
        'room_key': chat.room_key,
        'partner_avatar': partner.avatar if partner else '/static/default_avatar.png',  # ← главное добавление
        'messages': [{
            'id': m.id,
            'sender_id': m.sender_id,
            'content': m.content,
            'timestamp': m.timestamp.isoformat(),
            'is_read': m.is_read
        } for m in msgs]
    })

@app.route('/add_friend', methods=['POST'])
@login_required
def add_friend():
    user_id = request.form.get('user_id')
    query = request.form.get('phone', '').strip()
    friend = None
    if user_id:
        friend = User.query.get(int(user_id))
    elif query:
        if query.startswith('@'):
            username = query[1:].strip()
            friend = User.query.filter_by(username=username).first()
        else:
            normalized = ''.join(c for c in query if c.isdigit())
            if len(normalized) == 11 and normalized.startswith('8'):
                normalized = '+7' + normalized[1:]
            elif len(normalized) == 10:
                normalized = '+7' + normalized
            friend = User.query.filter_by(phone=normalized).first()
    if not friend:
        return jsonify({'success': False, 'message': 'Пользователь не найден'})
    if friend.id == current_user.id:
        return jsonify({'success': False, 'message': 'Это вы'})
    get_or_create_chat(current_user.id, friend.id)
    return jsonify({'success': True, 'message': f'{friend.name} добавлен!', 'friend_id': friend.id})

# ====================== SOCKET.IO ======================
@socketio.on('connect')
def handle_connect():
    if current_user.is_authenticated:
        user_sockets[current_user.id] = request.sid
        current_user.is_online = True
        db.session.commit()
        emit('user_status', {'id': current_user.id, 'online': True}, broadcast=True)

@socketio.on('disconnect')
def handle_disconnect():
    if current_user.is_authenticated and current_user.id in user_sockets:
        del user_sockets[current_user.id]
        current_user.is_online = False
        current_user.last_seen = datetime.utcnow()
        db.session.commit()
        emit('user_status', {'id': current_user.id, 'online': False}, broadcast=True)

@socketio.on('join_chat')
def join_chat(data):
    room = data['room']
    join_room(room)
    print(f"Пользователь {current_user.id} присоединился к комнате {room}")

@socketio.on('send_message')
def send_message(data):
    partner_id = int(data['partner_id'])
    chat = get_or_create_chat(current_user.id, partner_id)
    msg = Message(chat_id=chat.id, sender_id=current_user.id, content=data['content'], is_read=False)
    db.session.add(msg)
    db.session.commit()
    payload = {
        'id': msg.id,
        'sender_id': current_user.id,
        'content': msg.content,
        'timestamp': msg.timestamp.isoformat(),
        'chat_id': chat.id,
        'is_read': msg.is_read
    }
    emit('new_message', payload, room=chat.room_key)
    print(f"Сообщение отправлено в комнату {chat.room_key}")

@app.route('/search_users')
@login_required
def search_users():
    q = request.args.get('q', '').strip().lstrip('@').lower()
    if len(q) < 2:
        return jsonify([])
    users = User.query.filter(
        (User.username.ilike(f'%{q}%')) | (User.name.ilike(f'%{q}%'))
    ).filter(User.id != current_user.id).limit(10).all()
    return jsonify([{
        'id': u.id,
        'name': u.name,
        'username': u.username,
        'avatar': u.avatar
    } for u in users])

@socketio.on('typing')
def handle_typing(data):
    partner_id = data.get('partner_id')
    if partner_id:
        emit('typing', {
            'chat_id': data.get('chat_id'),
            'user_id': current_user.id,
            'username': current_user.name
        }, room=f"chat_{min(current_user.id, partner_id)}_{max(current_user.id, partner_id)}")

@socketio.on('stop_typing')
def handle_stop_typing(data):
    partner_id = data.get('partner_id')
    if partner_id:
        emit('stop_typing', {}, room=f"chat_{min(current_user.id, partner_id)}_{max(current_user.id, partner_id)}")

if __name__ == '__main__':
    print("🚀 Сервер запущен на http://localhost:5000")
    print("Для доступа из интернета открой новый терминал и выполни:")
    print(" ssh -R 80:localhost:5000 a.pinggy.io")
    print("-" * 60)
    socketio.run(app, host='0.0.0.0', port=5000, debug=False, allow_unsafe_werkzeug=True)
from flask import Flask, render_template, request, redirect, url_for, session, flash
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timezone
from functools import wraps

app = Flask(__name__)
app.secret_key = 'campus-secret-key-change-in-production'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///campus.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# ─────────────────────────────────────────
# MODELS
# ─────────────────────────────────────────

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    role = db.Column(db.String(10), nullable=False)  # 'student' or 'faculty'
    # Faculty-only fields
    department = db.Column(db.String(100))
    building = db.Column(db.String(50))
    floor = db.Column(db.String(20))
    room = db.Column(db.String(20))
    availability = db.Column(db.String(20), default='available')  # available, busy, in_class

    def __init__(self, **kwargs):
        super().__init__(**kwargs)


class VisitRequest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    faculty_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    reason = db.Column(db.String(300), nullable=False)
    preferred_date = db.Column(db.String(20))
    preferred_time = db.Column(db.String(20))
    status = db.Column(db.String(20), default='pending')  # pending, accepted, rejected
    response_time = db.Column(db.String(50))
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    student = db.relationship('User', foreign_keys=[student_id])
    faculty = db.relationship('User', foreign_keys=[faculty_id])

    def __init__(self, **kwargs):
        super().__init__(**kwargs)


class Notification(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    message = db.Column(db.String(300), nullable=False)
    is_read = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    def __init__(self, **kwargs):
        super().__init__(**kwargs)



# ─────────────────────────────────────────
# DECORATORS
# ─────────────────────────────────────────

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please log in to continue.', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

def role_required(role):
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if session.get('role') != role:
                flash('Access denied.', 'danger')
                return redirect(url_for('login'))
            return f(*args, **kwargs)
        return decorated
    return decorator

# ─────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────

def get_unread_count(user_id):
    return db.session.query(Notification).filter_by(user_id=user_id, is_read=False).count()

app.jinja_env.globals['get_unread_count'] = get_unread_count

def add_notification(user_id, message):
    notif = Notification(user_id=user_id, message=message)
    db.session.add(notif)
    db.session.commit()

# ─────────────────────────────────────────
# AUTH ROUTES
# ─────────────────────────────────────────

@app.route('/')
def index():
    if 'user_id' in session:
        return redirect(url_for('student_dashboard') if session['role'] == 'student' else url_for('faculty_dashboard'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email'].strip()
        password = request.form['password']
        user = db.session.query(User).filter_by(email=email).first()
        if user and check_password_hash(user.password, password):
            session['user_id'] = user.id
            session['role'] = user.role
            session['name'] = user.name
            return redirect(url_for('student_dashboard') if user.role == 'student' else url_for('faculty_dashboard'))
        flash('Invalid email or password.', 'danger')
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name = request.form['name'].strip()
        email = request.form['email'].strip()
        password = request.form['password']
        role = request.form['role']

        if db.session.query(User).filter_by(email=email).first():
            flash('Email already registered.', 'danger')
            return render_template('register.html')

        user = User(
            name=name,
            email=email,
            password=generate_password_hash(password),
            role=role
        )

        if role == 'faculty':
            user.department = request.form.get('department', '')
            user.building = request.form.get('building', '')
            user.floor = request.form.get('floor', '')
            user.room = request.form.get('room', '')
            user.availability = 'available'

        db.session.add(user)
        db.session.commit()
        flash('Registration successful! Please log in.', 'success')
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# ─────────────────────────────────────────
# STUDENT ROUTES
# ─────────────────────────────────────────

@app.route('/student')
@login_required
@role_required('student')
def student_dashboard():
    faculty_list = db.session.query(User).filter_by(role='faculty').all()
    my_requests = db.session.query(VisitRequest).filter_by(student_id=session['user_id']).order_by(VisitRequest.created_at.desc()).all()
    unread = get_unread_count(session['user_id'])
    return render_template('student_dashboard.html', faculty_list=faculty_list, my_requests=my_requests, unread=unread)

@app.route('/student/request/<int:faculty_id>', methods=['GET', 'POST'])
@login_required
@role_required('student')
def send_request(faculty_id):
    faculty = db.get_or_404(User, faculty_id)
    if request.method == 'POST':
        vr = VisitRequest(
            student_id=session['user_id'],
            faculty_id=faculty_id,
            reason=request.form['reason'],
            preferred_date=request.form.get('preferred_date', ''),
            preferred_time=request.form.get('preferred_time', '')
        )
        db.session.add(vr)
        db.session.commit()
        add_notification(faculty_id, f"New visit request from {session['name']}: {vr.reason[:60]}")
        flash('Visit request sent!', 'success')
        return redirect(url_for('student_dashboard'))
    return render_template('send_request.html', faculty=faculty)

# ─────────────────────────────────────────
# FACULTY ROUTES
# ─────────────────────────────────────────

@app.route('/faculty')
@login_required
@role_required('faculty')
def faculty_dashboard():
    requests = db.session.query(VisitRequest).filter_by(faculty_id=session['user_id']).order_by(VisitRequest.created_at.desc()).all()
    me = db.session.get(User, session['user_id'])
    unread = get_unread_count(session['user_id'])
    return render_template('faculty_dashboard.html', requests=requests, me=me, unread=unread)

@app.route('/faculty/availability', methods=['POST'])
@login_required
@role_required('faculty')
def update_availability():
    status = request.form['availability']
    user = db.session.get(User, session['user_id'])
    user.availability = status
    db.session.commit()
    flash(f'Availability updated to "{status}".', 'success')
    return redirect(url_for('faculty_dashboard'))

@app.route('/faculty/respond/<int:request_id>/<action>')
@login_required
@role_required('faculty')
def respond_request(request_id, action):
    vr = db.get_or_404(VisitRequest, request_id)
    if vr.faculty_id != session['user_id']:
        flash('Unauthorized.', 'danger')
        return redirect(url_for('faculty_dashboard'))

    if action == 'accept':
        vr.status = 'accepted'
        vr.response_time = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')
        msg = f"Your visit request to {session['name']} has been ACCEPTED."
    else:
        vr.status = 'rejected'
        vr.response_time = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')
        msg = f"Your visit request to {session['name']} has been declined."

    db.session.commit()
    add_notification(vr.student_id, msg)
    # Mark faculty's own notification as read
    db.session.query(Notification).filter_by(user_id=session['user_id'], is_read=False).update({'is_read': True})
    db.session.commit()
    flash('Response sent.', 'success')
    return redirect(url_for('faculty_dashboard'))

# ─────────────────────────────────────────
# NOTIFICATIONS
# ─────────────────────────────────────────

@app.route('/notifications')
@login_required
def notifications():
    notifs = db.session.query(Notification).filter_by(user_id=session['user_id']).order_by(Notification.created_at.desc()).all()
    for n in notifs:
        n.is_read = True
    db.session.commit()
    return render_template('notifications.html', notifs=notifs)

# ─────────────────────────────────────────
# INIT DB & SEED
# ─────────────────────────────────────────

def seed_data():
    if db.session.query(User).count() == 0:
        faculty_data = [
            ("Dr. Priya Sharma", "priya@campus.edu", "Computer Science", "Tech Block", "2nd", "201"),
            ("Dr. Rajan Mehta", "rajan@campus.edu", "Mathematics", "Science Block", "1st", "105"),
            ("Dr. Anita Rao", "anita@campus.edu", "Physics", "Science Block", "3rd", "302"),
        ]
        for name, email, dept, building, floor, room in faculty_data:
            u = User(name=name, email=email, password=generate_password_hash("faculty123"),
                     role='faculty', department=dept, building=building, floor=floor, room=room, availability='available')
            db.session.add(u)

        student = User(name="Arjun Kumar", email="arjun@campus.edu",
                       password=generate_password_hash("student123"), role='student')
        db.session.add(student)
        db.session.commit()
        print("✅ Seed data created.")
        print("   Student login: arjun@campus.edu / student123")
        print("   Faculty login: priya@campus.edu / faculty123")

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        seed_data()
    app.run(debug=True)

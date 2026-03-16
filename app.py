from gevent import monkey
monkey.patch_all()

import os
import json
from dotenv import load_dotenv
from datetime import datetime, timedelta
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_bcrypt import Bcrypt
import google.generativeai as genai
from flask_socketio import SocketIO, emit, join_room
from geopy.distance import geodesic

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "blood_donation_security_key_2026")

# Database URL Fix
database_url = os.getenv("DATABASE_URL")
if database_url and database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)

local_db = 'mysql+pymysql://root:123456@localhost/blood_bank_db?charset=utf8mb4'
app.config['SQLALCHEMY_DATABASE_URI'] = database_url or local_db
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# SQLAlchemy Engine Options (Pool Management)
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    "pool_size": 10,
    "max_overflow": 20,
    "pool_recycle": 1800,
    "pool_pre_ping": True
}

db = SQLAlchemy(app)
bcrypt = Bcrypt(app)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='gevent')

# Gemini AI Configuration
API_KEY = os.getenv("GEMINI_API_KEY")
genai.configure(api_key=API_KEY)

# Database Setup Function
def init_db():
    with app.app_context():
        try:
            db.create_all()
            print("✓ Database tables created successfully!")
        except Exception as e:
            print(f"Error creating database: {e}")

init_db()

# Session Cleanup (To prevent connection leaks)
@app.teardown_appcontext
def shutdown_session(exception=None):
    db.session.remove()

class User(db.Model):
    __tablename__ = 'user'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False)
    blood_group = db.Column(db.String(5), nullable=False)
    city = db.Column(db.String(50), nullable=False)
    phone = db.Column(db.String(15), nullable=False)
    latitude = db.Column(db.Float, nullable=True)
    longitude = db.Column(db.Float, nullable=True)
    last_donation_date = db.Column(db.DateTime, nullable=True)
    is_available = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_admin = db.Column(db.Boolean, default=False)

class BloodRequest(db.Model):
    __tablename__ = 'blood_request'
    id = db.Column(db.Integer, primary_key=True)
    patient_name = db.Column(db.String(100), nullable=False)
    blood_group = db.Column(db.String(5), nullable=False)
    location = db.Column(db.String(100), nullable=False)
    phone = db.Column(db.String(15), nullable=False)
    notes = db.Column(db.Text, nullable=True)
    created_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_active = db.Column(db.Boolean, default=True)
    requester = db.relationship('User', foreign_keys=[created_by])

# -------------------- Routes --------------------

@app.route('/', methods=['GET', 'POST'])
def index():
    # Handling potential transaction/table errors
    try:
        three_months_ago = datetime.now() - timedelta(days=90)
        User.query.filter(User.last_donation_date <= three_months_ago).update({User.is_available: True})
        db.session.commit()
    except Exception as e:
        db.session.rollback()  # Rollback as per SQLAlchemy documentation
        print(f"Update error: {e}")

    donors = []
    if request.method == 'POST':
        bg = request.form.get('blood_group')
        city = request.form.get('city')

        query = User.query.filter_by(is_available=True)
        if bg:
            query = query.filter_by(blood_group=bg)
        if city:
            query = query.filter_by(city=city)
        donors = query.limit(12).all()
    else:
        donors = User.query.filter_by(is_available=True).limit(12).all()

    return render_template('index.html', donors=donors)


@app.route('/contact', methods=['POST'])
def contact():
    try:
        name = request.form.get('name')
        email = request.form.get('email')
        message = request.form.get('message')

        new_message = ContactMessage(name=name, email=email, message=message)
        db.session.add(new_message)
        db.session.commit()

        flash('Thank you for contacting us! We will get back to you soon.', 'success')
    except Exception as e:
        flash('Something went wrong. Please try again.', 'danger')

    return redirect(url_for('index'))


@app.route('/update_location', methods=['POST'])
def update_location():
    data = request.get_json()
    if 'user_id' in session:
        user = User.query.get(session['user_id'])
        if user:
            user.latitude = data.get('latitude')
            user.longitude = data.get('longitude')
            db.session.commit()
            return jsonify({"status": "success"})
    return jsonify({"status": "unauthorized"}), 401


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        existing_user = User.query.filter_by(email=request.form['email']).first()
        if existing_user:
            flash('Email already exists! Please use a different email.', 'danger')
            return redirect(url_for('register'))

        hashed_pw = bcrypt.generate_password_hash(request.form['password']).decode('utf-8')
        new_user = User(
            name=request.form['name'],
            email=request.form['email'],
            password=hashed_pw,
            blood_group=request.form['blood_group'],
            city=request.form['city'],
            phone=request.form['phone']
        )

        try:
            db.session.add(new_user)
            db.session.commit()
            flash('Account created successfully! Please login.', 'success')
            return redirect(url_for('login'))
        except Exception as e:
            flash('Registration failed. Please try again.', 'danger')

    return render_template('register.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = User.query.filter_by(email=request.form['email']).first()
        if user and bcrypt.check_password_hash(user.password, request.form['password']):
            session['user_id'] = user.id
            session['user_name'] = user.name
            session['is_admin'] = user.is_admin
            flash(f'Welcome back, {user.name}!', 'success')
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid email or password', 'danger')
    return render_template('login.html')


@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        flash('Please login to access dashboard', 'warning')
        return redirect(url_for('login'))

    user_info = User.query.get(session['user_id'])
    recent_requests = BloodRequest.query.filter_by(
        blood_group=user_info.blood_group,
        is_active=True
    ).order_by(BloodRequest.created_at.desc()).limit(5).all()

    return render_template('dashboard.html', user=user_info, requests=recent_requests)


@app.route('/ask_ai', methods=['POST'])
def ask_ai():
    data = request.get_json()
    user_message = data.get("message", "")

    try:
        model = genai.GenerativeModel('gemini-1.5-flash')
        prompt = f"""You are an AI assistant for Blood Aid, a blood donation platform. 
        Help the user with their query about blood donation. Be friendly and informative.
        User query: {user_message}"""

        response = model.generate_content(prompt)
        return jsonify({"answer": response.text})
    except Exception as e:
        return jsonify({"answer": "I'm having trouble connecting right now. Please try again later."})


@app.route('/request_blood', methods=['GET', 'POST'])
def request_blood():
    if request.method == 'POST':
        new_req = BloodRequest(
            patient_name=request.form.get('patient_name'),
            blood_group=request.form.get('blood_group'),
            location=request.form.get('location'),
            phone=request.form.get('phone'),
            notes=request.form.get('notes', ''),
            created_by=session.get('user_id')
        )

        try:
            db.session.add(new_req)
            db.session.commit()
            flash("Your blood request has been posted successfully!", "success")
        except Exception as e:
            flash("Failed to post request. Please try again.", "danger")

        return redirect(url_for('index'))

    return render_template('blood_request.html')


@app.route('/accept_request/<int:id>')
def accept_request(id):
    if 'user_id' not in session:
        flash('Please login to accept requests', 'warning')
        return redirect(url_for('login'))

    user = User.query.get(session['user_id'])
    request_item = BloodRequest.query.get_or_404(id)

    user.last_donation_date = datetime.now()
    user.is_available = False
    request_item.is_active = False

    db.session.commit()

    flash("Thank you for accepting the request! You are now in a 3-month rest period.", "success")
    return redirect(url_for('dashboard'))


# ==================== API ENDPOINTS ====================

@app.route('/accept_request_api/<int:id>', methods=['POST'])
def accept_request_api(id):
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Not logged in'}), 401

    user = User.query.get(session['user_id'])
    request_item = BloodRequest.query.get_or_404(id)

    if not user.is_available:
        return jsonify({'success': False, 'error': 'You are in rest period'}), 400

    if user.blood_group != request_item.blood_group:
        return jsonify({'success': False, 'error': 'Blood group mismatch'}), 400

    user.last_donation_date = datetime.now()
    user.is_available = False
    request_item.is_active = False

    try:
        db.session.commit()
        tracking_url = url_for('track_donor', request_id=id, donor_id=user.id, _external=True)

        return jsonify({
            'success': True,
            'message': 'Request accepted successfully',
            'tracking_url': tracking_url
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/track_donor/<int:request_id>/<int:donor_id>')
def track_donor(request_id, donor_id):
    blood_request = BloodRequest.query.get_or_404(request_id)
    donor = User.query.get_or_404(donor_id)

    return render_template('track_donor.html',
                           request=blood_request,
                           donor=donor)


@app.route('/admin')
def admin_panel():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user = User.query.get(session['user_id'])
    if not user.is_admin:
        flash('Access denied. Admin only.', 'danger')
        return redirect(url_for('dashboard'))

    all_donors = User.query.order_by(User.created_at.desc()).all()
    all_requests = BloodRequest.query.order_by(BloodRequest.created_at.desc()).all()
    messages = ContactMessage.query.order_by(ContactMessage.created_at.desc()).all()
    subscriptions = PushSubscription.query.all()

    return render_template('admin_view.html',
                           donors=all_donors,
                           requests=all_requests,
                           messages=messages,
                           subscriptions=subscriptions)


@app.route('/delete_request/<int:id>')
def delete_request(id):
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user = User.query.get(session['user_id'])
    if not user.is_admin:
        return redirect(url_for('dashboard'))

    req_to_delete = BloodRequest.query.get_or_404(id)
    db.session.delete(req_to_delete)
    db.session.commit()

    flash('Request deleted successfully', 'success')
    return redirect(url_for('admin_panel'))


@app.route('/delete_user/<int:id>')
def delete_user(id):
    if 'user_id' not in session:
        return redirect(url_for('login'))

    admin = User.query.get(session['user_id'])
    if not admin.is_admin:
        return redirect(url_for('dashboard'))

    user_to_delete = User.query.get_or_404(id)
    if user_to_delete.id != admin.id:
        db.session.delete(user_to_delete)
        db.session.commit()
        flash('User deleted successfully', 'success')

    return redirect(url_for('admin_panel'))


@app.route('/mark_message_read/<int:id>')
def mark_message_read(id):
    if 'user_id' not in session:
        return redirect(url_for('login'))

    message = ContactMessage.query.get_or_404(id)
    message.is_read = True
    db.session.commit()

    return redirect(url_for('admin_panel'))


@app.route('/save_push_subscription', methods=['POST'])
def save_push_subscription():
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401

    subscription_data = request.get_json()

    PushSubscription.query.filter_by(user_id=session['user_id']).delete()

    subscription = PushSubscription(
        user_id=session['user_id'],
        subscription_json=json.dumps(subscription_data)
    )
    db.session.add(subscription)
    db.session.commit()

    return jsonify({'status': 'success'})


@app.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out', 'info')
    return redirect(url_for('index'))


# ==================== SOCKET.IO EVENT HANDLERS ====================

active_donors = {}


@socketio.on('connect')
def handle_connect():
    print(f'Client connected: {request.sid}')


@socketio.on('disconnect')
def handle_disconnect():
    for user_id, data in list(active_donors.items()):
        if data['sid'] == request.sid:
            del active_donors[user_id]
            socketio.emit('donor_offline', {'user_id': user_id})
            break


@socketio.on('donor_location_update')
def handle_location_update(data):
    if 'user_id' in session:
        user_id = session['user_id']
        latitude = data['lat']
        longitude = data['lng']
        request_id = data.get('request_id')

        user = User.query.get(user_id)
        if user:
            user.latitude = latitude
            user.longitude = longitude
            db.session.commit()

            active_donors[user_id] = {
                'lat': latitude,
                'lng': longitude,
                'sid': request.sid,
                'available': user.is_available,
                'blood_group': user.blood_group
            }

            if request_id:
                room = f"request_{request_id}"

                blood_request = BloodRequest.query.get(request_id)
                if blood_request and blood_request.created_by:
                    recipient = User.query.get(blood_request.created_by)
                    if recipient and recipient.latitude and recipient.longitude:
                        donor_coords = (latitude, longitude)
                        recipient_coords = (recipient.latitude, recipient.longitude)
                        distance = geodesic(donor_coords, recipient_coords).kilometers
                        eta_minutes = round((distance / 30) * 60)

                        socketio.emit('eta_update', {
                            'distance': round(distance, 1),
                            'eta': eta_minutes,
                            'donor_lat': latitude,
                            'donor_lng': longitude
                        }, room=room)


@socketio.on('track_blood_request')
def track_request(data):
    request_id = data['request_id']
    donor_id = data['donor_id']
    recipient_lat = data.get('recipient_lat')
    recipient_lng = data.get('recipient_lng')

    room = f"request_{request_id}"
    join_room(room)
    print(f"Client joined room: {room}")

    if donor_id in active_donors:
        donor = active_donors[donor_id]

        if recipient_lat and recipient_lng:
            donor_coords = (donor['lat'], donor['lng'])
            recipient_coords = (recipient_lat, recipient_lng)
            distance = geodesic(donor_coords, recipient_coords).kilometers
            eta_minutes = round((distance / 30) * 60)

            emit('eta_update', {
                'distance': round(distance, 1),
                'eta': eta_minutes,
                'donor_lat': donor['lat'],
                'donor_lng': donor['lng']
            }, room=room)


@socketio.on('update_recipient_location')
def update_recipient_location(data):
    request_id = data['request_id']
    lat = data['lat']
    lng = data['lng']

    room = f"request_{request_id}"
    emit('recipient_location_updated', {'lat': lat, 'lng': lng}, room=room)


# ==================== DATABASE INIT ====================

def create_admin():
    with app.app_context():
        admin = User.query.filter_by(email='admin@bloodaid.com').first()
        if not admin:
            admin = User(
                name='Admin',
                email='admin@bloodaid.com',
                password=bcrypt.generate_password_hash('admin123').decode('utf-8'),
                blood_group='O+',
                city='Dhaka',
                phone='01700000000',
                is_admin=True
            )
            db.session.add(admin)
            db.session.commit()
            print('✓ Admin user created successfully!')
            print('   Email: admin@bloodaid.com')
            print('   Password: admin123')


@app.route('/debug')
def debug_info():
    info = {
        'session': dict(session),
        'templates_exist': {
            'login.html': os.path.exists('templates/login.html'),
            'register.html': os.path.exists('templates/register.html'),
            'blood_request.html': os.path.exists('templates/blood_request.html'),
            'dashboard.html': os.path.exists('templates/dashboard.html'),
        },
        'user_count': User.query.count(),
        'database_connected': True
    }
    return jsonify(info)

# ==================== MAIN ====================

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        create_admin()

    print("\n🚀 Blood Aid app is running with Gevent!")
    print("   Access at: http://localhost:5001")
    print("   Admin login: admin@bloodaid.com / admin123\n")

    socketio.run(app, host='0.0.0.0', port=5001)

from flask import Flask, render_template, request, jsonify, session, redirect, url_for, send_file
import json
import os
import qrcode
from datetime import datetime
import sqlite3
from werkzeug.utils import secure_filename
from werkzeug.security import check_password_hash, generate_password_hash
import uuid
from io import BytesIO
import base64

app = Flask(__name__)
app.secret_key = 'your-secret-key-change-this'  # Change this in production
app.config['UPLOAD_FOLDER'] = 'static/images'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size

# Admin credentials (in production, use a database)
ADMIN_CREDENTIALS = {
    'admin': 'password123'  # Change this in production
}

# Ensure upload directory exists
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)


def init_db():
    """Initialize SQLite database"""
    conn = sqlite3.connect('menu.db')
    cursor = conn.cursor()

    # Create menu items table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS menu_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            description TEXT,
            price REAL NOT NULL,
            category TEXT NOT NULL,
            image_path TEXT,
            availability INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            uploaded_by TEXT
        )
    ''')

    # Create orders table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id TEXT UNIQUE NOT NULL,
            customer_name TEXT NOT NULL,
            college_name TEXT NOT NULL,
            roll_number TEXT NOT NULL,
            phone_number TEXT NOT NULL,
            payment_method TEXT NOT NULL,
            items TEXT NOT NULL,
            subtotal REAL NOT NULL,
            gst REAL NOT NULL,
            packing_fee REAL DEFAULT 0,
            total REAL NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            bill_downloaded BOOLEAN DEFAULT FALSE
        )
    ''')

    # Create admin logs table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS admin_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            admin_user TEXT NOT NULL,
            action TEXT NOT NULL,
            details TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    conn.commit()
    conn.close()


def get_db_connection():
    """Get database connection"""
    conn = sqlite3.connect('menu.db')
    conn.row_factory = sqlite3.Row
    return conn


def log_admin_action(admin_user, action, details=""):
    """Log admin actions"""
    conn = get_db_connection()
    conn.execute(
        'INSERT INTO admin_logs (admin_user, action, details) VALUES (?, ?, ?)',
        (admin_user, action, details)
    )
    conn.commit()
    conn.close()


@app.route('/')
def index():
    """Landing page with QR code"""
    # Generate QR code for menu
    qr_data = request.url_root + 'menu'
    qr = qrcode.QRCode(version=1, box_size=10, border=5)
    qr.add_data(qr_data)
    qr.make(fit=True)

    img = qr.make_image(fill_color="black", back_color="white")
    buffer = BytesIO()
    img.save(buffer, format='PNG')
    buffer.seek(0)

    qr_code_data = base64.b64encode(buffer.getvalue()).decode()

    return render_template('index.html', qr_code=qr_code_data, menu_url=qr_data)


@app.route('/menu')
def menu():
    """Display menu page"""
    conn = get_db_connection()
    items = conn.execute(
        'SELECT * FROM menu_items WHERE availability > 0 ORDER BY category, name'
    ).fetchall()
    conn.close()

    # Group items by category
    menu_data = {}
    for item in items:
        category = item['category']
        if category not in menu_data:
            menu_data[category] = []
        menu_data[category].append({
            'id': item['id'],
            'name': item['name'],
            'description': item['description'],
            'price': item['price'],
            'image_path': item['image_path'],
            'availability': item['availability']
        })

    return render_template('menu.html', menu_data=menu_data)


@app.route('/admin_login', methods=['GET', 'POST'])
def admin_login():
    """Admin login page"""
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        if username in ADMIN_CREDENTIALS and ADMIN_CREDENTIALS[username] == password:
            session['admin_logged_in'] = True
            session['admin_user'] = username
            log_admin_action(username, "LOGIN", "Admin logged in successfully")
            return redirect(url_for('admin_dashboard'))
        else:
            return render_template('admin_login.html', error="Invalid credentials")

    return render_template('admin_login.html')


@app.route('/admin_dashboard')
def admin_dashboard():
    """Admin dashboard"""
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))

    conn = get_db_connection()

    # Get all menu items
    items = conn.execute(
        'SELECT * FROM menu_items ORDER BY created_at DESC'
    ).fetchall()

    # Get recent orders
    orders = conn.execute(
        'SELECT * FROM orders ORDER BY created_at DESC LIMIT 20'
    ).fetchall()

    # Get admin logs
    logs = conn.execute(
        'SELECT * FROM admin_logs ORDER BY created_at DESC LIMIT 20'
    ).fetchall()

    conn.close()

    return render_template('admin_dashboard.html', items=items, orders=orders, logs=logs)


@app.route('/admin_upload', methods=['GET', 'POST'])
def admin_upload():
    """Admin upload item page"""
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))

    if request.method == 'POST':
        try:
            name = request.form['name']
            description = request.form['description']
            price = float(request.form['price'])
            category = request.form['category']
            availability = int(request.form['availability'])

            # Handle file upload
            image_path = None
            if 'image' in request.files:
                file = request.files['image']
                if file.filename != '':
                    filename = secure_filename(file.filename)
                    # Add timestamp to avoid conflicts
                    filename = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{filename}"
                    file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                    file.save(file_path)
                    image_path = f"images/{filename}"

            # Save to database
            conn = get_db_connection()
            conn.execute(
                '''INSERT INTO menu_items 
                   (name, description, price, category, image_path, availability, uploaded_by)
                   VALUES (?, ?, ?, ?, ?, ?, ?)''',
                (name, description, price, category, image_path, availability, session['admin_user'])
            )
            conn.commit()
            conn.close()

            log_admin_action(
                session['admin_user'],
                "ITEM_ADDED",
                f"Added item: {name} in category: {category}"
            )

            return render_template('admin_upload.html', success="Item added successfully!")

        except Exception as e:
            return render_template('admin_upload.html', error=f"Error: {str(e)}")

    categories = ['Starters', 'Main Course', 'Dessert', 'Chats', 'Beverages', 'Others']
    return render_template('admin_upload.html', categories=categories)


@app.route('/update_availability', methods=['POST'])
def update_availability():
    """Update item availability"""
    if not session.get('admin_logged_in'):
        return jsonify({'error': 'Unauthorized'}), 401

    try:
        item_id = request.json['item_id']
        new_availability = int(request.json['availability'])

        conn = get_db_connection()
        conn.execute(
            'UPDATE menu_items SET availability = ? WHERE id = ?',
            (new_availability, item_id)
        )
        conn.commit()
        conn.close()

        log_admin_action(
            session['admin_user'],
            "AVAILABILITY_UPDATED",
            f"Updated availability for item ID {item_id} to {new_availability}"
        )

        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/place_order', methods=['POST'])
def place_order():
    """Place order"""
    try:
        data = request.json

        # Generate unique order ID
        order_id = f"ORD{datetime.now().strftime('%Y%m%d%H%M%S')}{str(uuid.uuid4())[:4].upper()}"

        # Calculate totals
        subtotal = sum(item['price'] * item['quantity'] for item in data['items'])
        gst = subtotal * 0.05
        packing_fee = 20 if subtotal < 500 else 0
        total = subtotal + gst + packing_fee

        # Update item availability
        conn = get_db_connection()
        for item in data['items']:
            conn.execute(
                'UPDATE menu_items SET availability = availability - ? WHERE id = ?',
                (item['quantity'], item['id'])
            )

        # Save order
        conn.execute(
            '''INSERT INTO orders 
               (order_id, customer_name, college_name, roll_number, phone_number, 
                payment_method, items, subtotal, gst, packing_fee, total)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            (order_id, data['customer_name'], data['college_name'], data['roll_number'],
             data['phone_number'], data['payment_method'], json.dumps(data['items']),
             subtotal, gst, packing_fee, total)
        )
        conn.commit()
        conn.close()

        return jsonify({
            'success': True,
            'order_id': order_id,
            'subtotal': subtotal,
            'gst': gst,
            'packing_fee': packing_fee,
            'total': total
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/bill/<order_id>')
def view_bill(order_id):
    """View bill"""
    conn = get_db_connection()
    order = conn.execute(
        'SELECT * FROM orders WHERE order_id = ?', (order_id,)
    ).fetchone()
    conn.close()

    if not order:
        return "Order not found", 404

    order_items = json.loads(order['items'])
    return render_template('bill.html', order=order, order_items=order_items)


@app.route('/download_bill/<order_id>')
def download_bill(order_id):
    """Mark bill as downloaded"""
    conn = get_db_connection()
    conn.execute(
        'UPDATE orders SET bill_downloaded = TRUE WHERE order_id = ?', (order_id,)
    )
    conn.commit()
    conn.close()

    return jsonify({'success': True})


@app.route('/admin_logout')
def admin_logout():
    """Admin logout"""
    if session.get('admin_logged_in'):
        log_admin_action(session['admin_user'], "LOGOUT", "Admin logged out")
        session.pop('admin_logged_in', None)
        session.pop('admin_user', None)
    return redirect(url_for('index'))


@app.route('/get_menu_data')
def get_menu_data():
    """API endpoint to get menu data"""
    conn = get_db_connection()
    items = conn.execute(
        'SELECT * FROM menu_items WHERE availability > 0 ORDER BY category, name'
    ).fetchall()
    conn.close()

    menu_data = {}
    for item in items:
        category = item['category']
        if category not in menu_data:
            menu_data[category] = []
        menu_data[category].append({
            'id': item['id'],
            'name': item['name'],
            'description': item['description'],
            'price': item['price'],
            'image_path': item['image_path'],
            'availability': item['availability']
        })

    return jsonify(menu_data)


if __name__ == '__main__':
    init_db()
    app.run(debug=True, host='0.0.0.0', port=5000)
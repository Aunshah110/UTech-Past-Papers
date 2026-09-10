import os
import re
import hashlib
import secrets
import psycopg2
import psycopg2.extras
from flask import Flask, render_template, request, jsonify, redirect, url_for, session, flash
from flask_cors import CORS
from dotenv import load_dotenv
from werkzeug.utils import secure_filename
import datetime
from functools import wraps
import urllib.parse

# Load environment variables
load_dotenv()

app = Flask(__name__)
CORS(app)

# Configuration
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-key-change-in-production')
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024
app.config['SESSION_COOKIE_SECURE'] = True
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['PERMANENT_SESSION_LIFETIME'] = datetime.timedelta(hours=24)

# ============= SINGLE DATABASE CONNECTION FUNCTION =============
def get_db_connection():
    """
    Universal database connection that works everywhere.
    Tries SSL first (for Vercel), falls back to no SSL (for local).
    """
    database_url = os.environ.get('DATABASE_URL')
    
    if not database_url:
        print("❌ DATABASE_URL not set in environment variables")
        return None
    
    try:
        # First attempt: Try with SSL (required for Vercel/Production)
        conn = psycopg2.connect(database_url, sslmode='require')
        print("✅ Connected to database with SSL")
        return conn
    except Exception as ssl_error:
        # SSL failed - probably local development without SSL
        print(f"⚠️ SSL connection failed: {ssl_error}")
        
        try:
            # Second attempt: Try without SSL (for local development)
            # Remove sslmode from URL if present
            if 'sslmode=' in database_url:
                database_url = database_url.split('?')[0]
            
            conn = psycopg2.connect(database_url)
            print("✅ Connected to database without SSL (local mode)")
            return conn
        except Exception as no_ssl_error:
            print(f"❌ All connection attempts failed: {no_ssl_error}")
            return None

# ============= DATABASE INITIALIZATION =============
def init_db():
    """Initialize database tables if they don't exist."""
    conn = get_db_connection()
    if conn is None:
        print("⚠️ Skipping database initialization - connection failed")
        return
    
    try:
        cur = conn.cursor()
        
        # Create courses table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS courses (
                id SERIAL PRIMARY KEY,
                course_name VARCHAR(255) NOT NULL,
                course_code VARCHAR(50) NOT NULL UNIQUE,
                description TEXT,
                exam_type VARCHAR(20) NOT NULL CHECK (exam_type IN ('Mid', 'Final', 'Notes')),
                year INTEGER NOT NULL,
                pdf_url VARCHAR(500) NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Create admin users table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS admin_users (
                id SERIAL PRIMARY KEY,
                username VARCHAR(50) UNIQUE NOT NULL,
                password_hash VARCHAR(255) NOT NULL,
                email VARCHAR(255) UNIQUE NOT NULL,
                reset_token VARCHAR(255),
                reset_token_expires TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_login TIMESTAMP
            )
        """)
        
        # Create indexes for performance
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_course_code ON courses(course_code);
            CREATE INDEX IF NOT EXISTS idx_course_name ON courses(course_name);
            CREATE INDEX IF NOT EXISTS idx_exam_type ON courses(exam_type);
            CREATE INDEX IF NOT EXISTS idx_admin_username ON admin_users(username);
            CREATE INDEX IF NOT EXISTS idx_admin_email ON admin_users(email);
        """)
        
        # Create default admin user if none exists
        cur.execute("SELECT COUNT(*) FROM admin_users")
        count = cur.fetchone()[0]
        
        if count == 0:
            default_password = hash_password("admin123")
            cur.execute("""
                INSERT INTO admin_users (username, password_hash, email)
                VALUES (%s, %s, %s)
            """, ("admin", default_password, "admin@example.com"))
            print("✅ Default admin created: admin / admin123")
        
        conn.commit()
        cur.close()
        print("✅ Database initialized successfully")
    except Exception as e:
        print(f"❌ Database initialization error: {e}")
    finally:
        conn.close()

# ============= PASSWORD UTILITIES =============
def hash_password(password):
    salt = secrets.token_hex(16)
    hash_obj = hashlib.sha256((salt + password).encode())
    return f"{salt}${hash_obj.hexdigest()}"

def verify_password(password, hashed):
    try:
        salt, hash_value = hashed.split('$')
        hash_obj = hashlib.sha256((salt + password).encode())
        return hash_obj.hexdigest() == hash_value
    except:
        return False

def generate_reset_token():
    return secrets.token_urlsafe(32)

# ============= AUTH DECORATOR =============
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return jsonify({'error': 'Authentication required'}), 401
        return f(*args, **kwargs)
    return decorated_function

# Initialize database on startup
init_db()

# ============= AUTH ROUTES =============
@app.route('/api/admin/login', methods=['POST'])
def admin_login():
    try:
        data = request.get_json()
        username = data.get('username')
        password = data.get('password')
        
        if not username or not password:
            return jsonify({'error': 'Username and password required'}), 400
        
        conn = get_db_connection()
        if conn is None:
            return jsonify({'error': 'Database connection failed'}), 500
        
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        cur.execute("SELECT * FROM admin_users WHERE username = %s", (username,))
        user = cur.fetchone()
        
        if not user or not verify_password(password, user['password_hash']):
            cur.close()
            conn.close()
            return jsonify({'error': 'Invalid username or password'}), 401
        
        cur.execute("UPDATE admin_users SET last_login = CURRENT_TIMESTAMP WHERE id = %s", (user['id'],))
        conn.commit()
        
        session['user_id'] = user['id']
        session['username'] = user['username']
        session.permanent = True
        
        cur.close()
        conn.close()
        
        return jsonify({
            'message': 'Login successful',
            'user': {
                'id': user['id'],
                'username': user['username'],
                'email': user['email']
            }
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/admin/logout', methods=['POST'])
def admin_logout():
    session.clear()
    return jsonify({'message': 'Logged out successfully'})

@app.route('/api/admin/check-auth')
def check_auth():
    if 'user_id' in session:
        return jsonify({
            'authenticated': True,
            'user': {
                'id': session['user_id'],
                'username': session.get('username')
            }
        })
    return jsonify({'authenticated': False}), 401

@app.route('/api/admin/request-reset', methods=['POST'])
def request_password_reset():
    try:
        data = request.get_json()
        email = data.get('email')
        
        if not email:
            return jsonify({'error': 'Email required'}), 400
        
        conn = get_db_connection()
        if conn is None:
            return jsonify({'error': 'Database connection failed'}), 500
        
        cur = conn.cursor()
        cur.execute("SELECT id FROM admin_users WHERE email = %s", (email,))
        user = cur.fetchone()
        
        if not user:
            cur.close()
            conn.close()
            return jsonify({'message': 'If an account exists, a reset link will be sent'})
        
        token = generate_reset_token()
        expires = datetime.datetime.now() + datetime.timedelta(hours=24)
        
        cur.execute("""
            UPDATE admin_users 
            SET reset_token = %s, reset_token_expires = %s 
            WHERE id = %s
        """, (token, expires, user[0]))
        conn.commit()
        cur.close()
        conn.close()
        
        reset_link = f"{request.host_url}admin/reset-password?token={token}"
        
        return jsonify({
            'message': 'Reset token generated',
            'reset_link': reset_link,
            'token': token
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/admin/reset-password', methods=['POST'])
def reset_password():
    try:
        data = request.get_json()
        token = data.get('token')
        new_password = data.get('new_password')
        confirm_password = data.get('confirm_password')
        
        if not token or not new_password or not confirm_password:
            return jsonify({'error': 'All fields required'}), 400
        
        if new_password != confirm_password:
            return jsonify({'error': 'Passwords do not match'}), 400
        
        if len(new_password) < 6:
            return jsonify({'error': 'Password must be at least 6 characters'}), 400
        
        conn = get_db_connection()
        if conn is None:
            return jsonify({'error': 'Database connection failed'}), 500
        
        cur = conn.cursor()
        cur.execute("""
            SELECT id FROM admin_users 
            WHERE reset_token = %s AND reset_token_expires > CURRENT_TIMESTAMP
        """, (token,))
        user = cur.fetchone()
        
        if not user:
            cur.close()
            conn.close()
            return jsonify({'error': 'Invalid or expired token'}), 400
        
        hashed_password = hash_password(new_password)
        cur.execute("""
            UPDATE admin_users 
            SET password_hash = %s, reset_token = NULL, reset_token_expires = NULL 
            WHERE id = %s
        """, (hashed_password, user[0]))
        conn.commit()
        cur.close()
        conn.close()
        
        return jsonify({'message': 'Password reset successfully'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ============= MAIN ROUTES =============
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/admin')
def admin():
    return render_template('admin.html')

@app.route('/course/<int:course_id>')
def course_detail(course_id):
    return render_template('course.html', course_id=course_id)

# ============= API ROUTES =============
@app.route('/api/courses')
def get_courses():
    try:
        page = int(request.args.get('page', 1))
        limit = int(request.args.get('limit', 20))
        offset = (page - 1) * limit
        
        conn = get_db_connection()
        if conn is None:
            return jsonify({'error': 'Database connection failed'}), 500
        
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        cur.execute("SELECT COUNT(*) FROM courses")
        total_count = cur.fetchone()[0]
        
        cur.execute("""
            SELECT * FROM courses 
            ORDER BY created_at DESC 
            LIMIT %s OFFSET %s
        """, (limit, offset))
        
        courses = [dict(row) for row in cur.fetchall()]
        cur.close()
        conn.close()
        
        return jsonify({
            'courses': courses,
            'total': total_count,
            'page': page,
            'limit': limit,
            'total_pages': (total_count + limit - 1) // limit
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/search')
def search_courses():
    try:
        query = request.args.get('q', '').strip()
        if not query:
            return jsonify({'courses': []})
        
        conn = get_db_connection()
        if conn is None:
            return jsonify({'error': 'Database connection failed'}), 500
        
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        search_pattern = f"%{query}%"
        
        cur.execute("""
            SELECT * FROM courses 
            WHERE LOWER(course_name) LIKE LOWER(%s) 
               OR LOWER(course_code) LIKE LOWER(%s)
            ORDER BY 
                CASE 
                    WHEN LOWER(course_name) = LOWER(%s) THEN 1
                    WHEN LOWER(course_code) = LOWER(%s) THEN 2
                    WHEN LOWER(course_name) LIKE LOWER(%s) THEN 3
                    WHEN LOWER(course_code) LIKE LOWER(%s) THEN 4
                    ELSE 5
                END,
                created_at DESC
        """, (search_pattern, search_pattern, query, query, search_pattern, search_pattern))
        
        courses = [dict(row) for row in cur.fetchall()]
        cur.close()
        conn.close()
        
        return jsonify({'courses': courses})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/admin/upload', methods=['POST'])
@login_required
def upload_course():
    try:
        course_name = request.form.get('course_name')
        course_code = request.form.get('course_code')
        description = request.form.get('description')
        exam_type = request.form.get('exam_type')
        year = request.form.get('year')
        
        if not all([course_name, course_code, exam_type, year]):
            return jsonify({'error': 'Missing required fields'}), 400
        
        if exam_type not in ['Mid', 'Final', 'Notes']:
            return jsonify({'error': 'Invalid exam type'}), 400
        
        if 'pdf_file' not in request.files:
            return jsonify({'error': 'No PDF file uploaded'}), 400
        
        pdf_file = request.files['pdf_file']
        if pdf_file.filename == '':
            return jsonify({'error': 'No file selected'}), 400
        
        filename = secure_filename(pdf_file.filename)
        if not filename.endswith('.pdf'):
            return jsonify({'error': 'Only PDF files are allowed'}), 400
        
        try:
            file_content = pdf_file.read()
            blob_data = put(
                f"courses/{course_code}_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}_{filename}",
                file_content,
                {'contentType': 'application/pdf'}
            )
            pdf_url = blob_data['url']
        except Exception as e:
            return jsonify({'error': f'Failed to upload PDF: {str(e)}'}), 500
        
        conn = get_db_connection()
        if conn is None:
            return jsonify({'error': 'Database connection failed'}), 500
        
        try:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO courses 
                (course_name, course_code, description, exam_type, year, pdf_url)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING id
            """, (course_name, course_code, description, exam_type, year, pdf_url))
            
            course_id = cur.fetchone()[0]
            conn.commit()
            cur.close()
            conn.close()
            
            return jsonify({
                'message': 'Course uploaded successfully',
                'course_id': course_id
            }), 201
        except psycopg2.IntegrityError:
            conn.rollback()
            return jsonify({'error': 'Course code already exists'}), 400
        except Exception as e:
            conn.rollback()
            return jsonify({'error': f'Database error: {str(e)}'}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/admin/course/<int:course_id>', methods=['DELETE'])
@login_required
def delete_course(course_id):
    try:
        conn = get_db_connection()
        if conn is None:
            return jsonify({'error': 'Database connection failed'}), 500
        
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        cur.execute("SELECT pdf_url FROM courses WHERE id = %s", (course_id,))
        course = cur.fetchone()
        
        if not course:
            cur.close()
            conn.close()
            return jsonify({'error': 'Course not found'}), 404
        
        pdf_url = course['pdf_url']
        cur.execute("DELETE FROM courses WHERE id = %s", (course_id,))
        conn.commit()
        cur.close()
        
        if pdf_url:
            try:
                blob_delete(pdf_url)
            except Exception as e:
                print(f"Warning: Could not delete blob: {e}")
        
        conn.close()
        return jsonify({'message': 'Course deleted successfully'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/admin/courses')
@login_required
def get_all_courses():
    try:
        conn = get_db_connection()
        if conn is None:
            return jsonify({'error': 'Database connection failed'}), 500
        
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        cur.execute("SELECT * FROM courses ORDER BY created_at DESC")
        courses = [dict(row) for row in cur.fetchall()]
        cur.close()
        conn.close()
        
        return jsonify({'courses': courses})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ============= ERROR HANDLERS =============
@app.errorhandler(404)
def not_found(e):
    return jsonify({'error': 'Resource not found'}), 404

@app.errorhandler(500)
def server_error(e):
    return jsonify({'error': 'Internal server error'}), 500

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
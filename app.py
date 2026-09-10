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
from werkzeug.security import generate_password_hash, check_password_hash
import datetime
from functools import wraps
import urllib.parse

from pathlib import Path

app = Flask(__name__)
CORS(app)

# BASE_DIR = Path(__file__).resolve().parent
# load_dotenv(BASE_DIR / ".env")

# Configuration
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-key-change-in-production')
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024
app.config['SESSION_COOKIE_SECURE'] = os.environ.get(
    "FLASK_ENV", "development"
) == "production"
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['PERMANENT_SESSION_LIFETIME'] = datetime.timedelta(hours=24)

# ============= SINGLE DATABASE CONNECTION FUNCTION =============
def get_db_connection():
    database_url = os.environ.get("DATABASE_URL")

    if not database_url:
        print("❌ DATABASE_URL is not configured.")
        return None

    try:
        conn = psycopg2.connect(
            database_url,
            connect_timeout=10
        )

        print("✅ PostgreSQL connection successful")
        return conn

    except psycopg2.Error as e:
        print(f"❌ PostgreSQL connection failed: {e}")
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
                course_code VARCHAR(50)  NOT NULL,
                description TEXT,
                exam_type VARCHAR(20) NOT NULL
                    CHECK (exam_type IN ('Mid', 'Final', 'Notes')),
                year INTEGER NOT NULL,
                pdf_url VARCHAR(500) NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                CONSTRAINT courses_code_type_year_unique
                    UNIQUE (course_code, exam_type, year)
            )
        """)

        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_courses_course_code
                ON courses(course_code);
            CREATE INDEX IF NOT EXISTS idx_courses_name
                ON courses(course_name);
            CREATE INDEX IF NOT EXISTS idx_courses_exam_type
                ON courses(exam_type);
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

import requests  # add this import at the top

# ===================== VERCEL BLOB HELPERS =====================

BLOB_API_BASE = "https://blob.vercel-storage.com"

def _blob_token():
    """Read the Blob token from env at call time (never cache at import)."""
    token = os.environ.get("BLOB_READ_WRITE_TOKEN")
    if not token:
        raise RuntimeError(
            "BLOB_READ_WRITE_TOKEN is not set. Add it in Vercel → Settings → "
            "Environment Variables and redeploy."
        )
    return token


def upload_pdf_to_blob(pathname: str, file_bytes: bytes) -> str:
    """
    Upload a PDF to Vercel Blob via the official REST API.
    Returns the public URL of the uploaded blob.

    Docs: https://vercel.com/docs/storage/vercel-blob/using-blob-sdk#api
    """
    token = _blob_token()
    headers = {
        "Authorization": f"Bearer {token}",
        "x-api-version": "7",
        "x-content-type": "application/pdf",
        "x-add-random-suffix": "1",
        "access": "public",
    }
    # Vercel Blob REST: PUT /<pathname> with raw body
    url = f"{BLOB_API_BASE}/{pathname.lstrip('/')}"
    resp = requests.put(url, headers=headers, data=file_bytes, timeout=60)

    if resp.status_code not in (200, 201):
        raise RuntimeError(
            f"Blob upload failed ({resp.status_code}): {resp.text[:300]}"
        )

    data = resp.json()
    # REST response includes the public URL
    return data.get("url") or data.get("downloadUrl")

# ============================================================
# ADMIN REGISTRATION (first admin only)
# ============================================================

@app.route('/api/admin/exists')
def admin_exists():
    """Return whether at least one admin account exists."""
    try:
        conn = get_db_connection()
        if conn is None:
            return jsonify({'error': 'Database connection failed'}), 500

        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM admin_users")
        count = cur.fetchone()[0]
        cur.close()
        conn.close()

        return jsonify({'exists': count > 0})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/admin/register', methods=['POST'])
def admin_register():
    """
    Register the FIRST admin only.
    After one admin exists, this endpoint permanently returns 403.
    """
    conn = None
    try:
        # ---- 1. Parse input ----
        data = request.get_json(silent=True) or {}
        username = (data.get('username') or '').strip()
        email    = (data.get('email')    or '').strip().lower()
        password = data.get('password')  or ''
        confirm  = data.get('confirm_password') or ''

        # ---- 2. Validate ----
        if not username or not email or not password:
            return jsonify({'error': 'Username, email and password are required'}), 400

        if len(username) < 3 or len(username) > 50:
            return jsonify({'error': 'Username must be 3–50 characters'}), 400

        # Basic email sanity
        if '@' not in email or '.' not in email.split('@')[-1]:
            return jsonify({'error': 'Please enter a valid email address'}), 400

        if len(password) < 8:
            return jsonify({'error': 'Password must be at least 8 characters'}), 400

        if password != confirm:
            return jsonify({'error': 'Passwords do not match'}), 400

        # ---- 3. Open DB, hard-block if an admin already exists ----
        conn = get_db_connection()
        if conn is None:
            return jsonify({'error': 'Database connection failed'}), 500

        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

        cur.execute("SELECT COUNT(*) AS c FROM admin_users")
        if cur.fetchone()['c'] > 0:
            cur.close()
            conn.close()
            return jsonify({
                'error': 'An admin account already exists. Registration is disabled.'
            }), 403

        # ---- 4. Insert new admin with hashed password ----
        password_hash = hash_password(password)

        try:
            cur.execute("""
                INSERT INTO admin_users (username, email, password_hash)
                VALUES (%s, %s, %s)
                RETURNING id, username, email
            """, (username, email, password_hash))
            row = cur.fetchone()
            conn.commit()
        except psycopg2.IntegrityError as ie:
            conn.rollback()
            cur.close()
            conn.close()
            # Unique constraint on username or email
            msg = 'Username or email already taken'
            if 'username' in str(ie).lower():
                msg = 'That username is already taken'
            elif 'email' in str(ie).lower():
                msg = 'That email is already registered'
            return jsonify({'error': msg}), 409

        # ---- 5. Auto-login the new admin ----
        session['user_id'] = row['id']
        session['username'] = row['username']
        session.permanent = True

        cur.close()
        conn.close()

        return jsonify({
            'message': 'Admin account created successfully',
            'user': {
                'id': row['id'],
                'username': row['username'],
                'email': row['email'],
            }
        }), 201

    except Exception as e:
        if conn is not None:
            try:
                conn.rollback()
            except Exception:
                pass
        return jsonify({'error': str(e)}), 500


def delete_pdf_from_blob(blob_url: str) -> None:
    """Delete a blob by its public URL."""
    try:
        token = _blob_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "x-api-version": "7",
        }
        # Extract pathname from the full URL
        pathname = blob_url.split(f"{BLOB_API_BASE}/", 1)[-1]
        url = f"{BLOB_API_BASE}/{pathname}"
        requests.delete(url, headers=headers, timeout=30)
    except Exception as e:
        # Non-fatal — orphan blob will be cleaned up later if needed
        print(f"Blob delete warning: {e}")

# ============= PASSWORD UTILITIES =============
def hash_password(password):
    return generate_password_hash(password)

def verify_password(password, hashed):
    if not password or not hashed:
        return False
    try:
        return check_password_hash(hashed, password)
    except Exception:
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
# init_db()

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
    """
    Upload a paper. If the course code already exists, only the new paper
    row is inserted (the card on the homepage automatically groups by code).
    """
    conn = None
    try:
        # ---------- 1. Read & validate form fields ----------
        course_name  = (request.form.get('course_name')  or '').strip()
        course_code  = (request.form.get('course_code')  or '').strip().upper()
        description  = (request.form.get('description')  or '').strip()
        exam_type    = (request.form.get('exam_type')    or '').strip()
        year_raw     = (request.form.get('year')         or '').strip()

        if not all([course_name, course_code, exam_type, year_raw]):
            return jsonify({'error': 'Missing required fields'}), 400

        if exam_type not in ('Mid', 'Final', 'Notes'):
            return jsonify({'error': 'Invalid exam type'}), 400

        try:
            year = int(year_raw)
        except ValueError:
            return jsonify({'error': 'Year must be a number'}), 400

        if year < 2000 or year > 2100:
            return jsonify({'error': 'Year must be between 2000 and 2100'}), 400

        # ---------- 2. Validate the uploaded file ----------
        if 'pdf_file' not in request.files:
            return jsonify({'error': 'No PDF file uploaded'}), 400

        pdf_file = request.files['pdf_file']
        if not pdf_file.filename:
            return jsonify({'error': 'No file selected'}), 400

        filename = secure_filename(pdf_file.filename)
        if not filename.lower().endswith('.pdf'):
            return jsonify({'error': 'Only PDF files are allowed'}), 400

        # ---------- 3. Open DB connection early (needed for the lookup) ----------
        conn = get_db_connection()
        if conn is None:
            return jsonify({'error': 'Database connection failed'}), 500

        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

        # ---------- 4. Does this course code already exist? ----------
        cur.execute("""
            SELECT id, course_name, description
            FROM courses
            WHERE UPPER(course_code) = %s
            ORDER BY created_at ASC
            LIMIT 1
        """, (course_code,))
        existing = cur.fetchone()

        is_new_course = existing is None

        if is_new_course:
            # A brand new course — use what the admin typed
            final_name        = course_name
            final_description = description
        else:
            # Course already exists — keep its canonical name/description.
            # If the admin typed a new description, adopt it (optional update).
            final_name        = existing['course_name']
            final_description = description or existing['description']

        # ---------- 5. Prevent duplicate (code + type + year) ----------
        cur.execute("""
            SELECT id FROM courses
            WHERE UPPER(course_code) = %s
              AND exam_type = %s
              AND year = %s
        """, (course_code, exam_type, year))

        if cur.fetchone():
            cur.close()
            conn.close()
            return jsonify({
                'error': (
                    f'{course_code} already has a {exam_type} paper '
                    f'for {year}. Delete it first if you want to re-upload.'
                )
            }), 409

        # ---------- 6. Upload PDF to Vercel Blob ----------
        try:
            file_content = pdf_file.read()
            pathname = (
                f"courses/{course_code}_"
                f"{exam_type.lower()}_{year}_"
                f"{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}_"
                f"{filename}"
            )
            pdf_url = upload_pdf_to_blob(pathname, file_content)
        except Exception as e:
            cur.close()
            conn.close()
            return jsonify({'error': f'Failed to upload PDF: {str(e)}'}), 500

        # ---------- 7. Insert the paper row ----------
        try:
            cur.execute("""
                INSERT INTO courses
                    (course_name, course_code, description, exam_type, year, pdf_url)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING id
            """, (
                final_name,
                course_code,
                final_description,
                exam_type,
                year,
                pdf_url,
            ))
            new_paper_id = cur.fetchone()['id']
            conn.commit()
        except psycopg2.IntegrityError as ie:
            conn.rollback()
            cur.close()
            conn.close()
            return jsonify({
                'error': 'A matching paper already exists (code + type + year).'
            }), 409
        except Exception as e:
            conn.rollback()
            cur.close()
            conn.close()
            return jsonify({'error': f'Database error: {str(e)}'}), 500

        # ---------- 8. Count total papers for this course ----------
        cur.execute(
            "SELECT COUNT(*) AS total FROM courses WHERE UPPER(course_code) = %s",
            (course_code,)
        )
        total_papers = cur.fetchone()['total']

        cur.close()
        conn.close()

        # ---------- 9. Friendly response ----------
        if is_new_course:
            message = (
                f'New course {course_code} created with its first '
                f'{exam_type} paper ({year}).'
            )
        else:
            message = (
                f'Added {exam_type} paper ({year}) to {course_code}. '
                f'This course now has {total_papers} paper'
                f'{"" if total_papers == 1 else "s"}.'
            )

        return jsonify({
            'message': message,
            'course_id': new_paper_id,
            'course_code': course_code,
            'is_new_course': is_new_course,
            'total_papers': total_papers,
        }), 201

    except Exception as e:
        if conn is not None:
            try:
                conn.rollback()
            except Exception:
                pass
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
            delete_pdf_from_blob(pdf_url)
        
        conn.close()
        return jsonify({'message': 'Course deleted successfully'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/admin/courses')
@login_required
def get_all_courses():
    """
    Admin course list — one entry per course code, with a breakdown
    of papers grouped by exam type. This mirrors /api/courses/grouped
    but is not paginated (admin wants to see everything).
    """
    try:
        conn = get_db_connection()
        if conn is None:
            return jsonify({'error': 'Database connection failed'}), 500

        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

        # One row per course_code with aggregate info
        cur.execute("""
            SELECT
                MIN(id)                                        AS id,
                course_name,
                course_code,
                MAX(year)                                      AS latest_year,
                COUNT(*)                                       AS paper_count,
                (ARRAY_AGG(description ORDER BY year DESC))[1] AS description,
                MAX(created_at)                                AS last_uploaded,
                -- Papers by type: comma-separated years per type
                COALESCE(
                    ARRAY_AGG(DISTINCT year ORDER BY year DESC)
                        FILTER (WHERE exam_type = 'Mid'),
                    '{}'
                ) AS mid_years,
                COALESCE(
                    ARRAY_AGG(DISTINCT year ORDER BY year DESC)
                        FILTER (WHERE exam_type = 'Final'),
                    '{}'
                ) AS final_years,
                COALESCE(
                    ARRAY_AGG(DISTINCT year ORDER BY year DESC)
                        FILTER (WHERE exam_type = 'Notes'),
                    '{}'
                ) AS notes_years
            FROM courses
            GROUP BY course_name, course_code
            ORDER BY MAX(created_at) DESC
        """)

        rows = cur.fetchall()

        # Also fetch every individual paper so the admin can view/delete each
        cur.execute("""
            SELECT id, course_code, exam_type, year, pdf_url
            FROM courses
            ORDER BY course_code, exam_type, year DESC
        """)
        all_papers = cur.fetchall()

        cur.close()
        conn.close()

        # Group papers by course_code for fast attachment
        papers_by_code = {}
        for p in all_papers:
            papers_by_code.setdefault(p['course_code'], []).append({
                'id':        p['id'],
                'exam_type': p['exam_type'],
                'year':      p['year'],
                'pdf_url':   p['pdf_url'],
            })

        courses = []
        for row in rows:
            c = dict(row)
            c['papers'] = papers_by_code.get(c['course_code'], [])
            # Postgres returns integer[] — convert to plain list for JSON
            c['mid_years']   = list(c.get('mid_years')   or [])
            c['final_years'] = list(c.get('final_years') or [])
            c['notes_years'] = list(c.get('notes_years') or [])
            c.pop('last_uploaded', None)  # not needed in the payload
            courses.append(c)

        return jsonify({
            'courses': courses,
            'total_courses': len(courses),
            'total_papers': sum(c['paper_count'] for c in courses),
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ============= ERROR HANDLERS =============
@app.errorhandler(404)
def not_found(e):
    return jsonify({'error': 'Resource not found'}), 404

@app.errorhandler(500)
def server_error(e):
    return jsonify({'error': 'Internal server error'}), 500

@app.route('/api/courses/grouped')
def get_grouped_courses():
    """Return one entry per course with paper count and latest year."""
    try:
        page = int(request.args.get('page', 1))
        limit = int(request.args.get('limit', 20))
        offset = (page - 1) * limit

        conn = get_db_connection()
        if conn is None:
            return jsonify({'error': 'Database connection failed'}), 500

        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

        # Total distinct courses
        cur.execute("SELECT COUNT(DISTINCT course_code) FROM courses")
        total_count = cur.fetchone()[0]

        # Grouped courses with count + latest year + latest description
        cur.execute("""
            SELECT
                MIN(id)                                   AS id,
                course_name,
                course_code,
                MAX(year)                                 AS latest_year,
                COUNT(*)                                  AS paper_count,
                (ARRAY_AGG(description ORDER BY year DESC))[1] AS description,
                (ARRAY_AGG(exam_type  ORDER BY year DESC))[1] AS latest_exam_type
            FROM courses
            GROUP BY course_name, course_code
            ORDER BY MAX(created_at) DESC
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


@app.route('/api/courses/grouped/search')
def search_grouped_courses():
    """Search grouped courses by name or code."""
    try:
        query = request.args.get('q', '').strip()
        if not query:
            return jsonify({'courses': []})

        conn = get_db_connection()
        if conn is None:
            return jsonify({'error': 'Database connection failed'}), 500

        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        pattern = f"%{query}%"

        cur.execute("""
            SELECT
                MIN(id)                                   AS id,
                course_name,
                course_code,
                MAX(year)                                 AS latest_year,
                COUNT(*)                                  AS paper_count,
                (ARRAY_AGG(description ORDER BY year DESC))[1] AS description,
                (ARRAY_AGG(exam_type  ORDER BY year DESC))[1] AS latest_exam_type
            FROM courses
            WHERE LOWER(course_name) LIKE LOWER(%s)
               OR LOWER(course_code) LIKE LOWER(%s)
            GROUP BY course_name, course_code
            ORDER BY
                CASE
                    WHEN LOWER(course_code) = LOWER(%s) THEN 1
                    WHEN LOWER(course_name) = LOWER(%s) THEN 2
                    ELSE 3
                END,
                MAX(created_at) DESC
        """, (pattern, pattern, query, query))

        courses = [dict(row) for row in cur.fetchall()]
        cur.close()
        conn.close()

        return jsonify({'courses': courses})

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/course/<int:course_id>')
def get_course_detail(course_id):
    """Get grouped details for one course."""
    try:
        conn = get_db_connection()
        if conn is None:
            return jsonify({'error': 'Database connection failed'}), 500

        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

        # Get one row per distinct course_code — but we only have id, so find the
        # course_code first via the row's id, then aggregate all matching rows.
        cur.execute("SELECT course_code FROM courses WHERE id = %s", (course_id,))
        row = cur.fetchone()
        if not row:
            cur.close(); conn.close()
            return jsonify({'error': 'Course not found'}), 404

        course_code = row['course_code']

        cur.execute("""
            SELECT
                MIN(id)                                   AS id,
                course_name,
                course_code,
                MAX(year)                                 AS latest_year,
                COUNT(*)                                  AS paper_count,
                (ARRAY_AGG(description ORDER BY year DESC))[1] AS description
            FROM courses
            WHERE course_code = %s
            GROUP BY course_name, course_code
        """, (course_code,))

        course = cur.fetchone()
        cur.close(); conn.close()

        if not course:
            return jsonify({'error': 'Course not found'}), 404

        return jsonify(dict(course))

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/course/<int:course_id>/papers')
def get_course_papers(course_id):
    """Return all papers for a course, optionally filtered by exam_type."""
    try:
        exam_type = request.args.get('type', '').strip()  # Mid | Final | Notes | ''
        conn = get_db_connection()
        if conn is None:
            return jsonify({'error': 'Database connection failed'}), 500

        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

        cur.execute("SELECT course_code FROM courses WHERE id = %s", (course_id,))
        row = cur.fetchone()
        if not row:
            cur.close(); conn.close()
            return jsonify({'error': 'Course not found'}), 404

        course_code = row['course_code']

        if exam_type and exam_type in ('Mid', 'Final', 'Notes'):
            cur.execute("""
                SELECT id, course_name, course_code, exam_type, year, pdf_url, description
                FROM courses
                WHERE course_code = %s AND exam_type = %s
                ORDER BY year DESC
            """, (course_code, exam_type))
        else:
            cur.execute("""
                SELECT id, course_name, course_code, exam_type, year, pdf_url, description
                FROM courses
                WHERE course_code = %s
                ORDER BY year DESC
            """, (course_code,))

        papers = [dict(r) for r in cur.fetchall()]
        cur.close(); conn.close()

        return jsonify({'papers': papers, 'course_code': course_code})

    except Exception as e:
        return jsonify({'error': str(e)}), 500

import secrets
print(secrets.token_hex(32))

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
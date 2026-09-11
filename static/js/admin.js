// ============================================================
// Admin Dashboard JavaScript — grouped course list + auth + CSRF
// Includes: first-time admin registration
// ============================================================

let csrfToken = '';

// ---------- CSRF helpers (defined first so class can use them) ----------
async function fetchCsrfToken() {
    try {
        const res = await fetch('/api/admin/check-auth', {
            credentials: 'same-origin'
        });
        if (res.ok) {
            const data = await res.json();
            csrfToken = data.csrf_token || '';
        }
    } catch (e) {
        console.warn('Could not fetch CSRF token', e);
    }
}

function csrfFetch(url, options = {}) {
    const headers = new Headers(options.headers || {});
    if (csrfToken) headers.set('X-CSRF-Token', csrfToken);
    return fetch(url, {
        ...options,
        headers,
        credentials: 'same-origin'
    });
}

// ============================================================
// AdminDashboard
// ============================================================
class AdminDashboard {
    constructor() {
        this.isAuthenticated = false;
        this.user = null;

        // Auth cards
        this.loginCard      = document.getElementById('loginCard');
        this.registerCard   = document.getElementById('registerCard');

        // Forms
        this.loginForm      = document.getElementById('loginForm');
        this.registerForm   = document.getElementById('registerForm');
        this.resetForm      = document.getElementById('resetForm');
        this.uploadForm     = document.getElementById('uploadForm');

        // Status elements
        this.loginStatus    = document.getElementById('loginStatus');
        this.registerStatus = document.getElementById('registerStatus');
        this.resetStatus    = document.getElementById('resetStatus');
        this.uploadStatus   = document.getElementById('uploadStatus');

        // Upload / list
        this.courseList     = document.getElementById('adminCoursesList');
        this.courseCount    = document.getElementById('courseCount');
        this.fileInput      = document.getElementById('pdfFile');
        this.fileName       = document.getElementById('fileName');

        // User display
        this.usernameDisplay = document.getElementById('usernameDisplay');

        this.init();
    }

    async init() {
        await fetchCsrfToken();
        await this.checkAuth();
        this.setupEventListeners();
        if (this.isAuthenticated) this.loadCourses();
    }

    setupEventListeners() {
        // Login
        if (this.loginForm) {
            this.loginForm.addEventListener('submit', (e) => {
                e.preventDefault();
                this.handleLogin();
            });
        }

        // Register (first admin only)
        if (this.registerForm) {
            this.registerForm.addEventListener('submit', (e) => {
                e.preventDefault();
                this.handleRegister();
            });
        }

        // Password reset request
        if (this.resetForm) {
            this.resetForm.addEventListener('submit', (e) => {
                e.preventDefault();
                this.handleResetRequest();
            });
        }

        // Upload
        if (this.uploadForm) {
            this.uploadForm.addEventListener('submit', (e) => {
                e.preventDefault();
                if (!this.isAuthenticated) {
                    this.showStatus('Please login first.', 'error');
                    return;
                }
                this.handleUpload();
            });

            this.uploadForm.addEventListener('reset', () => {
                if (this.fileName) this.fileName.textContent = 'No file selected';
                if (this.uploadStatus) {
                    this.uploadStatus.className = 'upload-status';
                    this.uploadStatus.textContent = '';
                    this.uploadStatus.style.display = 'none';
                }
            });
        }

        // File input name preview
        if (this.fileInput) {
            this.fileInput.addEventListener('change', (e) => {
                const file = e.target.files[0];
                if (this.fileName) this.fileName.textContent = file ? file.name : 'No file selected';
            });
        }
    }

    // ---------- AUTH ----------
    async checkAuth() {
        try {
            const response = await fetch('/api/admin/check-auth', {
                credentials: 'same-origin'
            });
            if (response.ok) {
                const data = await response.json();
                this.isAuthenticated = true;
                this.user = data.user;
                if (data.csrf_token) csrfToken = data.csrf_token;
                this.showAdminContent();
                if (this.usernameDisplay && this.user) {
                    this.usernameDisplay.textContent = this.user.username;
                }
            } else {
                this.isAuthenticated = false;
                this.showLoginForm();
                await this.decideLoginOrRegister();
            }
        } catch (err) {
            console.error('Auth check error:', err);
            this.isAuthenticated = false;
            this.showLoginForm();
            await this.decideLoginOrRegister();
        }
    }

    /**
     * Ask the server whether any admin exists yet.
     * - If none: show the register card (first-time setup).
     * - If one exists: show only the login card.
     * Falls back to login card on any error so the user is never stuck.
     */
    async decideLoginOrRegister() {
        try {
            const res = await fetch('/api/admin/exists', {
                credentials: 'same-origin'
            });
            if (!res.ok) throw new Error('exists check failed');
            const data = await res.json();

            if (data.exists) {
                if (this.loginCard)    this.loginCard.style.display    = 'block';
                if (this.registerCard) this.registerCard.style.display = 'none';
            } else {
                if (this.loginCard)    this.loginCard.style.display    = 'none';
                if (this.registerCard) this.registerCard.style.display = 'block';
            }
        } catch (err) {
            console.error('admin/exists error:', err);
            // Safe fallback: show login only
            if (this.loginCard)    this.loginCard.style.display    = 'block';
            if (this.registerCard) this.registerCard.style.display = 'none';
        }
    }

    async handleLogin() {
        const username = document.getElementById('loginUsername').value;
        const password = document.getElementById('loginPassword').value;

        if (!username || !password) {
            this.showLoginStatus('Please enter username and password.', 'error');
            return;
        }

        try {
            const response = await fetch('/api/admin/login', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'same-origin',
                body: JSON.stringify({ username, password })
            });

            const data = await response.json();

            if (response.ok) {
                this.showLoginStatus('Login successful!', 'success');
                this.isAuthenticated = true;
                this.user = data.user;
                if (data.csrf_token) csrfToken = data.csrf_token;

                setTimeout(() => {
                    this.showAdminContent();
                    this.loadCourses();
                    if (this.usernameDisplay && this.user) {
                        this.usernameDisplay.textContent = this.user.username;
                    }
                }, 400);
            } else {
                this.showLoginStatus(data.error || 'Login failed.', 'error');
            }
        } catch (err) {
            console.error('Login error:', err);
            this.showLoginStatus('Network error. Please try again.', 'error');
        }
    }

    /**
     * First-time admin registration.
     * Only succeeds if zero admins exist on the server.
     * On success: auto-login and swap to the dashboard.
     * On 403 (an admin already exists): swap back to login.
     */
    async handleRegister() {
        const username = document.getElementById('registerUsername').value.trim();
        const email    = document.getElementById('registerEmail').value.trim();
        const password = document.getElementById('registerPassword').value;
        const confirm  = document.getElementById('registerConfirm').value;

        // Client-side mirrors of the server-side checks
        if (!username || !email || !password || !confirm) {
            return this.showRegisterStatus('All fields are required.', 'error');
        }
        if (username.length < 3) {
            return this.showRegisterStatus('Username must be at least 3 characters.', 'error');
        }
        if (!email.includes('@') || !email.split('@')[1]?.includes('.')) {
            return this.showRegisterStatus('Please enter a valid email address.', 'error');
        }
        if (password.length < 8) {
            return this.showRegisterStatus('Password must be at least 8 characters.', 'error');
        }
        if (password !== confirm) {
            return this.showRegisterStatus('Passwords do not match.', 'error');
        }

        this.showRegisterStatus('Creating admin account…', 'success');

        try {
            const res = await fetch('/api/admin/register', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'same-origin',
                body: JSON.stringify({
                    username,
                    email,
                    password,
                    confirm_password: confirm
                })
            });

            const data = await res.json();

            if (res.status === 403) {
                // Race: someone registered in another tab first
                this.showRegisterStatus(
                    '⚠ ' + (data.error || 'An admin already exists.'),
                    'error'
                );
                setTimeout(() => this.decideLoginOrRegister(), 2000);
                return;
            }

            if (res.ok) {
                this.showRegisterStatus('✅ Admin created! Redirecting…', 'success');
                this.isAuthenticated = true;
                this.user = data.user;
                if (this.usernameDisplay && this.user) {
                    this.usernameDisplay.textContent = this.user.username;
                }
                setTimeout(() => {
                    this.showAdminContent();
                    this.loadCourses();
                }, 700);
            } else {
                this.showRegisterStatus(
                    '❌ ' + (data.error || 'Registration failed.'),
                    'error'
                );
            }
        } catch (err) {
            console.error('Register error:', err);
            this.showRegisterStatus('❌ Network error. Please try again.', 'error');
        }
    }

    async handleLogout() {
        if (!confirm('Are you sure you want to logout?')) return;

        try {
            const response = await csrfFetch('/api/admin/logout', { method: 'POST' });
            if (response.ok) {
                this.isAuthenticated = false;
                this.user = null;
                csrfToken = '';
                this.showLoginForm();
                this.showLoginStatus('Logged out successfully.', 'success');
                // Re-check whether register card should show
                await this.decideLoginOrRegister();
            }
        } catch (err) {
            console.error('Logout error:', err);
        }
    }

    async handleResetRequest() {
        const email = document.getElementById('resetEmail').value;

        if (!email) {
            this.showResetStatus('Please enter your email address.', 'error');
            return;
        }

        try {
            const response = await fetch('/api/admin/request-reset', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'same-origin',
                body: JSON.stringify({ email })
            });

            const data = await response.json();

            if (response.ok) {
                this.showResetStatus('Reset link sent! Check your email.', 'success');
                if (data.reset_link) console.log('Reset link (dev):', data.reset_link);
                setTimeout(() => closeResetModal(), 3000);
            } else {
                this.showResetStatus(data.error || 'Request failed.', 'error');
            }
        } catch (err) {
            console.error('Reset request error:', err);
            this.showResetStatus('Network error. Please try again.', 'error');
        }
    }

    // ---------- UPLOAD ----------
    async handleUpload() {
        const formData = new FormData();
        const courseCode  = document.getElementById('courseCode');
        const courseName  = document.getElementById('courseName');
        const description = document.getElementById('description');
        const examType    = document.getElementById('examType');
        const year        = document.getElementById('year');
        const pdfFile     = document.getElementById('pdfFile');

        if (!courseCode.value || !courseName.value || !examType.value ||
            !year.value || !pdfFile.files[0]) {
            this.showStatus('Please fill in all required fields.', 'error');
            return;
        }

        const yearNum = parseInt(year.value, 10);
        if (isNaN(yearNum) || yearNum < 2000 || yearNum > 2100) {
            this.showStatus('Please enter a valid year (2000–2100).', 'error');
            return;
        }

        formData.append('course_code', courseCode.value.trim());
        formData.append('course_name', courseName.value.trim());
        formData.append('description', description.value.trim());
        formData.append('exam_type', examType.value);
        formData.append('year', year.value);
        formData.append('pdf_file', pdfFile.files[0]);

        this.showStatus('Uploading… Please wait.', 'info');

        try {
            const response = await csrfFetch('/api/admin/upload', {
                method: 'POST',
                body: formData
            });

            const data = await response.json();

            if (response.ok) {
                const msg = data.message || 'Upload successful';
                const extra = (typeof data.total_papers === 'number')
                    ? ` This course now has ${data.total_papers} paper${data.total_papers === 1 ? '' : 's'}.`
                    : '';
                this.showStatus('✅ ' + msg + extra, 'success');
                this.uploadForm.reset();
                if (this.fileName) this.fileName.textContent = 'No file selected';
                this.loadCourses();
            } else {
                this.showStatus('❌ ' + (data.error || 'Upload failed.'), 'error');
            }
        } catch (err) {
            console.error('Upload error:', err);
            this.showStatus('❌ Network error. Please check your connection.', 'error');
        }
    }

    // ---------- COURSE LIST (grouped) ----------
    async loadCourses() {
        try {
            const response = await fetch('/api/admin/courses', {
                credentials: 'same-origin'
            });

            if (!response.ok) {
                if (response.status === 401) {
                    this.isAuthenticated = false;
                    this.showLoginForm();
                    return;
                }
                throw new Error('Failed to load courses');
            }

            const data = await response.json();
            this.renderCourses(data.courses || []);
            this.updateCount(data.total_courses || 0, data.total_papers || 0);
        } catch (err) {
            console.error('Error loading courses:', err);
            if (this.courseList) {
                this.courseList.innerHTML = `
                    <div class="admin-empty">
                        <i class="fas fa-exclamation-triangle"></i>
                        <p>Failed to load courses. Please refresh.</p>
                    </div>`;
            }
        }
    }

    renderCourses(courses) {
        if (!this.courseList) return;
        this.courseList.innerHTML = '';

        if (!courses.length) {
            this.courseList.innerHTML = `
                <div class="admin-empty">
                    <i class="fas fa-inbox"></i>
                    <p>No courses uploaded yet.</p>
                </div>`;
            return;
        }

        courses.forEach(course => {
            this.courseList.appendChild(this.createCourseItem(course));
        });
    }

    createCourseItem(course) {
        const div = document.createElement('div');
        div.className = 'admin-course-item';
        div.dataset.id = course.id;

        const paperRows = (course.papers || []).map(p => `
            <div class="admin-paper-row">
                <span class="admin-paper-type ${this.esc(p.exam_type.toLowerCase())}">
                    ${this.esc(p.exam_type)}
                </span>
                <span class="admin-paper-year">${this.esc(p.year)}</span>
                <a href="/download/${p.id}" target="_blank" rel="noopener" class="admin-paper-link">
                    <i class="fas fa-file-pdf"></i> View
                </a>
                <button class="admin-paper-delete" data-id="${p.id}"
                        title="Delete this paper" type="button">
                    <i class="fas fa-trash"></i>
                </button>
            </div>
        `).join('');

        const plural = course.paper_count === 1 ? '' : 's';

        div.innerHTML = `
            <div class="admin-course-header">
                <div class="admin-course-info">
                    <span class="admin-course-name">${this.esc(course.course_name)}</span>
                    <span class="admin-course-code">${this.esc(course.course_code)}</span>
                </div>
                <div class="admin-course-meta">
                    <span class="admin-paper-count">
                        <i class="fas fa-file-pdf"></i>
                        ${course.paper_count} Paper${plural}
                    </span>
                    <span class="admin-latest-year">
                        <i class="fas fa-calendar-alt"></i>
                        Latest ${course.latest_year}
                    </span>
                </div>
            </div>
            <div class="admin-papers-list">${paperRows}</div>
        `;

        div.querySelectorAll('.admin-paper-delete').forEach(btn => {
            btn.addEventListener('click', () => this.handleDelete(btn.dataset.id));
        });

        return div;
    }

    async handleDelete(paperId) {
        if (!confirm('Delete this paper? This cannot be undone.')) return;

        try {
            const response = await csrfFetch(`/api/admin/course/${paperId}`, {
                method: 'DELETE'
            });

            if (response.status === 401) {
                this.isAuthenticated = false;
                this.showLoginForm();
                return;
            }

            const data = await response.json();

            if (response.ok) {
                this.showStatus('✅ Paper deleted successfully.', 'success');
                this.loadCourses();
            } else {
                this.showStatus('❌ ' + (data.error || 'Deletion failed.'), 'error');
            }
        } catch (err) {
            console.error('Delete error:', err);
            this.showStatus('❌ Network error. Please try again.', 'error');
        }
    }

    updateCount(courseCount, paperCount) {
        if (!this.courseCount) return;
        const cPart = `${courseCount} course${courseCount === 1 ? '' : 's'}`;
        const pPart = (typeof paperCount === 'number' && paperCount !== courseCount)
            ? ` · ${paperCount} paper${paperCount === 1 ? '' : 's'}`
            : '';
        this.courseCount.textContent = cPart + pPart;
    }

    // ---------- UI toggles ----------
    showAdminContent() {
        const ov = document.getElementById('loginOverlay');
        const ad = document.getElementById('adminContent');
        if (ov) ov.style.display = 'none';
        if (ad) ad.style.display = 'block';
    }

    showLoginForm() {
        const ov = document.getElementById('loginOverlay');
        const ad = document.getElementById('adminContent');
        if (ov) ov.style.display = 'flex';
        if (ad) ad.style.display = 'none';
    }

    showLoginStatus(message, type) {
        if (!this.loginStatus) return;
        this.loginStatus.textContent = message;
        this.loginStatus.className = 'login-status';
        if (type) this.loginStatus.classList.add(type);
        this.loginStatus.style.display = 'block';
    }

    showRegisterStatus(message, type) {
        if (!this.registerStatus) return;
        this.registerStatus.textContent = message;
        this.registerStatus.className = 'login-status';
        if (type) this.registerStatus.classList.add(type);
        this.registerStatus.style.display = 'block';
    }

    showStatus(message, type) {
        if (!this.uploadStatus) return;
        this.uploadStatus.textContent = message;
        this.uploadStatus.className = 'upload-status';
        if (type) this.uploadStatus.classList.add(type);
        this.uploadStatus.style.display = 'block';
        if (type === 'success') {
            setTimeout(() => { this.uploadStatus.style.display = 'none'; }, 5000);
        }
    }

    showResetStatus(message, type) {
        if (!this.resetStatus) return;
        this.resetStatus.textContent = message;
        this.resetStatus.className = 'reset-status';
        if (type) this.resetStatus.classList.add(type);
        this.resetStatus.style.display = 'block';
    }

    esc(text) {
        const d = document.createElement('div');
        d.textContent = text == null ? '' : String(text);
        return d.innerHTML;
    }
}

// ============================================================
// Global helpers
// ============================================================
function showResetForm() {
    const m = document.getElementById('resetModal');
    if (m) m.style.display = 'flex';
}

function closeResetModal() {
    const m = document.getElementById('resetModal');
    if (m) m.style.display = 'none';
    const s = document.getElementById('resetStatus');
    if (s) {
        s.className = 'reset-status';
        s.textContent = '';
        s.style.display = 'none';
    }
}

function handleLogout() {
    if (window.adminDashboard) window.adminDashboard.handleLogout();
}

// ============================================================
// Change Credentials form
// ============================================================
document.addEventListener('DOMContentLoaded', () => {
    const form = document.getElementById('credentialsForm');
    if (!form) return;

    form.addEventListener('submit', async (e) => {
        e.preventDefault();

        const statusEl = document.getElementById('credentialsStatus');
        const show = (msg, type) => {
            if (!statusEl) return;
            statusEl.textContent = msg;
            statusEl.className = 'upload-status ' + type;
            statusEl.style.display = 'block';
        };

        const currentPassword = document.getElementById('currentPassword').value;
        const newUsername     = (document.getElementById('newUsername')?.value || '').trim();
        const confirmUsername = (document.getElementById('confirmNewUsername')?.value || '').trim();
        const newPassword     = document.getElementById('newPassword')?.value || '';
        const confirmPassword = document.getElementById('confirmNewPassword')?.value || '';

        if (!currentPassword) return show('Current password is required', 'error');
        if (newUsername && newUsername !== confirmUsername)
            return show('New usernames do not match', 'error');
        if (newPassword && newPassword !== confirmPassword)
            return show('New passwords do not match', 'error');
        if (!newUsername && !newPassword)
            return show('Provide a new username or new password', 'error');
        if (newPassword && newPassword.length < 8)
            return show('Password must be at least 8 characters', 'error');

        show('Saving…', 'info');

        try {
            const res = await csrfFetch('/api/admin/change-credentials', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    current_password: currentPassword,
                    new_username: newUsername,
                    new_password: newPassword,
                    confirm_password: confirmPassword
                })
            });

            const data = await res.json();

            if (res.ok) {
                if (data.csrf_token) csrfToken = data.csrf_token;
                if (data.username) {
                    const u = document.getElementById('usernameDisplay');
                    if (u) u.textContent = data.username;
                }
                show('✅ ' + (data.message || 'Updated'), 'success');
                form.reset();
            } else {
                show('❌ ' + (data.error || 'Update failed'), 'error');
            }
        } catch (err) {
            console.error(err);
            show('❌ Network error', 'error');
        }
    });
});

// ============================================================
// Boot
// ============================================================
document.addEventListener('DOMContentLoaded', () => {
    window.adminDashboard = new AdminDashboard();
});

window.onclick = function (event) {
    const modal = document.getElementById('resetModal');
    if (event.target === modal) closeResetModal();
};
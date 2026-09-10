// Admin Dashboard JavaScript with Authentication

class AdminDashboard {
    constructor() {
        this.isAuthenticated = false;
        this.user = null;
        
        this.loginForm = document.getElementById('loginForm');
        this.resetForm = document.getElementById('resetForm');
        this.uploadForm = document.getElementById('uploadForm');
        this.courseList = document.getElementById('adminCoursesList');
        this.courseCount = document.getElementById('courseCount');
        this.uploadStatus = document.getElementById('uploadStatus');
        this.loginStatus = document.getElementById('loginStatus');
        this.resetStatus = document.getElementById('resetStatus');
        this.fileInput = document.getElementById('pdfFile');
        this.fileName = document.getElementById('fileName');
        this.usernameDisplay = document.getElementById('usernameDisplay');
        
        this.init();
    }
    
    async init() {
        // Check authentication status
        await this.checkAuth();
        
        // Setup event listeners
        this.setupEventListeners();
        
        // If authenticated, load courses
        if (this.isAuthenticated) {
            this.loadCourses();
        }
    }
    
    setupEventListeners() {
        // Login form
        if (this.loginForm) {
            this.loginForm.addEventListener('submit', (e) => {
                e.preventDefault();
                this.handleLogin();
            });
        }
        
        // Reset form
        if (this.resetForm) {
            this.resetForm.addEventListener('submit', (e) => {
                e.preventDefault();
                this.handleResetRequest();
            });
        }
        
        // Upload form
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
                this.fileName.textContent = 'No file selected';
                this.uploadStatus.className = 'upload-status';
                this.uploadStatus.textContent = '';
                this.uploadStatus.style.display = 'none';
            });
        }
        
        // File input
        if (this.fileInput) {
            this.fileInput.addEventListener('change', (e) => {
                const file = e.target.files[0];
                this.fileName.textContent = file ? file.name : 'No file selected';
            });
        }
    }
    
    async checkAuth() {
        try {
            const response = await fetch('/api/admin/check-auth');
            
            if (response.ok) {
                const data = await response.json();
                this.isAuthenticated = true;
                this.user = data.user;
                this.showAdminContent();
                if (this.usernameDisplay) {
                    this.usernameDisplay.textContent = this.user.username;
                }
            } else {
                this.isAuthenticated = false;
                this.showLoginForm();
            }
        } catch (error) {
            console.error('Auth check error:', error);
            this.isAuthenticated = false;
            this.showLoginForm();
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
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ username, password })
            });
            
            const data = await response.json();
            
            if (response.ok) {
                this.showLoginStatus('Login successful!', 'success');
                this.isAuthenticated = true;
                this.user = data.user;
                
                setTimeout(() => {
                    this.showAdminContent();
                    this.loadCourses();
                    if (this.usernameDisplay) {
                        this.usernameDisplay.textContent = this.user.username;
                    }
                }, 500);
            } else {
                this.showLoginStatus(data.error || 'Login failed.', 'error');
            }
        } catch (error) {
            console.error('Login error:', error);
            this.showLoginStatus('Network error. Please try again.', 'error');
        }
    }
    
    async handleLogout() {
        if (!confirm('Are you sure you want to logout?')) {
            return;
        }
        
        try {
            const response = await fetch('/api/admin/logout', {
                method: 'POST'
            });
            
            if (response.ok) {
                this.isAuthenticated = false;
                this.user = null;
                this.showLoginForm();
                this.showLoginStatus('Logged out successfully.', 'success');
            }
        } catch (error) {
            console.error('Logout error:', error);
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
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ email })
            });
            
            const data = await response.json();
            
            if (response.ok) {
                this.showResetStatus('Reset link sent! Check your email.', 'success');
                if (data.reset_link) {
                    console.log('Reset link (for development):', data.reset_link);
                }
                setTimeout(() => {
                    closeResetModal();
                }, 3000);
            } else {
                this.showResetStatus(data.error || 'Request failed.', 'error');
            }
        } catch (error) {
            console.error('Reset request error:', error);
            this.showResetStatus('Network error. Please try again.', 'error');
        }
    }
    
    async handleUpload() {
        const formData = new FormData();
        
        const courseCode = document.getElementById('courseCode');
        const courseName = document.getElementById('courseName');
        const description = document.getElementById('description');
        const examType = document.getElementById('examType');
        const year = document.getElementById('year');
        const pdfFile = document.getElementById('pdfFile');
        
        // Validate
        if (!courseCode.value || !courseName.value || !examType.value || !year.value || !pdfFile.files[0]) {
            this.showStatus('Please fill in all required fields.', 'error');
            return;
        }
        
        // Validate year
        const yearNum = parseInt(year.value);
        if (isNaN(yearNum) || yearNum < 2000 || yearNum > 2030) {
            this.showStatus('Please enter a valid year (2000-2030).', 'error');
            return;
        }
        
        formData.append('course_code', courseCode.value);
        formData.append('course_name', courseName.value);
        formData.append('description', description.value);
        formData.append('exam_type', examType.value);
        formData.append('year', year.value);
        formData.append('pdf_file', pdfFile.files[0]);
        
        this.showStatus('Uploading... Please wait.', 'info');
        
        try {
            const response = await fetch('/api/admin/upload', {
                method: 'POST',
                body: formData
            });
            
            const data = await response.json();
            
            if (response.ok) {
                this.showStatus('✅ Course uploaded successfully!', 'success');
                this.uploadForm.reset();
                this.fileName.textContent = 'No file selected';
                this.loadCourses(); // Refresh course list
            } else {
                this.showStatus('❌ ' + (data.error || 'Upload failed. Please try again.'), 'error');
            }
        } catch (error) {
            console.error('Upload error:', error);
            this.showStatus('❌ Network error. Please check your connection.', 'error');
        }
    }
    
    async loadCourses() {
        try {
            const response = await fetch('/api/admin/courses');
            
            if (!response.ok) {
                if (response.status === 401) {
                    this.isAuthenticated = false;
                    this.showLoginForm();
                    return;
                }
                throw new Error('Failed to load courses');
            }
            
            const data = await response.json();
            this.renderCourses(data.courses);
            this.updateCount(data.courses.length);
        } catch (error) {
            console.error('Error loading courses:', error);
            this.courseList.innerHTML = `
                <div style="text-align: center; padding: 2rem; color: var(--gray);">
                    <i class="fas fa-exclamation-triangle" style="font-size: 2rem; margin-bottom: 1rem;"></i>
                    <p>Failed to load courses. Please refresh.</p>
                </div>
            `;
        }
    }
    
    renderCourses(courses) {
        this.courseList.innerHTML = '';
        
        if (courses.length === 0) {
            this.courseList.innerHTML = `
                <div style="text-align: center; padding: 2rem; color: var(--gray);">
                    <i class="fas fa-inbox" style="font-size: 2rem; margin-bottom: 1rem;"></i>
                    <p>No courses uploaded yet.</p>
                </div>
            `;
            return;
        }
        
        courses.forEach(course => {
            const item = this.createCourseItem(course);
            this.courseList.appendChild(item);
        });
    }
    
    createCourseItem(course) {
        const div = document.createElement('div');
        div.className = 'admin-course-item';
        div.dataset.id = course.id;
        
        const typeClass = course.exam_type.toLowerCase();
        
        div.innerHTML = `
            <div class="admin-course-info">
                <span class="admin-course-name">${this.escapeHtml(course.course_name)}</span>
                <span class="admin-course-code">${this.escapeHtml(course.course_code)}</span>
                <span class="admin-course-type ${typeClass}">${course.exam_type}</span>
                <span style="color: var(--gray); font-size: 0.9rem;">${course.year}</span>
                <a href="${course.pdf_url}" target="_blank" style="color: var(--primary); text-decoration: none; font-size: 0.9rem;">
                    <i class="fas fa-file-pdf"></i> PDF
                </a>
            </div>
            <div class="admin-course-actions">
                <button class="btn btn-danger btn-small delete-btn" data-id="${course.id}">
                    <i class="fas fa-trash"></i>
                </button>
            </div>
        `;
        
        // Add delete handler
        const deleteBtn = div.querySelector('.delete-btn');
        deleteBtn.addEventListener('click', () => this.handleDelete(course.id));
        
        return div;
    }
    
    async handleDelete(courseId) {
        if (!confirm('Are you sure you want to delete this course? This action cannot be undone.')) {
            return;
        }
        
        try {
            const response = await fetch(`/api/admin/course/${courseId}`, {
                method: 'DELETE'
            });
            
            if (response.status === 401) {
                this.isAuthenticated = false;
                this.showLoginForm();
                return;
            }
            
            const data = await response.json();
            
            if (response.ok) {
                this.showStatus('✅ Course deleted successfully!', 'success');
                this.loadCourses(); // Refresh list
            } else {
                this.showStatus('❌ ' + (data.error || 'Deletion failed.'), 'error');
            }
        } catch (error) {
            console.error('Delete error:', error);
            this.showStatus('❌ Network error. Please try again.', 'error');
        }
    }
    
    updateCount(count) {
        if (this.courseCount) {
            this.courseCount.textContent = `${count} course${count !== 1 ? 's' : ''}`;
        }
    }
    
    showAdminContent() {
        const loginOverlay = document.getElementById('loginOverlay');
        const adminContent = document.getElementById('adminContent');
        
        if (loginOverlay) loginOverlay.style.display = 'none';
        if (adminContent) adminContent.style.display = 'block';
    }
    
    showLoginForm() {
        const loginOverlay = document.getElementById('loginOverlay');
        const adminContent = document.getElementById('adminContent');
        
        if (loginOverlay) loginOverlay.style.display = 'flex';
        if (adminContent) adminContent.style.display = 'none';
    }
    
    showLoginStatus(message, type) {
        this.loginStatus.textContent = message;
        this.loginStatus.className = 'login-status';
        if (type) {
            this.loginStatus.classList.add(type);
        }
        this.loginStatus.style.display = 'block';
    }
    
    showStatus(message, type) {
        this.uploadStatus.textContent = message;
        this.uploadStatus.className = 'upload-status';
        if (type) {
            this.uploadStatus.classList.add(type);
        }
        this.uploadStatus.style.display = 'block';
        
        // Auto-hide after 5 seconds for success messages
        if (type === 'success') {
            setTimeout(() => {
                this.uploadStatus.style.display = 'none';
            }, 5000);
        }
    }
    
    showResetStatus(message, type) {
        this.resetStatus.textContent = message;
        this.resetStatus.className = 'reset-status';
        if (type) {
            this.resetStatus.classList.add(type);
        }
        this.resetStatus.style.display = 'block';
    }
    
    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
}

// Global functions for modal
function showResetForm() {
    document.getElementById('resetModal').style.display = 'flex';
}

function closeResetModal() {
    document.getElementById('resetModal').style.display = 'none';
    document.getElementById('resetStatus').className = 'reset-status';
    document.getElementById('resetStatus').textContent = '';
    document.getElementById('resetStatus').style.display = 'none';
}

function handleLogout() {
    if (window.adminDashboard) {
        window.adminDashboard.handleLogout();
    }
}

// Initialize dashboard
document.addEventListener('DOMContentLoaded', () => {
    window.adminDashboard = new AdminDashboard();
});

// Close modal when clicking outside
window.onclick = function(event) {
    const modal = document.getElementById('resetModal');
    if (event.target == modal) {
        closeResetModal();
    }
}
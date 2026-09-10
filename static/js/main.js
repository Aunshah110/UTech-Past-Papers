// Main JavaScript for Student Homepage

class CourseManager {
    constructor() {
        this.currentPage = 1;
        this.limit = 20;
        this.totalPages = 0;
        this.searchQuery = '';
        this.isSearching = false;
        this.courses = [];
        
        this.coursesGrid = document.getElementById('coursesGrid');
        this.searchInput = document.getElementById('searchInput');
        this.clearBtn = document.getElementById('clearSearchBtn');
        this.loadMoreBtn = document.getElementById('loadMoreBtn');
        this.loadingSpinner = document.getElementById('loadingSpinner');
        this.noResults = document.getElementById('noResults');
        this.resultCount = document.getElementById('resultCount');
        this.loadMoreContainer = document.getElementById('loadMoreContainer');
        
        this.init();
    }
    
    init() {
        this.loadCourses();
        this.setupEventListeners();
    }
    
    setupEventListeners() {
        // Search input with debounce
        let debounceTimer;
        this.searchInput.addEventListener('input', (e) => {
            clearTimeout(debounceTimer);
            debounceTimer = setTimeout(() => {
                this.handleSearch(e.target.value);
            }, 300);
        });
        
        // Clear search
        this.clearBtn.addEventListener('click', () => {
            this.searchInput.value = '';
            this.clearBtn.classList.remove('visible');
            this.handleSearch('');
        });
        
        // Load more
        this.loadMoreBtn.addEventListener('click', () => {
            this.currentPage++;
            this.loadCourses(false);
        });
    }
    
    async loadCourses(reset = true) {
        if (reset) {
            this.currentPage = 1;
            this.courses = [];
            this.coursesGrid.innerHTML = '';
            this.loadMoreContainer.style.display = 'none';
        }
        
        this.showLoading(true);
        
        try {
            const url = `/api/courses?page=${this.currentPage}&limit=${this.limit}`;
            const response = await fetch(url);
            const data = await response.json();
            
            if (data.error) {
                throw new Error(data.error);
            }
            
            this.totalPages = data.total_pages;
            this.courses = [...this.courses, ...data.courses];
            
            this.renderCourses(this.courses);
            this.updateLoadMoreButton();
            this.updateStats(this.courses.length, data.total);
            
            // Hide loading spinner
            this.showLoading(false);
            
        } catch (error) {
            console.error('Error loading courses:', error);
            this.showLoading(false);
            this.showError('Failed to load courses. Please try again.');
        }
    }
    
    async handleSearch(query) {
        this.searchQuery = query.trim();
        this.isSearching = this.searchQuery.length > 0;
        
        this.clearBtn.classList.toggle('visible', this.isSearching);
        
        if (!this.isSearching) {
            this.loadCourses(true);
            return;
        }
        
        this.showLoading(true);
        
        try {
            const url = `/api/search?q=${encodeURIComponent(this.searchQuery)}`;
            const response = await fetch(url);
            const data = await response.json();
            
            if (data.error) {
                throw new Error(data.error);
            }
            
            this.courses = data.courses;
            this.renderCourses(this.courses);
            
            this.loadMoreContainer.style.display = 'none';
            this.updateStats(this.courses.length);
            this.showLoading(false);
            
        } catch (error) {
            console.error('Search error:', error);
            this.showLoading(false);
            this.showError('Search failed. Please try again.');
        }
    }
    
    renderCourses(courses) {
        this.coursesGrid.innerHTML = '';
        
        if (courses.length === 0) {
            this.noResults.style.display = 'block';
            return;
        }
        
        this.noResults.style.display = 'none';
        
        courses.forEach((course, index) => {
            const card = this.createCourseCard(course, index);
            this.coursesGrid.appendChild(card);
        });
    }
    
    createCourseCard(course, index) {
        const div = document.createElement('div');
        div.className = 'course-card';
        div.style.animationDelay = `${index * 50}ms`;
        
        const examTypeBadge = this.getExamTypeBadge(course.exam_type);
        
        div.innerHTML = `
            <div class="course-card-header">
                <span class="course-card-code">${this.escapeHtml(course.course_code)}</span>
                <span class="course-card-type">${examTypeBadge}</span>
            </div>
            <h3 class="course-card-title">${this.escapeHtml(course.course_name)}</h3>
            <p class="course-card-description">${this.escapeHtml(course.description || 'No description available.')}</p>
            <div class="course-card-footer">
                <span class="course-card-year">📅 ${course.year}</span>
                <a href="/course/${course.id}" class="course-card-btn">
                    View Course →
                </a>
            </div>
        `;
        
        return div;
    }
    
    getExamTypeBadge(type) {
        const badges = {
            'Mid': '📝 Mid',
            'Final': '📚 Final',
            'Notes': '📓 Notes'
        };
        return badges[type] || type;
    }
    
    updateStats(displayed, total) {
        if (this.isSearching) {
            this.resultCount.textContent = `Showing ${displayed} results for "${this.searchQuery}"`;
        } else if (total) {
            this.resultCount.textContent = `Showing ${displayed} of ${total} courses`;
        } else {
            this.resultCount.textContent = `Showing ${displayed} courses`;
        }
    }
    
    updateLoadMoreButton() {
        if (!this.isSearching && this.currentPage < this.totalPages) {
            this.loadMoreContainer.style.display = 'block';
        } else {
            this.loadMoreContainer.style.display = 'none';
        }
    }
    
    showLoading(show) {
        this.loadingSpinner.style.display = show ? 'block' : 'none';
    }
    
    showError(message) {
        // Simple error handling - can be improved
        alert(message);
    }
    
    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
}

// Initialize the application
document.addEventListener('DOMContentLoaded', () => {
    new CourseManager();
});
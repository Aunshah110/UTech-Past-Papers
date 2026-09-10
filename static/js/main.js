// ============ Student Homepage Logic ============

// ---------- Cursor-tracked slide for hero titles ----------
function initSlideTitles() {
    const titles = document.querySelectorAll('.slide-title');

    titles.forEach((el) => {
        // Track pointer position over the text; underline follows the cursor.
        el.addEventListener('mousemove', (e) => {
            const rect = el.getBoundingClientRect();
            const x = e.clientX - rect.left;
            const pct = Math.max(0, Math.min(1, x / rect.width));

            // Slide width: minimum 12% of text, scaled to cursor position
            const minWidth = 12;                     // %
            const width = minWidth + (100 - minWidth) * pct;

            el.style.setProperty('--slide-left', '0%');
            el.style.setProperty('--slide-width', `${width}%`);
            el.style.setProperty('--slide-opacity', '1');
        });

        el.addEventListener('mouseenter', () => {
            el.style.setProperty('--slide-opacity', '1');
        });

        el.addEventListener('mouseleave', () => {
            // Fade out and reset
            el.style.setProperty('--slide-opacity', '0');
            setTimeout(() => {
                el.style.setProperty('--slide-width', '0%');
            }, 220);
        });
    });
}

// ---------- Course Manager ----------
class CourseManager {
    constructor() {
        this.page = 1;
        this.limit = 20;
        this.totalPages = 0;
        this.searchQuery = '';
        this.isSearching = false;
        this.allLoaded = [];

        this.grid         = document.getElementById('coursesGrid');
        this.searchInput  = document.getElementById('searchInput');
        this.clearBtn     = document.getElementById('clearSearchBtn');
        this.loadMoreBtn  = document.getElementById('loadMoreBtn');
        this.loadMoreWrap = document.getElementById('loadMoreContainer');
        this.spinner      = document.getElementById('loadingSpinner');
        this.noResults    = document.getElementById('noResults');
        this.stats        = document.getElementById('searchStats');

        this.init();
    }

    init() {
        this.loadCourses(true);
        this.bindEvents();
    }

    bindEvents() {
        let t;
        this.searchInput.addEventListener('input', (e) => {
            clearTimeout(t);
            t = setTimeout(() => this.handleSearch(e.target.value), 280);
        });

        this.clearBtn.addEventListener('click', () => {
            this.searchInput.value = '';
            this.handleSearch('');
        });

        this.loadMoreBtn.addEventListener('click', () => {
            this.page++;
            this.loadCourses(false);
        });
    }

    async loadCourses(reset) {
        if (reset) {
            this.page = 1;
            this.allLoaded = [];
            this.grid.innerHTML = '';
            this.loadMoreWrap.style.display = 'none';
        }

        this.setLoading(true);

        try {
            const res = await fetch(`/api/courses/grouped?page=${this.page}&limit=${this.limit}`);
            const data = await res.json();
            if (!res.ok) throw new Error(data.error || 'Failed to load');

            this.totalPages = data.total_pages || 1;
            this.allLoaded = this.allLoaded.concat(data.courses);

            this.render(this.allLoaded);
            this.updateStats(this.allLoaded.length, data.total);
            this.updateLoadMore();
        } catch (err) {
            console.error(err);
            this.showError('Could not load courses. Please try again.');
        } finally {
            this.setLoading(false);
        }
    }

    async handleSearch(rawQuery) {
        this.searchQuery = rawQuery.trim();
        this.isSearching = this.searchQuery.length > 0;
        this.clearBtn.classList.toggle('visible', this.isSearching);

        if (!this.isSearching) {
            this.loadCourses(true);
            return;
        }

        this.setLoading(true);
        this.loadMoreWrap.style.display = 'none';

        try {
            const res = await fetch(`/api/courses/grouped/search?q=${encodeURIComponent(this.searchQuery)}`);
            const data = await res.json();
            if (!res.ok) throw new Error(data.error || 'Search failed');

            this.render(data.courses);
            this.updateStats(data.courses.length);
        } catch (err) {
            console.error(err);
            this.showError('Search failed. Please try again.');
        } finally {
            this.setLoading(false);
        }
    }

    render(courses) {
        this.grid.innerHTML = '';
        if (!courses.length) {
            this.noResults.style.display = 'block';
            return;
        }
        this.noResults.style.display = 'none';

        courses.forEach((c, i) => {
            this.grid.appendChild(this.buildCard(c, i));
        });
    }

    buildCard(course, index) {
        const el = document.createElement('article');
        el.className = 'course-card';
        el.style.animationDelay = `${Math.min(index * 40, 400)}ms`;
        
        const name  = this.esc(course.course_name || 'Untitled Course');
        const code  = this.esc(course.course_code || '—');
        const desc  = this.esc(course.description || 'Study past papers, exams, and notes for this course.');
        
        // Robust number/year handling — works whether API returns int or string
        const rawCount = course.paper_count;
        const count = (rawCount === 0 || rawCount) ? Number(rawCount) : 0;
        const year  = course.latest_year ? course.latest_year : '—';
        
        el.innerHTML = `
            <div class="card-top">
                <span class="card-code">${code}</span>
            </div>
            <h3 class="card-title">${name}</h3>
            <p class="card-desc">${desc}</p>
        
            <div class="card-meta">
                <span class="meta-item" title="Total past papers">
                    <i class="fas fa-file-pdf"></i>
                    <span class="value">${count}</span>&nbsp;Paper${count === 1 ? '' : 's'}
                </span>
                <span class="meta-item" title="Latest year">
                    <i class="fas fa-calendar-alt"></i>
                    Latest:&nbsp;<span class="value">${year}</span>
                </span>
            </div>
        
            <div class="card-link-wrap">
                <a href="/course/${course.id}" class="card-link">
                    View Papers <i class="fas fa-arrow-right"></i>
                </a>
            </div>
        `;
        return el;
    }

    setLoading(on) {
        this.spinner.style.display = on ? 'block' : 'none';
    }

    updateStats(shown, total) {
        if (this.isSearching) {
            this.stats.textContent = `Showing ${shown} result${shown === 1 ? '' : 's'} for "${this.searchQuery}"`;
        } else if (total != null) {
            this.stats.textContent = `Showing ${shown} of ${total} course${total === 1 ? '' : 's'}`;
        } else {
            this.stats.textContent = `Showing ${shown} course${shown === 1 ? '' : 's'}`;
        }
    }

    updateLoadMore() {
        const more = !this.isSearching && this.page < this.totalPages;
        this.loadMoreWrap.style.display = more ? 'block' : 'none';
    }

    showError(msg) {
        this.noResults.style.display = 'block';
        this.noResults.querySelector('h3').textContent = 'Something went wrong';
        this.noResults.querySelector('p').textContent = msg;
    }

    esc(str) {
        const d = document.createElement('div');
        d.textContent = String(str);
        return d.innerHTML;
    }
}

document.addEventListener('DOMContentLoaded', () => {
    initSlideTitles();
    new CourseManager();
});
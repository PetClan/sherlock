// Sherlock - Dashboard JavaScript
// All functions at global scope for onclick handlers

// Global state
var state = {
    shop: null,
    currentScan: null,
    pollInterval: null,
    isScanning: false
};

// API helper
async function api(endpoint, options = {}) {
    const url = '/api/v1' + endpoint;
    const response = await fetch(url, {
        headers: {
            'Content-Type': 'application/json',
        },
        ...options,
    });

    if (!response.ok) {
        throw new Error('API error: ' + response.status);
    }

    return response.json();
}

// Show notification
function showNotification(message, type) {
    type = type || 'info';
    const container = document.getElementById('notifications');
    if (!container) return;

    const notification = document.createElement('div');
    notification.className = 'notification notification-' + type;
    notification.innerHTML =
        '<span>' + message + '</span>' +
        '<button class="notification-close" onclick="this.parentElement.remove()">&times;</button>';

    container.appendChild(notification);

    setTimeout(function () {
        if (notification.parentElement) {
            notification.remove();
        }
    }, 5000);
}

// Show error
function showError(message) {
    showNotification(message, 'error');
}

// Initialize app
function init() {
    const params = new URLSearchParams(window.location.search);
    state.shop = params.get('shop');

    if (!state.shop) {
        showError('No shop specified. Please install the app first.');
        return;
    }

    const shopNameEl = document.getElementById('shop-name');
    if (shopNameEl) {
        shopNameEl.textContent = state.shop;
    }

    loadDashboard();
}

// Hide progress banner helper
function hideProgressBanner() {
    const progressBanner = document.getElementById('scan-progress');
    if (progressBanner) {
        progressBanner.style.display = 'none';
        progressBanner.innerHTML = '';
    }
}

// Stop polling helper
function stopPolling() {
    if (state.pollInterval) {
        clearInterval(state.pollInterval);
        state.pollInterval = null;
    }
    state.isScanning = false;
}

// Load dashboard data
async function loadDashboard() {
    stopPolling();
    hideProgressBanner();

    try {
        const apps = await api('/apps/' + state.shop);
        const scanHistory = await api('/scan/history/' + state.shop + '?limit=5');
        let performance = null;
        try {
            performance = await api('/performance/' + state.shop + '/latest');
        } catch (e) {
            // Performance data may not exist
        }

        renderStats(apps, scanHistory, performance);
        renderRecentScans(scanHistory.scans || []);
        renderSuspectApps(apps);

        // Load site health status
        loadSiteHealth();

    } catch (error) {
        console.error('Dashboard load error:', error);
        showError('Failed to load dashboard. Please try again.');
    }
}

// Render stats cards
function renderStats(apps, scanHistory, performance) {
    const totalScans = scanHistory.total_scans || scanHistory.scans?.length || 0;

    const statsHtml =
        '<div class="grid grid-4">' +
        '<div class="card stat-card">' +
        '<div class="stat-value">' + (apps.total || 0) + '</div>' +
        '<div class="stat-label">Installed Apps</div>' +
        '</div>' +
        '<div class="card stat-card">' +
        '<div class="stat-value ' + (apps.suspect_count > 0 ? 'danger' : 'success') + '">' +
        (apps.suspect_count || 0) +
        '</div>' +
        '<div class="stat-label">Suspect Apps</div>' +
        '</div>' +
        '<div class="card stat-card">' +
        '<div class="stat-value ' + getScoreClass(performance?.performance_score) + '">' +
        (performance?.performance_score ? Math.round(performance.performance_score) : '—') +
        '</div>' +
        '<div class="stat-label">Performance Score</div>' +
        '</div>' +
        '<div class="card stat-card">' +
        '<div class="stat-value">' + totalScans + '</div>' +
        '<div class="stat-label">Scans Run</div>' +
        '</div>' +
        '</div>';

    document.getElementById('stats-container').innerHTML = statsHtml;
}

// Get score class for styling
function getScoreClass(score) {
    if (!score) return '';
    if (score >= 90) return 'success';
    if (score >= 50) return 'warning';
    return 'danger';
}

// Render recent scans
function renderRecentScans(scans) {
    const container = document.getElementById('recent-scans');

    if (!scans.length) {
        container.innerHTML =
            '<div class="empty-state">' +
            '<div class="empty-state-icon">🔍</div>' +
            '<h3>No scans yet</h3>' +
            '<p>Run your first diagnostic scan to find issues</p>' +
            '</div>';
        return;
    }

    let rows = '';
    scans.forEach(function (scan) {
        rows += '<tr onclick="viewScan(\'' + scan.diagnosis_id + '\')" style="cursor: pointer;">' +
            '<td>' +
            '<span class="scan-status">' +
            '<span class="scan-status-dot ' + scan.status + '"></span>' +
            capitalizeFirst(scan.status) +
            '</span>' +
            '</td>' +
            '<td><span class="badge badge-info">' + scan.scan_type + '</span></td>' +
            '<td>' + scan.issues_found + ' issues</td>' +
            '<td>' + formatDate(scan.started_at) + '</td>' +
            '<td class="text-right">' +
            '<button class="btn btn-sm btn-secondary" onclick="event.stopPropagation(); viewScan(\'' + scan.diagnosis_id + '\')">View</button>' +
            '</td>' +
            '</tr>';
    });

    container.innerHTML =
        '<div class="table-container">' +
        '<table>' +
        '<thead>' +
        '<tr>' +
        '<th>Status</th>' +
        '<th>Type</th>' +
        '<th>Issues</th>' +
        '<th>Date</th>' +
        '<th></th>' +
        '</tr>' +
        '</thead>' +
        '<tbody>' + rows + '</tbody>' +
        '</table>' +
        '</div>';
}

// Render suspect apps
function renderSuspectApps(apps) {
    const container = document.getElementById('suspect-apps');
    const suspectApps = apps.apps ? apps.apps.filter(function (app) { return app.is_suspect; }) : [];

    if (!suspectApps.length) {
        container.innerHTML =
            '<div class="empty-state">' +
            '<div class="empty-state-icon">✅</div>' +
            '<h3>No suspect apps</h3>' +
            '<p>All installed apps look healthy</p>' +
            '</div>';
        return;
    }

    let html = '<ul class="app-list">';
    suspectApps.slice(0, 5).forEach(function (app) {
        html += '<li class="app-item suspect">' +
            '<div class="app-info">' +
            '<span class="app-name">' + app.title + '</span>' +
            '<span class="app-reason">' + (app.suspect_reason || 'Flagged as potentially problematic') + '</span>' +
            '</div>' +
            '</li>';
    });
    html += '</ul>';

    container.innerHTML = html;
}

// Format date helper
function formatDate(dateString) {
    if (!dateString) return '—';
    const date = new Date(dateString);
    return date.toLocaleDateString('en-US', {
        month: 'short',
        day: 'numeric',
        hour: 'numeric',
        minute: '2-digit'
    });
}

// Capitalize first letter
function capitalizeFirst(str) {
    if (!str) return '';
    return str.charAt(0).toUpperCase() + str.slice(1);
}

// Start a scan
async function startScan(scanType) {
    if (state.isScanning) {
        showNotification('A scan is already in progress', 'warning');
        return;
    }

    state.isScanning = true;
    showScanProgress({ status: 'starting', scan_type: scanType });

    try {
        const result = await api('/scan/start', {
            method: 'POST',
            body: JSON.stringify({
                shop: state.shop,
                scan_type: scanType
            })
        });

        if (result.diagnosis_id) {
            state.currentScan = result.diagnosis_id;
            pollScanStatus(result.diagnosis_id);
        }
    } catch (error) {
        console.error('Scan start error:', error);
        showError('Failed to start scan: ' + error.message);
        state.isScanning = false;
        hideProgressBanner();
    }
}

// Poll scan status
function pollScanStatus(diagnosisId) {
    state.pollInterval = setInterval(async function () {
        try {
            const status = await api('/scan/status/' + diagnosisId);
            showScanProgress(status);

            if (status.status === 'completed' || status.status === 'failed') {
                stopPolling();
                if (status.status === 'completed') {
                    showNotification('Scan completed!', 'success');
                    loadDashboard();
                } else {
                    showError('Scan failed: ' + (status.error || 'Unknown error'));
                }
            }
        } catch (error) {
            console.error('Poll error:', error);
            stopPolling();
            showError('Lost connection to scan');
        }
    }, 2000);
}

// Show scan progress
function showScanProgress(scan) {
    const progressBanner = document.getElementById('scan-progress');
    progressBanner.style.display = 'block';

    const statusText = scan.status === 'starting' ? 'Starting scan...' :
        scan.status === 'in_progress' ? 'Scanning... ' + (scan.progress || 0) + '%' :
            scan.status === 'completed' ? 'Scan complete!' :
                'Scan ' + scan.status;

    progressBanner.innerHTML =
        '<div class="progress-banner">' +
        '<div class="progress-content">' +
        '<div class="spinner"></div>' +
        '<span>' + statusText + '</span>' +
        '</div>' +
        '<button class="btn btn-sm btn-secondary" onclick="stopPolling(); hideProgressBanner();">Cancel</button>' +
        '</div>';
}

// View scan details
async function viewScan(diagnosisId) {
    try {
        const report = await api('/scan/report/' + diagnosisId);
        renderScanReport(report);
    } catch (error) {
        console.error('View scan error:', error);
        showError('Failed to load scan report');
    }
}

// Render scan report
function renderScanReport(report) {
    const mainContent = document.getElementById('main-content');

    let issuesHtml = '';
    if (report.issues && report.issues.length > 0) {
        report.issues.forEach(function (issue) {
            const severityClass = issue.severity === 'high' ? 'danger' :
                issue.severity === 'medium' ? 'warning' : 'info';
            issuesHtml +=
                '<div class="issue-card ' + severityClass + '">' +
                '<div class="issue-header">' +
                '<span class="issue-severity badge badge-' + severityClass + '">' + issue.severity + '</span>' +
                '<span class="issue-type">' + issue.issue_type + '</span>' +
                '</div>' +
                '<div class="issue-body">' +
                '<p>' + issue.description + '</p>' +
                (issue.app_name ? '<p class="issue-app">App: ' + issue.app_name + '</p>' : '') +
                (issue.recommendation ? '<p class="issue-recommendation">💡 ' + issue.recommendation + '</p>' : '') +
                '</div>' +
                '</div>';
        });
    } else {
        issuesHtml = '<div class="empty-state"><div class="empty-state-icon">✅</div><h3>No issues found</h3></div>';
    }

    mainContent.innerHTML =
        '<div class="scan-report">' +
        '<div class="report-header">' +
        '<button class="btn btn-secondary" onclick="backToDashboard()">← Back to Dashboard</button>' +
        '<h2>Scan Report</h2>' +
        '</div>' +
        '<div class="report-summary card">' +
        '<div class="grid grid-3">' +
        '<div class="stat-card"><div class="stat-value">' + (report.issues_found || 0) + '</div><div class="stat-label">Issues Found</div></div>' +
        '<div class="stat-card"><div class="stat-value">' + (report.apps_scanned || 0) + '</div><div class="stat-label">Apps Scanned</div></div>' +
        '<div class="stat-card"><div class="stat-value">' + formatDate(report.completed_at) + '</div><div class="stat-label">Completed</div></div>' +
        '</div>' +
        '</div>' +
        '<div class="report-issues">' +
        '<h3>Issues</h3>' +
        issuesHtml +
        '</div>' +
        '</div>';
}

// Back to dashboard
function backToDashboard() {
    location.reload();
}

// View all apps
async function viewAllApps() {
    try {
        const appsData = await api('/apps/' + state.shop);
        renderAllApps(appsData);
    } catch (error) {
        console.error('View apps error:', error);
        showError('Failed to load apps');
    }
}

// Render all apps
function renderAllApps(appsData) {
    const mainContent = document.getElementById('main-content');

    let appsHtml = '';
    if (appsData.apps && appsData.apps.length > 0) {
        appsData.apps.forEach(function (app) {
            const statusClass = app.is_suspect ? 'suspect' : 'healthy';
            appsHtml +=
                '<div class="app-card ' + statusClass + '">' +
                '<div class="app-card-header">' +
                '<span class="app-name">' + app.title + '</span>' +
                (app.is_suspect ? '<span class="badge badge-danger">Suspect</span>' : '<span class="badge badge-success">Healthy</span>') +
                '</div>' +
                (app.suspect_reason ? '<p class="app-reason">' + app.suspect_reason + '</p>' : '') +
                '</div>';
        });
    } else {
        appsHtml = '<div class="empty-state"><div class="empty-state-icon">📦</div><h3>No apps installed</h3></div>';
    }

    mainContent.innerHTML =
        '<div class="all-apps">' +
        '<div class="report-header">' +
        '<button class="btn btn-secondary" onclick="backToDashboard()">← Back to Dashboard</button>' +
        '<h2>All Installed Apps (' + (appsData.total || 0) + ')</h2>' +
        '</div>' +
        '<div class="apps-grid">' + appsHtml + '</div>' +
        '</div>';
}

// Tab Navigation
function switchTab(tabName, el) {
    document.querySelectorAll('.tab-content').forEach(function (content) {
        content.classList.add('hidden');
    });
    document.querySelectorAll('.tab').forEach(function (tab) {
        tab.classList.remove('active');
    });

    const tabContent = document.getElementById('tab-' + tabName);
    if (tabContent) {
        tabContent.classList.remove('hidden');
    }

    if (el) {
        el.classList.add('active');
    }

    // Load data for specific tabs
    if (tabName === 'community') {
        loadMostReportedApps();
    }
}

// Check conflicts
async function checkConflicts() {
    const container = document.getElementById('conflicts-content');
    container.innerHTML = '<div class="loading"><div class="spinner"></div><p>Checking conflicts...</p></div>';

    try {
        const result = await api('/conflicts/check?shop=' + state.shop, { method: 'POST' });
        renderConflicts(result);
    } catch (error) {
        console.error('Check conflicts error:', error);
        showError('Failed to check conflicts');
        container.innerHTML =
            '<div class="empty-state">' +
            '<div class="empty-state-icon">❌</div>' +
            '<h3>Error</h3>' +
            '<p>Could not check for conflicts.</p>' +
            '</div>';
    }
}

// Render conflicts
function renderConflicts(data) {
    const container = document.getElementById('conflicts-content');

    if (!data.conflicts || data.conflicts.length === 0) {
        container.innerHTML =
            '<div class="empty-state">' +
            '<div class="empty-state-icon">✅</div>' +
            '<h3>No Conflicts Found</h3>' +
            '<p>Your installed apps appear to be compatible with each other.</p>' +
            '</div>';
        return;
    }

    let html = '<div class="conflicts-list">';
    data.conflicts.forEach(function (conflict) {
        html +=
            '<div class="conflict-card">' +
            '<div class="conflict-apps">' +
            '<span class="app-name">' + conflict.app1 + '</span>' +
            '<span class="conflict-icon">⚡</span>' +
            '<span class="app-name">' + conflict.app2 + '</span>' +
            '</div>' +
            '<p class="conflict-description">' + conflict.description + '</p>' +
            '</div>';
    });
    html += '</div>';

    container.innerHTML = html;
}

// Scan for orphan code
async function scanOrphanCode() {
    const container = document.getElementById('orphan-content');
    container.innerHTML = '<div class="loading"><div class="spinner"></div><p>Scanning for orphan code...</p></div>';

    try {
        const result = await api('/orphan/scan?shop=' + state.shop, { method: 'POST' });
        renderOrphanCode(result);
    } catch (error) {
        console.error('Orphan scan error:', error);
        showError('Failed to scan for orphan code');
        container.innerHTML =
            '<div class="empty-state">' +
            '<div class="empty-state-icon">❌</div>' +
            '<h3>Error</h3>' +
            '<p>Could not scan for orphan code.</p>' +
            '</div>';
    }
}

// Render orphan code results
function renderOrphanCode(data) {
    const container = document.getElementById('orphan-content');

    if (!data.orphans || data.orphans.length === 0) {
        container.innerHTML =
            '<div class="empty-state">' +
            '<div class="empty-state-icon">✅</div>' +
            '<h3>No Orphan Code Found</h3>' +
            '<p>Your theme appears clean of leftover app code.</p>' +
            '</div>';
        return;
    }

    let html = '<div class="orphan-list">';
    data.orphans.forEach(function (orphan) {
        html +=
            '<div class="orphan-card">' +
            '<div class="orphan-header">' +
            '<span class="orphan-file">' + orphan.file + '</span>' +
            '<span class="badge badge-warning">' + orphan.likely_app + '</span>' +
            '</div>' +
            '<p class="orphan-description">' + orphan.description + '</p>' +
            '</div>';
    });
    html += '</div>';

    container.innerHTML = html;
}

// Load timeline
async function loadTimeline() {
    const container = document.getElementById('timeline-content');
    container.innerHTML = '<div class="loading"><div class="spinner"></div><p>Loading timeline...</p></div>';

    try {
        const result = await api('/performance/' + state.shop + '/history');
        renderTimeline(result);
    } catch (error) {
        console.error('Timeline error:', error);
        container.innerHTML =
            '<div class="empty-state">' +
            '<div class="empty-state-icon">📈</div>' +
            '<h3>No Timeline Data</h3>' +
            '<p>Performance data will appear here after running scans.</p>' +
            '</div>';
    }
}

// Render timeline
function renderTimeline(data) {
    const container = document.getElementById('timeline-content');

    if (!data.history || data.history.length === 0) {
        container.innerHTML =
            '<div class="empty-state">' +
            '<div class="empty-state-icon">📈</div>' +
            '<h3>No Timeline Data</h3>' +
            '<p>Performance data will appear here after running scans.</p>' +
            '</div>';
        return;
    }

    let html = '<div class="timeline">';
    data.history.forEach(function (entry) {
        html +=
            '<div class="timeline-entry">' +
            '<div class="timeline-date">' + formatDate(entry.recorded_at) + '</div>' +
            '<div class="timeline-score">' +
            '<span class="score-value ' + getScoreClass(entry.performance_score) + '">' +
            Math.round(entry.performance_score) +
            '</span>' +
            '</div>' +
            (entry.event ? '<div class="timeline-event">' + entry.event + '</div>' : '') +
            '</div>';
    });
    html += '</div>';

    container.innerHTML = html;
}

// Load community insights
async function loadCommunityInsights() {
    const container = document.getElementById('community-content');
    container.innerHTML = '<div class="loading"><div class="spinner"></div><p>Loading community insights...</p></div>';

    try {
        const result = await api('/community/insights?shop=' + state.shop);
        renderCommunityInsights(result);
    } catch (error) {
        console.error('Community insights error:', error);
        container.innerHTML =
            '<div class="empty-state">' +
            '<div class="empty-state-icon">👥</div>' +
            '<h3>Community Insights</h3>' +
            '<p>No community data available for your installed apps.</p>' +
            '</div>';
    }
}

// Render community insights
function renderCommunityInsights(data) {
    const container = document.getElementById('community-content');

    if (!data.insights || data.insights.length === 0) {
        container.innerHTML =
            '<div class="empty-state">' +
            '<div class="empty-state-icon">👥</div>' +
            '<h3>No Issues Reported</h3>' +
            '<p>No community-reported issues for your installed apps.</p>' +
            '</div>';
        return;
    }

    let html = '<div class="insights-list">';
    data.insights.forEach(function (insight) {
        html +=
            '<div class="insight-card">' +
            '<div class="insight-header">' +
            '<span class="app-name">' + insight.app_name + '</span>' +
            '<span class="badge badge-' + (insight.severity === 'high' ? 'danger' : 'warning') + '">' +
            insight.report_count + ' reports</span>' +
            '</div>' +
            '<p class="insight-summary">' + insight.summary + '</p>' +
            '</div>';
    });
    html += '</div>';

    container.innerHTML = html;
}

// Open report modal
function openReportModal() {
    document.getElementById('report-modal').classList.remove('hidden');
}

// Close report modal
function closeReportModal() {
    document.getElementById('report-modal').classList.add('hidden');
    document.getElementById('report-results').classList.add('hidden');
    document.getElementById('report-results').innerHTML = '';
}

// Submit app report
async function submitAppReport() {
    const appName = document.getElementById('report-app-name').value.trim();
    const issueType = document.getElementById('report-issue-type').value;
    const when = document.getElementById('report-when').value;
    const doing = document.getElementById('report-doing').value;
    const otherApps = document.getElementById('report-other-apps').value.trim();
    const description = document.getElementById('report-description').value.trim();

    if (!appName || !issueType || !when || !doing) {
        showError('Please fill in all required fields');
        return;
    }

    const btn = document.getElementById('report-submit-btn');
    btn.disabled = true;
    btn.textContent = '🔍 Searching...';

    try {
        const result = await api('/reports/submit', {
            method: 'POST',
            body: JSON.stringify({
                shop: state.shop,
                app_name: appName,
                issue_type: issueType,
                when_started: when,
                what_doing: doing,
                other_apps: otherApps,
                description: description
            })
        });

        showReportResults(result);
    } catch (error) {
        console.error('Report submit error:', error);
        showReportError('Failed to submit report: ' + error.message);
    } finally {
        btn.disabled = false;
        btn.textContent = '🔍 Search & Report';
    }
}

// Show report results
function showReportResults(result) {
    const container = document.getElementById('report-results');
    container.classList.remove('hidden');

    let html = '<div class="report-results-content">';
    html += '<h3>✅ Report Submitted</h3>';

    if (result.reddit_results && result.reddit_results.length > 0) {
        html += '<h4>Related Reddit Discussions:</h4>';
        html += '<ul class="reddit-results">';
        result.reddit_results.forEach(function (post) {
            html += '<li><a href="' + post.url + '" target="_blank">' + post.title + '</a></li>';
        });
        html += '</ul>';
    }

    if (result.google_results && result.google_results.length > 0) {
        html += '<h4>Related Web Results:</h4>';
        html += '<ul class="google-results">';
        result.google_results.forEach(function (item) {
            html += '<li><a href="' + item.link + '" target="_blank">' + item.title + '</a></li>';
        });
        html += '</ul>';
    }

    html += '</div>';
    container.innerHTML = html;

    showNotification('Report submitted successfully!', 'success');
}

// Show report error
function showReportError(message) {
    const container = document.getElementById('report-results');
    container.classList.remove('hidden');
    container.innerHTML =
        '<div class="report-error">' +
        '<p>❌ ' + message + '</p>' +
        '</div>';
}

// Load most reported apps
async function loadMostReportedApps() {
    const container = document.getElementById('most-reported-apps');
    container.innerHTML = '<div class="loading"><div class="spinner"></div><p>Loading reported apps...</p></div>';

    try {
        const result = await api('/reports/most-reported');

        if (result.apps && result.apps.length > 0) {
            let html = '<div class="reported-apps-list">';
            result.apps.forEach(function (app, index) {
                html +=
                    '<div class="reported-app-card">' +
                    '<div class="reported-app-rank">#' + (index + 1) + '</div>' +
                    '<div class="reported-app-info">' +
                    '<span class="reported-app-name">' + app.app_name + '</span>' +
                    '<span class="reported-app-count">' + app.report_count + ' reports</span>' +
                    '</div>' +
                    '<div class="reported-app-issues">' +
                    (app.top_issues ? app.top_issues.join(', ') : 'Various issues') +
                    '</div>' +
                    '</div>';
            });
            html += '</div>';
            container.innerHTML = html;
        } else {
            container.innerHTML =
                '<div class="empty-state">' +
                '<div class="empty-state-icon">📊</div>' +
                '<h3>No Reports Yet</h3>' +
                '<p>Be the first to report a problematic app!</p>' +
                '</div>';
        }
    } catch (error) {
        console.error('Error loading reported apps:', error);
        container.innerHTML =
            '<div class="empty-state">' +
            '<div class="empty-state-icon">❌</div>' +
            '<h3>Error Loading</h3>' +
            '<p>Could not load reported apps. Please try again.</p>' +
            '</div>';
    }
}

// ==================== Site Health Functions ====================

async function loadSiteHealth() {
    const container = document.getElementById('site-health-content');

    try {
        const response = await fetch('/api/v1/monitoring/latest/' + state.shop);
        const data = await response.json();

        if (data.has_scan && data.scan) {
            renderSiteHealth(data.scan);
        } else {
            container.innerHTML =
                '<div class="site-health-empty">' +
                '<div class="site-health-empty-icon">🛡️</div>' +
                '<h4>No Health Scan Yet</h4>' +
                '<p>Run your first health scan to monitor theme changes, script injections, and CSS risks.</p>' +
                '</div>';
        }
    } catch (error) {
        console.error('Error loading site health:', error);
        container.innerHTML =
            '<div class="site-health-empty">' +
            '<div class="site-health-empty-icon">⚠️</div>' +
            '<h4>Could not load health status</h4>' +
            '<p>Try running a new health scan.</p>' +
            '</div>';
    }
}

function renderSiteHealth(scan) {
    const container = document.getElementById('site-health-content');

    // Determine risk styling
    var riskClass = 'low';
    var riskIcon = '✅';
    if (scan.risk_level === 'high') {
        riskClass = 'high';
        riskIcon = '🚨';
    } else if (scan.risk_level === 'medium') {
        riskClass = 'medium';
        riskIcon = '⚡';
    }

    // Build risk reasons list
    var reasonsHtml = '';
    if (scan.risk_reasons && scan.risk_reasons.length > 0) {
        reasonsHtml = '<div class="site-health-reasons"><ul>';
        scan.risk_reasons.forEach(function (reason) {
            reasonsHtml += '<li>⚠️ ' + escapeHtml(reason) + '</li>';
        });
        reasonsHtml += '</ul></div>';
    }

    container.innerHTML =
        '<div class="site-health-content">' +
        '<div class="site-health-status">' +
        '<div class="site-health-risk ' + riskClass + '">' +
        '<span>' + riskIcon + '</span>' +
        '<span>' + (scan.risk_level || 'low').toUpperCase() + ' RISK</span>' +
        '</div>' +
        '<div class="site-health-time">Last scan: ' + formatDate(scan.scan_date) + '</div>' +
        '</div>' +
        reasonsHtml +
        '<div class="site-health-stats">' +
        '<div class="site-health-stat">' +
        '<div class="site-health-stat-value">' + (scan.files_total || 0) + '</div>' +
        '<div class="site-health-stat-label">Total Files</div>' +
        '</div>' +
        '<div class="site-health-stat">' +
        '<div class="site-health-stat-value ' + (scan.files_new > 0 ? 'warning' : '') + '">' + (scan.files_new || 0) + '</div>' +
        '<div class="site-health-stat-label">New Files</div>' +
        '</div>' +
        '<div class="site-health-stat">' +
        '<div class="site-health-stat-value ' + (scan.files_changed > 0 ? 'warning' : '') + '">' + (scan.files_changed || 0) + '</div>' +
        '<div class="site-health-stat-label">Changed</div>' +
        '</div>' +
        '<div class="site-health-stat">' +
        '<div class="site-health-stat-value ' + (scan.css_issues_found > 0 ? 'danger' : '') + '">' + (scan.css_issues_found || 0) + '</div>' +
        '<div class="site-health-stat-label">CSS Issues</div>' +
        '</div>' +
        '<div class="site-health-stat">' +
        '<div class="site-health-stat-value">' + (scan.scripts_total || 0) + '</div>' +
        '<div class="site-health-stat-label">Scripts</div>' +
        '</div>' +
        '</div>' +
        '</div>';
}

async function runMonitoringScan() {
    const btn = document.getElementById('monitoring-scan-btn');
    btn.classList.add('loading');
    btn.textContent = 'Scanning...';
    btn.disabled = true;

    const healthContainer = document.getElementById('site-health-content');
    healthContainer.innerHTML =
        '<div class="scan-progress-indicator">' +
        '<div class="scan-progress-spinner"></div>' +
        '<h3>🔍 Scanning Your Theme...</h3>' +
        '<p>Analyzing theme files, script tags, and CSS for potential conflicts.</p>' +
        '<p class="scan-progress-note">This typically takes 30-60 seconds depending on theme size.</p>' +
        '</div>';

    try {
        const response = await fetch('/api/v1/monitoring/scan/' + state.shop, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' }
        });

        const result = await response.json();

        if (response.ok && result.success) {
            renderSiteHealth(result);
            showNotification('Health scan completed!', 'success');
        } else {
            throw new Error(result.detail || 'Scan failed');
        }
    } catch (error) {
        console.error('Health scan error:', error);
        healthContainer.innerHTML =
            '<div class="site-health-empty">' +
            '<div class="site-health-empty-icon">❌</div>' +
            '<h4>Scan Failed</h4>' +
            '<p>' + error.message + '</p>' +
            '</div>';
        showNotification('Health scan failed: ' + error.message, 'error');
    } finally {
        btn.classList.remove('loading');
        btn.textContent = '🔍 Run Health Scan';
        btn.disabled = false;
    }
}

// ==================== Utility Functions ====================

function truncateUrl(url) {
    if (!url) return '';
    if (url.length > 60) {
        return url.substring(0, 30) + '...' + url.substring(url.length - 25);
    }
    return url;
}

function escapeHtml(text) {
    if (!text) return '';
    var div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// Initialize on DOM ready
document.addEventListener('DOMContentLoaded', init);
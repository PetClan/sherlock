// Sherlock - Dashboard JavaScript
// Detective Theme Dashboard - All functions at global scope

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

        // Load site health / protection status
        loadSiteHealth();
        // Load diagnosis for alert banner
        loadDiagnosis();

    } catch (error) {
        console.error('Dashboard load error:', error);
        showError('Failed to load dashboard. Please try again.');
    }
}

// Render stats cards
function renderStats(apps, scanHistory, performance) {
    const statsHtml =
        '<div class="grid grid-3">' +
        '<div class="stat-card">' +
        '<div class="stat-value">' + (apps.total || 0) + '</div>' +
        '<div class="stat-label">Installed Apps</div>' +
        '</div>' +
        '<div class="stat-card">' +
        '<div class="stat-value ' + (apps.suspect_count > 0 ? 'danger' : 'success') + '">' +
        (apps.suspect_count || 0) +
        '</div>' +
        '<div class="stat-label">Suspect Apps</div>' +
        '</div>' +
        '<div class="stat-card">' +
        '<div class="stat-value ' + getScoreClass(performance?.performance_score) + '">' +
        (performance?.performance_score ? Math.round(performance.performance_score) : '—') +
        '</div>' +
        '<div class="stat-label">Performance Score</div>' +
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
            '<h3>No investigations yet</h3>' +
            '<p>Run your first scan to start investigating</p>' +
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
            '<h3>All clear!</h3>' +
            '<p>No suspect apps detected. Your store looks healthy.</p>' +
            '</div>';
        return;
    }

    let html = '<ul class="app-list">';
    suspectApps.slice(0, 5).forEach(function (app) {
        html += '<li class="app-item suspect">' +
            '<div class="app-info">' +
            '<span class="app-name">' + escapeHtml(app.title) + '</span>' +
            '<span class="app-reason">' + escapeHtml(app.suspect_reason || 'Flagged as potentially problematic') + '</span>' +
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

// ==================== SITE HEALTH / PROTECTION STATUS ====================

async function loadSiteHealth() {
    const container = document.getElementById('protection-body');

    try {
        const response = await fetch('/api/v1/monitoring/latest/' + state.shop);
        const data = await response.json();

        if (data.has_scan && data.scan) {
            renderProtectionStatus(data.scan);
        } else {
            container.innerHTML =
                '<div class="empty-state">' +
                '<div class="empty-state-icon">🕵️</div>' +
                '<h3>No Investigation Yet</h3>' +
                '<p>Run your first investigation to see your store\'s protection status.</p>' +
                '</div>';

            
        }
    } catch (error) {
        console.error('Error loading site health:', error);
        container.innerHTML =
            '<div class="empty-state">' +
            '<div class="empty-state-icon">⚠️</div>' +
            '<h3>Could not load protection status</h3>' +
            '<p>Click "Run Investigation" to scan your store.</p>' +
            '</div>';
    }
}

function renderProtectionStatus(scan) {
    const container = document.getElementById('protection-body');

    // Determine risk styling and messages
    var riskClass = 'low';
    var riskIcon = '✅';
    var riskText = 'LOW RISK';
    var statusMessage = 'Your store is protected. No suspicious activity detected.';
    var detectiveQuote = '"Elementary, my dear merchant. All is well."';

    if (scan.risk_level === 'high') {
        riskClass = 'high';
        riskIcon = '🚨';
        riskText = 'HIGH RISK';
        statusMessage = 'Sherlock has detected issues that need your attention.';
        detectiveQuote = '"The game is afoot! Immediate action recommended."';
    } else if (scan.risk_level === 'medium') {
        riskClass = 'medium';
        riskIcon = '⚠️';
        riskText = 'MEDIUM RISK';
        statusMessage = 'Some potential issues detected. Review recommended.';
        detectiveQuote = '"There are curious elements here worth investigating."';
    }

    // Build risk warnings HTML
    var warningsHtml = '';
    if (scan.risk_reasons && scan.risk_reasons.length > 0) {
        warningsHtml = '<div class="risk-warnings">';
        scan.risk_reasons.forEach(function (reason) {
            var warningClass = reason.toLowerCase().includes('high') ? 'high' : '';
            warningsHtml += '<div class="risk-warning-item ' + warningClass + '">⚠️ ' + escapeHtml(reason) + '</div>';
        });
        warningsHtml += '</div>';
    }

    container.innerHTML =
        '<div class="status-banner">' +
        '<div class="status-badge ' + riskClass + '">' +
        '<span class="status-icon">' + riskIcon + '</span>' +
        '<span>' + riskText + '</span>' +
        '</div>' +
        '<div class="status-meta">Last scan: ' + formatDate(scan.scan_date) + '</div>' +
        '</div>' +
        '<div class="status-message">' +
        '<p>' + statusMessage + '</p>' +
        '<p class="detective-quote">' + detectiveQuote + '</p>' +
        '</div>' +
        warningsHtml +
        '<div class="protection-stats">' +
        '<div class="protection-stat" onclick="showProtectionStat(\'totalfiles\')" style="cursor: pointer;">' +
        '<div class="protection-stat-value">' + (scan.files_total || 0) + '</div>' +
        '<div class="protection-stat-label">Total Files</div>' +
        '</div>' +
        '<div class="protection-stat" onclick="showProtectionStat(\'newfiles\')" style="cursor: pointer;">' +
        '<div class="protection-stat-value ' + (scan.files_new > 0 ? 'warning' : '') + '">' + (scan.files_new || 0) + '</div>' +
        '<div class="protection-stat-label">New Files</div>' +
        '</div>' +
        '<div class="protection-stat" onclick="showProtectionStat(\'changed\')" style="cursor: pointer;">' +
        '<div class="protection-stat-value ' + (scan.files_changed > 0 ? 'warning' : '') + '">' + (scan.files_changed || 0) + '</div>' +
        '<div class="protection-stat-label">Changed</div>' +
        '</div>' +
        '<div class="protection-stat" onclick="showProtectionStat(\'cssissues\')" style="cursor: pointer;">' +
        '<div class="protection-stat-value ' + (scan.css_issues_found > 0 ? 'danger' : '') + '">' + (scan.css_issues_found || 0) + '</div>' +
        '<div class="protection-stat-label">CSS Issues</div>' +
        '</div>' +
        '<div class="protection-stat" onclick="showProtectionStat(\'scripts\')" style="cursor: pointer;">' +
        '<div class="protection-stat-value">' + (scan.scripts_total || 0) + '</div>' +
        '<div class="protection-stat-label">Scripts</div>' +
        '</div>' +
        '</div>';
}


async function runMonitoringScan() {
    const btn = document.getElementById('monitoring-scan-btn');
    btn.classList.add('loading');
    btn.textContent = 'Investigating...';
    btn.disabled = true;

    const container = document.getElementById('protection-body');
    container.innerHTML =
        '<div class="scan-progress-indicator">' +
        '<div class="scan-progress-spinner"></div>' +
        '<h3>🔍 Investigation in Progress...</h3>' +
        '<p>Sherlock is analyzing your theme files, script tags, and CSS for potential issues.</p>' +
        '<p class="scan-progress-note">This typically takes 30-60 seconds depending on theme size.</p>' +
        '</div>';

    try {
        const response = await fetch('/api/v1/monitoring/scan/' + state.shop, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' }
        });

        const result = await response.json();

        if (response.ok && result.success) {
            renderProtectionStatus(result);
            updateCaseFiles(result);
            showNotification('Investigation complete!', 'success');
        } else {
            throw new Error(result.detail || 'Investigation failed');
        }
    } catch (error) {
        console.error('Investigation error:', error);
        container.innerHTML =
            '<div class="empty-state">' +
            '<div class="empty-state-icon">❌</div>' +
            '<h3>Investigation Failed</h3>' +
            '<p>' + escapeHtml(error.message) + '</p>' +
            '</div>';
        showNotification('Investigation failed: ' + error.message, 'error');
    } finally {
        btn.classList.remove('loading');
        btn.textContent = '🔍 Run Investigation';
        btn.disabled = false;
    }
}

async function runMonitoringScanSilent() {
    try {
        await fetch('/api/v1/monitoring/scan/' + state.shop, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' }
        });
    } catch (error) {
        console.error('Silent monitoring scan error:', error);
    }
}

// ==================== SCAN FUNCTIONS ====================

async function startScan(scanType) {
    if (state.isScanning) {
        showNotification('An investigation is already in progress', 'warning');
        return;
    }

    state.isScanning = true;
    incrementScanCount();
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
        showError('Failed to start investigation: ' + error.message);
        state.isScanning = false;
        hideProgressBanner();
    }
}

function pollScanStatus(diagnosisId) {
    state.pollInterval = setInterval(async function () {
        try {
            const status = await api('/scan/' + diagnosisId);
            showScanProgress(status);

            if (status.status === 'completed' || status.status === 'failed') {
                stopPolling();
                if (status.status === 'completed') {
                    // Also run monitoring scan to update Store Protection Status
                    await runMonitoringScanSilent();
                    showNotification('Investigation completed!', 'success');
                    loadDashboard();
                } else {
                    showError('Investigation failed: ' + (status.error || 'Unknown error'));
                }
            }    
        } catch (error) {
            console.error('Poll error:', error);
            stopPolling();
            showError('Lost connection to investigation');
        }
    }, 2000);
}

function showScanProgress(scan) {
    const progressBanner = document.getElementById('scan-progress');
    progressBanner.style.display = 'block';

    const statusText = scan.status === 'starting' ? 'Starting investigation...' :
        scan.status === 'in_progress' ? 'Investigating... ' + (scan.progress || 0) + '%' :
            scan.status === 'completed' ? 'Investigation complete!' :
                'Investigation ' + scan.status;

    progressBanner.innerHTML =
        '<div class="progress-banner">' +
        '<div class="progress-content">' +
        '<div class="spinner"></div>' +
        '<span>' + statusText + '</span>' +
        '</div>' +
        '<button class="btn btn-sm btn-secondary" onclick="stopPolling(); hideProgressBanner();">Cancel</button>' +
        '</div>';
}

async function viewScan(diagnosisId) {
    try {
        const report = await api('/scan/' + diagnosisId + '/report');
        renderScanReport(report);
    } catch (error) {
        console.error('View scan error:', error);
        showError('Failed to load investigation report');
    }
}

function renderScanReport(report) {
    const mainContent = document.getElementById('main-content');

    let issuesHtml = '';
    if (report.issues && report.issues.length > 0) {
        report.issues.forEach(function (issue) {
            const severityClass = issue.severity === 'high' ? 'danger' :
                issue.severity === 'medium' ? 'warning' : 'info';
            issuesHtml +=
                '<div class="card" style="margin-bottom: 12px; border-left: 4px solid var(--' + (severityClass === 'danger' ? 'crimson' : severityClass === 'warning' ? 'amber' : 'gold') + '-500);">' +
                '<div class="card-body">' +
                '<div style="display: flex; align-items: center; gap: 10px; margin-bottom: 8px;">' +
                '<span class="badge badge-' + severityClass + '">' + issue.severity + '</span>' +
                '<strong>' + escapeHtml(issue.issue_type) + '</strong>' +
                '</div>' +
                '<p style="margin-bottom: 8px;">' + escapeHtml(issue.description) + '</p>' +
                (issue.app_name ? '<p style="color: var(--slate-400); font-size: 13px;">App: ' + escapeHtml(issue.app_name) + '</p>' : '') +
                (issue.recommendation ? '<p style="color: var(--gold-400); font-size: 13px;">💡 ' + escapeHtml(issue.recommendation) + '</p>' : '') +
                '</div>' +
                '</div>';
        });
    } else {
        issuesHtml = '<div class="empty-state"><div class="empty-state-icon">✅</div><h3>No issues found</h3><p>Your store passed all checks.</p></div>';
    }

    mainContent.innerHTML =
        '<div style="padding: 24px;">' +
        '<button class="btn btn-secondary" onclick="backToDashboard()" style="margin-bottom: 20px;">← Back to Dashboard</button>' +
        '<h2 style="font-family: var(--font-display); margin-bottom: 24px;">📋 Investigation Report</h2>' +
        '<div class="grid grid-3" style="margin-bottom: 24px;">' +
        '<div class="stat-card"><div class="stat-value">' + (report.issues_found || 0) + '</div><div class="stat-label">Issues Found</div></div>' +
        '<div class="stat-card"><div class="stat-value">' + (report.apps_scanned || 0) + '</div><div class="stat-label">Apps Analyzed</div></div>' +
        '<div class="stat-card"><div class="stat-value">' + formatDate(report.completed_at) + '</div><div class="stat-label">Completed</div></div>' +
        '</div>' +
        '<h3 style="margin-bottom: 16px;">Findings</h3>' +
        issuesHtml +
        '</div>';
}

function backToDashboard() {
    location.reload();
}

// ==================== VIEW ALL APPS ====================

async function viewAllApps() {
    try {
        const appsData = await api('/apps/' + state.shop);
        renderAllApps(appsData);
    } catch (error) {
        console.error('View apps error:', error);
        showError('Failed to load apps');
    }
}

function renderAllApps(appsData) {
    const mainContent = document.getElementById('main-content');

    let appsHtml = '';
    if (appsData.apps && appsData.apps.length > 0) {
        appsHtml = '<div class="grid grid-2">';
        appsData.apps.forEach(function (app) {
            const statusClass = app.is_suspect ? 'danger' : 'success';
            appsHtml +=
                '<div class="card">' +
                '<div class="card-body">' +
                '<div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">' +
                '<strong>' + escapeHtml(app.title) + '</strong>' +
                '<span class="badge badge-' + statusClass + '">' + (app.is_suspect ? 'Suspect' : 'Healthy') + '</span>' +
                '</div>' +
                (app.suspect_reason ? '<p style="color: var(--crimson-400); font-size: 13px;">' + escapeHtml(app.suspect_reason) + '</p>' : '') +
                '</div>' +
                '</div>';
        });
        appsHtml += '</div>';
    } else {
        appsHtml = '<div class="empty-state"><div class="empty-state-icon">📦</div><h3>No apps installed</h3></div>';
    }

    mainContent.innerHTML =
        '<div style="padding: 24px;">' +
        '<button class="btn btn-secondary" onclick="backToDashboard()" style="margin-bottom: 20px;">← Back to Dashboard</button>' +
        '<h2 style="font-family: var(--font-display); margin-bottom: 24px;">📦 All Installed Apps (' + (appsData.total || 0) + ')</h2>' +
        appsHtml +
        '</div>';
}

// ==================== TAB NAVIGATION ====================

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

// ==================== CONFLICTS TAB ====================

async function checkConflicts() {
    const container = document.getElementById('conflicts-content');
    container.innerHTML = '<div class="loading"><div class="spinner"></div><p>Checking for conflicts...</p></div>';

    try {
        const result = await api('/conflicts/check?shop=' + state.shop, { method: 'POST' });
        renderConflicts(result);
    } catch (error) {
        console.error('Check conflicts error:', error);
        container.innerHTML =
            '<div class="empty-state">' +
            '<div class="empty-state-icon">❌</div>' +
            '<h3>Error</h3>' +
            '<p>Could not check for conflicts.</p>' +
            '</div>';
    }
}

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

    let html = '';
    data.conflicts.forEach(function (conflict) {
        html +=
            '<div class="card" style="margin-bottom: 12px;">' +
            '<div class="card-body">' +
            '<div style="display: flex; align-items: center; gap: 8px; margin-bottom: 8px;">' +
            '<strong>' + escapeHtml(conflict.app1) + '</strong>' +
            '<span>⚡</span>' +
            '<strong>' + escapeHtml(conflict.app2) + '</strong>' +
            '</div>' +
            '<p style="color: var(--slate-400);">' + escapeHtml(conflict.description) + '</p>' +
            '</div>' +
            '</div>';
    });

    container.innerHTML = html;
}

// ==================== ORPHAN CODE TAB ====================

async function scanOrphanCode() {
    const container = document.getElementById('orphan-content');
    container.innerHTML = '<div class="loading"><div class="spinner"></div><p>Scanning for orphan code...</p></div>';

    try {
        const result = await api('/orphan/scan?shop=' + state.shop, { method: 'POST' });
        renderOrphanCode(result);
    } catch (error) {
        console.error('Orphan scan error:', error);
        container.innerHTML =
            '<div class="empty-state">' +
            '<div class="empty-state-icon">❌</div>' +
            '<h3>Error</h3>' +
            '<p>Could not scan for orphan code.</p>' +
            '</div>';
    }
}

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

    let html = '';
    data.orphans.forEach(function (orphan) {
        html +=
            '<div class="card" style="margin-bottom: 12px;">' +
            '<div class="card-body">' +
            '<div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">' +
            '<code>' + escapeHtml(orphan.file) + '</code>' +
            '<span class="badge badge-warning">' + escapeHtml(orphan.likely_app) + '</span>' +
            '</div>' +
            '<p style="color: var(--slate-400);">' + escapeHtml(orphan.description) + '</p>' +
            '</div>' +
            '</div>';
    });

    container.innerHTML = html;
}

// ==================== TIMELINE TAB ====================

async function loadTimeline() {
    const container = document.getElementById('timeline-content');
    container.innerHTML = '<div class="loading"><div class="spinner"></div><p>Loading timeline...</p></div>';

    try {
        const result = await api('/performance/' + state.shop);
        renderTimeline(result);
    } catch (error) {
        console.error('Timeline error:', error);
        container.innerHTML =
            '<div class="empty-state">' +
            '<div class="empty-state-icon">📈</div>' +
            '<h3>No Timeline Data</h3>' +
            '<p>Performance data will appear here after running investigations.</p>' +
            '</div>';
    }
}

function renderTimeline(data) {
    const container = document.getElementById('timeline-content');

    if (!data.history || data.history.length === 0) {
        container.innerHTML =
            '<div class="empty-state">' +
            '<div class="empty-state-icon">📈</div>' +
            '<h3>No Timeline Data</h3>' +
            '<p>Performance data will appear here after running investigations.</p>' +
            '</div>';
        return;
    }

    let html = '';
    data.history.forEach(function (entry) {
        html +=
            '<div class="card" style="margin-bottom: 12px;">' +
            '<div class="card-body">' +
            '<div style="display: flex; justify-content: space-between; align-items: center;">' +
            '<span>' + formatDate(entry.recorded_at) + '</span>' +
            '<span class="stat-value ' + getScoreClass(entry.performance_score) + '" style="font-size: 24px;">' + Math.round(entry.performance_score) + '</span>' +
            '</div>' +
            (entry.event ? '<p style="color: var(--slate-400); margin-top: 8px;">' + escapeHtml(entry.event) + '</p>' : '') +
            '</div>' +
            '</div>';
    });

    container.innerHTML = html;
}

// ==================== COMMUNITY TAB ====================

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

    let html = '';
    data.insights.forEach(function (insight) {
        html +=
            '<div class="card" style="margin-bottom: 12px;">' +
            '<div class="card-body">' +
            '<div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">' +
            '<strong>' + escapeHtml(insight.app_name) + '</strong>' +
            '<span class="badge badge-' + (insight.severity === 'high' ? 'danger' : 'warning') + '">' + insight.report_count + ' reports</span>' +
            '</div>' +
            '<p style="color: var(--slate-400);">' + escapeHtml(insight.summary) + '</p>' +
            '</div>' +
            '</div>';
    });

    container.innerHTML = html;
}

async function loadMostReportedApps() {
    const container = document.getElementById('most-reported-apps');
    container.innerHTML = '<div class="loading"><div class="spinner"></div><p>Loading reported apps...</p></div>';

    try {
        const result = await api('/reports/most-reported');

        if (result.apps && result.apps.length > 0) {
            let html = '';
            result.apps.forEach(function (app, index) {
                html +=
                    '<div class="card" style="margin-bottom: 12px;">' +
                    '<div class="card-body">' +
                    '<div style="display: flex; align-items: center; gap: 12px;">' +
                    '<span style="font-size: 24px; font-weight: bold; color: var(--gold-400);">#' + (index + 1) + '</span>' +
                    '<div style="flex: 1;">' +
                    '<strong>' + escapeHtml(app.app_name) + '</strong>' +
                    '<p style="color: var(--slate-400); font-size: 13px; margin-top: 4px;">' + app.report_count + ' reports · ' + (app.top_issues ? app.top_issues.join(', ') : 'Various issues') + '</p>' +
                    '</div>' +
                    '</div>' +
                    '</div>' +
                    '</div>';
            });
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
            '<p>Could not load reported apps.</p>' +
            '</div>';
    }
}

// ==================== DIAGNOSIS ALERT ====================

async function loadDiagnosis() {
    try {
        const diagnosis = await api('/scan/store-diagnosis/' + state.shop);
        renderDiagnosisAlert(diagnosis);
    } catch (error) {
        console.error('Diagnosis load error:', error);
        // Don't show error to user - just hide the alert
        document.getElementById('diagnosis-alert').classList.add('hidden');
    }
}

function renderDiagnosisAlert(diagnosis) {
    const container = document.getElementById('diagnosis-alert');

    // If healthy, hide the alert
    if (diagnosis.status === 'healthy' || diagnosis.status === 'unknown') {
        container.classList.add('hidden');
        return;
    }

    // Show alert for issues
    container.classList.remove('hidden');

    const issueCount = diagnosis.issue_count || 0;
    const suspect = diagnosis.primary_suspect;
    const actions = diagnosis.recommended_actions || [];

    // Determine alert severity
    let alertClass = 'alert-warning';
    let icon = '⚠️';
    if (suspect && suspect.confidence >= 70) {
        alertClass = 'alert-danger';
        icon = '🚨';
    }

    container.className = 'diagnosis-alert ' + alertClass;

    let html = '<div class="diagnosis-alert-header">' +
        '<span class="diagnosis-alert-icon">' + icon + '</span>' +
        '<div>' +
        '<h3 class="diagnosis-alert-title">Sherlock Found ' + issueCount + ' Issue' + (issueCount !== 1 ? 's' : '') + '</h3>' +
        '<p class="diagnosis-alert-subtitle">Here\'s what we know and what you can do about it</p>' +
        '</div>' +
        '</div>';

    // Show primary suspect if found
    if (suspect) {
        const confidenceClass = suspect.confidence >= 80 ? 'very-likely' :
            suspect.confidence >= 60 ? 'likely' : 'possibly';

        html += '<div class="diagnosis-suspect">' +
            '<div class="diagnosis-suspect-header">' +
            '<span class="diagnosis-suspect-name">🎯 ' + escapeHtml(suspect.app_name) + '</span>' +
            '<span class="diagnosis-confidence ' + confidenceClass + '">' + escapeHtml(suspect.confidence_label) + '</span>' +
            '</div>' +
            '<p class="diagnosis-suspect-message">' + escapeHtml(suspect.message) + '</p>' +
            '</div>';
    }

    // Show recommended actions
    if (actions.length > 0) {
        html += '<div class="diagnosis-actions">' +
            '<div class="diagnosis-actions-title">What to do next:</div>';

        actions.forEach(function (action) {
            html += '<div class="diagnosis-action">' +
                '<div class="diagnosis-action-step">' +
                '<span class="diagnosis-action-number">' + action.step + '</span>' +
                '<div class="diagnosis-action-content">' +
                '<div class="diagnosis-action-title">' + escapeHtml(action.title) + '</div>' +
                '<div class="diagnosis-action-description">' + escapeHtml(action.description) + '</div>' +
                '<div class="diagnosis-action-why">' + escapeHtml(action.why) + '</div>' +
                '</div>' +
                '</div>' +
                '</div>';
        });

        html += '</div>';
    }

    // Dismiss button
    html += '<button class="diagnosis-dismiss" onclick="dismissDiagnosis()">Got it, I\'ll check this</button>';

    container.innerHTML = html;
}

function dismissDiagnosis() {
    const container = document.getElementById('diagnosis-alert');
    container.classList.add('hidden');
    // Store dismissal in session so it doesn't reappear until page refresh
    sessionStorage.setItem('diagnosis_dismissed', 'true');
}

// ==================== INVESTIGATE APP MODAL ====================

function openInvestigateModal() {
    document.getElementById('investigate-modal').classList.remove('hidden');
    document.getElementById('investigate-app-name').value = '';
    document.getElementById('investigate-results').classList.add('hidden');
    document.getElementById('investigate-results').innerHTML = '';
}

function closeInvestigateModal() {
    document.getElementById('investigate-modal').classList.add('hidden');
}

async function investigateApp() {
    const appName = document.getElementById('investigate-app-name').value.trim();

    if (!appName) {
        showError('Please enter an app name');
        return;
    }

    const btn = document.getElementById('investigate-btn');
    const resultsContainer = document.getElementById('investigate-results');

    btn.disabled = true;
    btn.innerHTML = '🔍 Investigating...';

    resultsContainer.classList.remove('hidden');
    resultsContainer.innerHTML =
        '<div class="loading">' +
        '<div class="spinner"></div>' +
        '<p>Sherlock is investigating ' + escapeHtml(appName) + '...</p>' +
        '<p style="font-size: 13px; color: var(--slate-400);">Searching Reddit, reviews, and community reports...</p>' +
        '</div>';

    try {
        const response = await fetch('/api/v1/reports/investigate?app_name=' + encodeURIComponent(appName));
        const data = await response.json();

        renderInvestigationReport(appName, data);
    } catch (error) {
        console.error('Investigation error:', error);
        resultsContainer.innerHTML =
            '<div class="empty-state">' +
            '<div class="empty-state-icon">❌</div>' +
            '<h3>Investigation Failed</h3>' +
            '<p>Could not complete investigation. Please try again.</p>' +
            '</div>';
    } finally {
        btn.disabled = false;
        btn.innerHTML = '🔎 Investigate';
    }
}

function renderInvestigationReport(appName, data) {
    const container = document.getElementById('investigate-results');

    // Determine risk level and styling
    const riskScore = data.risk_score || 0;
    let riskLevel, riskClass, riskIcon, recommendation;

    if (riskScore >= 7) {
        riskLevel = 'HIGH RISK';
        riskClass = 'danger';
        riskIcon = '🚨';
        recommendation = 'Proceed with caution. Significant issues reported by the community.';
    } else if (riskScore >= 4) {
        riskLevel = 'MEDIUM RISK';
        riskClass = 'warning';
        riskIcon = '⚠️';
        recommendation = 'Some concerns found. Review the evidence below before installing.';
    } else {
        riskLevel = 'LOW RISK';
        riskClass = 'success';
        riskIcon = '✅';
        recommendation = 'No significant issues found. This app appears safe to install.';
    }

    // Build evidence sections
    let evidenceHtml = '';

    // Track Reddit URLs to avoid duplicates from Google
    var redditUrls = [];

    // Reddit evidence (show first - most relevant customer discussions)
    if (data.reddit_results && data.reddit_results.length > 0) {
        data.reddit_results.forEach(function (post) {
            if (post.url) redditUrls.push(post.url.toLowerCase());
        });

        evidenceHtml += '<div class="evidence-section">' +
            '<h4>💬 Reddit Discussions (' + data.reddit_results.length + ' found)</h4>' +
            '<p class="evidence-section-desc">Real merchant experiences and discussions</p>' +
            '<div class="evidence-list">';

        data.reddit_results.forEach(function (post) {
            evidenceHtml +=
                '<div class="evidence-item">' +
                '<a href="' + escapeHtml(post.url) + '" target="_blank" class="evidence-title">' + escapeHtml(post.title) + '</a>' +
                (post.snippet ? '<p class="evidence-snippet">"' + escapeHtml(post.snippet) + '"</p>' : '') +
                '<span class="evidence-source">r/' + escapeHtml(post.subreddit || 'shopify') + '</span>' +
                '</div>';
        });

        evidenceHtml += '</div></div>';
    }

    // Google evidence (filter out Reddit duplicates)
    if (data.google_results && data.google_results.length > 0) {
        // Filter out Reddit results already shown
        var filteredGoogle = data.google_results.filter(function (result) {
            var url = (result.url || result.link || '').toLowerCase();
            var isReddit = url.indexOf('reddit.com') !== -1;
            var isDuplicate = redditUrls.some(function (redditUrl) {
                return url.indexOf(redditUrl) !== -1 || redditUrl.indexOf(url) !== -1;
            });
            return !isReddit || !isDuplicate;
        });

        // Separate Reddit results found via Google (if Reddit API failed)
        var googleRedditResults = filteredGoogle.filter(function (r) {
            return (r.url || r.link || '').toLowerCase().indexOf('reddit.com') !== -1;
        });
        var otherWebResults = filteredGoogle.filter(function (r) {
            return (r.url || r.link || '').toLowerCase().indexOf('reddit.com') === -1;
        });

        // Show Reddit from Google if we didn't get direct Reddit results
        if (googleRedditResults.length > 0 && data.reddit_results.length === 0) {
            evidenceHtml += '<div class="evidence-section">' +
                '<h4>💬 Reddit Discussions (' + googleRedditResults.length + ' found)</h4>' +
                '<p class="evidence-section-desc">Real merchant experiences and discussions</p>' +
                '<div class="evidence-list">';

            googleRedditResults.forEach(function (result) {
                evidenceHtml +=
                    '<div class="evidence-item">' +
                    '<a href="' + escapeHtml(result.url || result.link) + '" target="_blank" class="evidence-title">' + escapeHtml(result.title) + '</a>' +
                    (result.snippet ? '<p class="evidence-snippet">"' + escapeHtml(result.snippet) + '"</p>' : '') +
                    '<span class="evidence-source">r/shopify</span>' +
                    '</div>';
            });

            evidenceHtml += '</div></div>';
        }

        // Show other web results
        if (otherWebResults.length > 0) {
            evidenceHtml += '<div class="evidence-section">' +
                '<h4>🔍 Web Results (' + otherWebResults.length + ' found)</h4>' +
                '<p class="evidence-section-desc">Reviews, articles, and documentation</p>' +
                '<div class="evidence-list">';

            otherWebResults.forEach(function (result) {
                evidenceHtml +=
                    '<div class="evidence-item">' +
                    '<a href="' + escapeHtml(result.url || result.link) + '" target="_blank" class="evidence-title">' + escapeHtml(result.title) + '</a>' +
                    (result.snippet ? '<p class="evidence-snippet">"' + escapeHtml(result.snippet) + '"</p>' : '') +
                    '<span class="evidence-source">' + escapeHtml(result.source || result.displayLink || 'Web') + '</span>' +
                    '</div>';
            });

            evidenceHtml += '</div></div>';
        }
    }

    // Database reports
    if (data.database_reports && data.database_reports.total > 0) {
        evidenceHtml += '<div class="evidence-section">' +
            '<h4>📊 Community Reports (' + data.database_reports.total + ' reports)</h4>' +
            '<p class="evidence-section-desc">Issues reported by Sherlock users</p>' +
            '<div class="evidence-list">';

        if (data.database_reports.issues && data.database_reports.issues.length > 0) {
            data.database_reports.issues.forEach(function (issue) {
                evidenceHtml +=
                    '<div class="evidence-item">' +
                    '<span class="evidence-issue-type">' + escapeHtml(issue.type) + '</span>' +
                    '<span class="evidence-count">' + issue.count + ' reports</span>' +
                    '</div>';
            });
        }

        evidenceHtml += '</div></div>';
    }

    // Known conflicts
    if (data.known_conflicts && data.known_conflicts.length > 0) {
        evidenceHtml += '<div class="evidence-section">' +
            '<h4>⚡ Known Conflicts</h4>' +
            '<p class="evidence-section-desc">Apps with reported compatibility issues</p>' +
            '<div class="evidence-list">';

        data.known_conflicts.forEach(function (conflict) {
            evidenceHtml +=
                '<div class="evidence-item">' +
                '<span class="evidence-conflict">Conflicts with: <strong>' + escapeHtml(conflict.app) + '</strong></span>' +
                (conflict.description ? '<p class="evidence-snippet">' + escapeHtml(conflict.description) + '</p>' : '') +
                '</div>';
        });

        evidenceHtml += '</div></div>';
    }

    // No evidence found
    if (!evidenceHtml) {
        evidenceHtml = '<div class="evidence-section">' +
            '<p style="color: var(--slate-400);">No community reports or discussions found for this app. This could mean it\'s new, rarely used, or simply has no reported issues.</p>' +
            '</div>';
    }
  

    // Build final report
    container.innerHTML =
        '<div class="investigation-report">' +
        '<div class="report-header">' +
        '<h3>' + escapeHtml(appName) + '</h3>' +
        '<div class="risk-badge ' + riskClass + '">' + riskIcon + ' ' + riskLevel + '</div>' +
        '</div>' +
        '<div class="report-recommendation">' +
        '<p><strong>Sherlock\'s Assessment:</strong> ' + recommendation + '</p>' +
        '</div>' +
        '<div class="report-evidence">' +
        '<h4 style="margin-bottom: 16px;">📋 Evidence</h4>' +
        evidenceHtml +
        '</div>' +
        '</div>';
}
// ==================== REPORT MODAL ====================

function openReportModal() {
    document.getElementById('report-modal').classList.remove('hidden');
}

function closeReportModal() {
    document.getElementById('report-modal').classList.add('hidden');
    document.getElementById('report-results').classList.add('hidden');
    document.getElementById('report-results').innerHTML = '';
}

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
        const params = new URLSearchParams({
            app_name: appName,
            shop: state.shop,
            issue_type: issueType,
            description: description
        });
        const result = await api('/reports/app?' + params.toString(), {
            method: 'POST'
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

function showReportResults(result) {
    const container = document.getElementById('report-results');
    container.classList.remove('hidden');

    let html = '<div style="padding: 16px; background: var(--emerald-bg); border: 1px solid var(--emerald-500); border-radius: var(--radius-md);">';
    html += '<h4 style="color: var(--emerald-400); margin-bottom: 12px;">✅ Report Submitted</h4>';
    html += '<button class="btn btn-secondary" onclick="closeReportModal()" style="margin-top: 12px;">Close</button>';

    if (result.reddit_results && result.reddit_results.length > 0) {
        html += '<p style="margin-bottom: 8px; font-weight: 600;">Related Reddit Discussions:</p>';
        html += '<ul style="margin-left: 20px;">';
        result.reddit_results.forEach(function (post) {
            html += '<li style="margin-bottom: 4px;"><a href="' + post.url + '" target="_blank" style="color: var(--gold-400);">' + escapeHtml(post.title) + '</a></li>';
        });
        html += '</ul>';
    }

    html += '</div>';
    container.innerHTML = html;

    showNotification('Report submitted successfully!', 'success');
}

function showReportError(message) {
    const container = document.getElementById('report-results');
    container.classList.remove('hidden');
    container.innerHTML =
        '<div style="padding: 16px; background: var(--crimson-bg); border: 1px solid var(--crimson-500); border-radius: var(--radius-md);">' +
        '<p style="color: var(--crimson-400);">❌ ' + escapeHtml(message) + '</p>' +
        '</div>';
}

// ==================== UTILITY FUNCTIONS ====================

function escapeHtml(text) {
    if (!text) return '';
    var div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function truncateUrl(url) {
    if (!url) return '';
    if (url.length > 60) {
        return url.substring(0, 30) + '...' + url.substring(url.length - 25);
    }
    return url;
}
// ==================== RATING WIDGET ====================

var selectedRating = 0;

function initRatingWidget() {
    const stars = document.querySelectorAll('#rating-stars .star');

    stars.forEach(function (star) {
        star.addEventListener('mouseenter', function () {
            const rating = parseInt(this.dataset.rating);
            highlightStars(rating);
        });

        star.addEventListener('mouseleave', function () {
            highlightStars(selectedRating);
        });

        star.addEventListener('click', function () {
            selectedRating = parseInt(this.dataset.rating);
            highlightStars(selectedRating);
        });
    });

    // Check if we should show the rating widget
    checkShowRatingWidget();
}

function highlightStars(rating) {
    const stars = document.querySelectorAll('#rating-stars .star');
    stars.forEach(function (star) {
        const starRating = parseInt(star.dataset.rating);
        if (starRating <= rating) {
            star.classList.add('active');
        } else {
            star.classList.remove('active');
        }
    });
}

function checkShowRatingWidget() {
    // Check if user has already rated recently (stored in localStorage)
    const lastRated = localStorage.getItem('sherlock_last_rated');
    const dismissed = localStorage.getItem('sherlock_rating_dismissed');

    if (lastRated) {
        const daysSinceRated = (Date.now() - parseInt(lastRated)) / (1000 * 60 * 60 * 24);
        if (daysSinceRated < 30) return; // Don't show again for 30 days
    }

    if (dismissed) {
        const daysSinceDismissed = (Date.now() - parseInt(dismissed)) / (1000 * 60 * 60 * 24);
        if (daysSinceDismissed < 7) return; // Don't show again for 7 days after dismiss
    }

    // Show widget after 3 scans or after 5 seconds on dashboard
    const scanCount = parseInt(localStorage.getItem('sherlock_scan_count') || '0');

    if (scanCount >= 3) {
        setTimeout(showRatingWidget, 2000);
    } else {
        setTimeout(function () {
            if (scanCount >= 1) {
                showRatingWidget();
            }
        }, 30000); // Show after 30 seconds if at least 1 scan
    }
}

function showRatingWidget() {
    const widget = document.getElementById('rating-widget');
    if (widget) {
        widget.classList.remove('hidden');
    }
}

function dismissRating() {
    const widget = document.getElementById('rating-widget');
    if (widget) {
        widget.classList.add('hidden');
    }
    localStorage.setItem('sherlock_rating_dismissed', Date.now().toString());
}

async function submitRating() {
    if (selectedRating === 0) {
        showNotification('Please select a rating', 'warning');
        return;
    }

    const comment = document.getElementById('rating-comment').value.trim();
    const btn = document.getElementById('rating-submit-btn');

    btn.disabled = true;
    btn.textContent = 'Submitting...';

    try {
        const response = await fetch('/api/v1/ratings/submit', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                shop: state.shop,
                rating: selectedRating,
                comment: comment
            })
        });

        if (response.ok) {
            // Show success state
            document.querySelector('.rating-content').classList.add('hidden');
            document.getElementById('rating-success').classList.remove('hidden');

            // Store that user has rated
            localStorage.setItem('sherlock_last_rated', Date.now().toString());

            // Hide widget after 3 seconds
            setTimeout(function () {
                const widget = document.getElementById('rating-widget');
                if (widget) {
                    widget.classList.add('hidden');
                }
            }, 3000);
        } else {
            throw new Error('Failed to submit rating');
        }
    } catch (error) {
        console.error('Rating submit error:', error);
        showNotification('Failed to submit rating. Please try again.', 'error');
        btn.disabled = false;
        btn.textContent = 'Submit Feedback';
    }
}

// Track scan count for rating widget trigger
function incrementScanCount() {
    const count = parseInt(localStorage.getItem('sherlock_scan_count') || '0');
    localStorage.setItem('sherlock_scan_count', (count + 1).toString());
}

// ==================== CAPABILITY MODAL ====================

var capabilityData = {
    monitoring: {
        title: '🛡️ 24/7 Monitoring',
        content: `
            <h4>What it does</h4>
            <p>Sherlock automatically scans your store every day, looking for changes that could cause problems — even while you sleep.</p>
            
            <h4>Why it matters for your store</h4>
            <p>Apps can update themselves, inject new code, or modify your theme without warning. A change that happens on Tuesday might not cause visible problems until the weekend when you're running a sale. Daily monitoring catches issues early, before they cost you sales.</p>
            
            <h4>What we check</h4>
            <ul>
                <li>Theme file changes (new, modified, or deleted files)</li>
                <li>New script injections from apps</li>
                <li>CSS that could conflict with your theme</li>
                <li>Performance impact changes</li>
            </ul>
            
            <h4>What you'll see</h4>
            <p>Your Store Protection Status card updates automatically. If something changes, you'll see warnings with specific details about what changed and which app likely caused it.</p>
        `
    },
    filetracking: {
        title: '📁 File Tracking',
        content: `
            <h4>What it does</h4>
            <p>Sherlock creates a "fingerprint" (checksum) of every file in your theme. When a file changes, we know exactly what changed and when.</p>
            
            <h4>Why it matters for your store</h4>
            <p>Many apps modify your theme files directly — adding code to your theme.liquid, cart.liquid, or other templates. Sometimes these changes break things. Without tracking, you'd never know which app made the change or when it happened.</p>
            
            <h4>Real example</h4>
            <p>A review app adds code to your product template. Later, you install a currency converter that conflicts with that code. Your product pages break, but you don't know why. With file tracking, Sherlock shows you exactly which files changed and when, so you can identify the culprit.</p>
            
            <h4>What we track</h4>
            <ul>
                <li>All .liquid template files</li>
                <li>CSS and JavaScript files</li>
                <li>Config and settings files</li>
                <li>Asset files</li>
            </ul>
        `
    },
    conflicts: {
        title: '⚡ Conflict Detection',
        content: `
            <h4>What it does</h4>
            <p>Sherlock maintains a database of known app conflicts based on community reports and our own research. We check your installed apps against this database.</p>
            
            <h4>Why it matters for your store</h4>
            <p>Some apps simply don't play nice together. They might both try to modify the same part of your theme, or their JavaScript conflicts. These issues are often not documented anywhere — you only find out when something breaks.</p>
            
            <h4>How we know about conflicts</h4>
            <ul>
                <li>Merchant reports from our community</li>
                <li>Reddit discussions and forums</li>
                <li>Web reviews and articles</li>
                <li>Our own testing and research</li>
            </ul>
            
            <h4>What you can do</h4>
            <p>Check the Conflicts tab to see if any of your installed apps have known issues with each other. If conflicts are found, we'll explain the issue and suggest solutions.</p>
        `
    },
    orphan: {
        title: '🧹 Orphan Code Finder',
        content: `
            <h4>What it does</h4>
            <p>When you uninstall an app, it should remove all the code it added to your theme. But many apps don't clean up after themselves. Sherlock finds this leftover "orphan" code.</p>
            
            <h4>Why it matters for your store</h4>
            <p>Orphan code slows down your store. Every extra line of code takes time to load and process. If you've installed and uninstalled several apps over the years, you might have hundreds of lines of useless code dragging down your performance.</p>
            
            <h4>Common culprits</h4>
            <ul>
                <li>Review apps that leave star rating code</li>
                <li>Chat widgets that leave loading scripts</li>
                <li>Pop-up apps that leave modal code</li>
                <li>Analytics apps that leave tracking snippets</li>
            </ul>
            
            <h4>What you can do</h4>
            <p>Check the Orphan Code tab. Sherlock identifies suspicious code and tells you which app likely left it behind. You can then safely remove it or ask a developer to help.</p>
        `
    },
    performance: {
        title: '📊 Performance Impact',
        content: `
            <h4>What it does</h4>
            <p>Sherlock measures your store's loading speed and tracks how it changes over time, especially after you install or update apps.</p>
            
            <h4>Why it matters for your store</h4>
            <p>Every second of load time costs you sales. Studies show that a 1-second delay can reduce conversions by 7%. When you install a new app, you need to know if it's slowing down your store.</p>
            
            <h4>What we measure</h4>
            <ul>
                <li>Homepage load time</li>
                <li>Product page load time</li>
                <li>Collection page load time</li>
                <li>Cart page load time</li>
                <li>Overall performance score (0-100)</li>
            </ul>
            
            <h4>What you'll see</h4>
            <p>Check the Timeline tab to see how your performance has changed over time. If you notice a drop after installing an app, that app might be the problem.</p>
        `
    },
    rollback: {
        title: '🔄 Rollback Protection',
        content: `
            <h4>What it does</h4>
            <p>Sherlock saves snapshots of your theme files. If an app breaks something, you can restore individual files to their previous working state.</p>
            
            <h4>Why it matters for your store</h4>
            <p>When something breaks at 2am before a big sale, you don't want to be scrambling to figure out what changed. With rollback protection, you can quickly restore the affected files and deal with the root cause later.</p>
            
            <h4>How it works</h4>
            <ul>
                <li>We save file versions with each daily scan</li>
                <li>You can view the history of any file</li>
                <li>One-click restore to any previous version</li>
                <li>See exactly what changed between versions</li>
            </ul>
            
            <h4>Peace of mind</h4>
            <p>This is your safety net. Install new apps with confidence knowing you can always roll back if something goes wrong.</p>
        `
    }
};
var protectionStatData = {
    totalfiles: {
        title: '📄 Total Files',
        content: `
            <h4>What it means</h4>
            <p>This is the total number of files in your Shopify theme that Sherlock is monitoring.</p>
            
            <h4>What's included</h4>
            <ul>
                <li>Liquid templates (.liquid files)</li>
                <li>Stylesheets (CSS files)</li>
                <li>JavaScript files</li>
                <li>Configuration files (settings, locales)</li>
                <li>Assets (images, fonts)</li>
            </ul>
            
            <h4>Why it matters</h4>
            <p>More files means more places where apps can inject code or make changes. Sherlock tracks every file so nothing slips through unnoticed.</p>
        `
    },
    newfiles: {
        title: '🆕 New Files',
        content: `
            <h4>What it means</h4>
            <p>Files that have been added to your theme since the last scan.</p>
            
            <h4>Common causes</h4>
            <ul>
                <li>Installing a new app that adds theme files</li>
                <li>Theme updates from your theme developer</li>
                <li>Manual additions by you or a developer</li>
            </ul>
            
            <h4>What to do</h4>
            <p>If you see unexpected new files, check what apps you recently installed. New files aren't necessarily bad, but you should know where they came from.</p>
        `
    },
    changed: {
        title: '✏️ Changed Files',
        content: `
            <h4>What it means</h4>
            <p>Files that existed before but have been modified since the last scan.</p>
            
            <h4>Common causes</h4>
            <ul>
                <li>Apps injecting code into your theme</li>
                <li>Theme updates</li>
                <li>Manual edits in the theme editor</li>
                <li>App updates modifying existing code</li>
            </ul>
            
            <h4>What to do</h4>
            <p>If you didn't make changes yourself, investigate which app modified your files. Unexpected changes can cause display issues or conflicts.</p>
        `
    },
    cssissues: {
        title: '🎨 CSS Issues',
        content: `
            <h4>What it means</h4>
            <p>CSS rules that don't use proper namespacing and could conflict with your theme or other apps.</p>
            
            <h4>The problem</h4>
            <p>When an app uses generic CSS selectors like <code>.button</code> or <code>.container</code> instead of namespaced ones like <code>.app-name-button</code>, their styles can accidentally override your theme's styles.</p>
            
            <h4>Symptoms of CSS conflicts</h4>
            <ul>
                <li>Buttons looking different than expected</li>
                <li>Text colors or sizes changing</li>
                <li>Layout breaking on certain pages</li>
                <li>Elements appearing in wrong positions</li>
            </ul>
            
            <h4>What to do</h4>
            <p>If you have CSS issues and notice visual problems, the apps with non-namespaced CSS are likely culprits. Contact the app developer or consider alternatives.</p>
        `
    },
    scripts: {
        title: '⚡ Scripts',
        content: `
            <h4>What it means</h4>
            <p>JavaScript files injected into your store by apps via Shopify's Script Tags API.</p>
            
            <h4>How it works</h4>
            <p>Apps can add JavaScript to your storefront without modifying your theme files. These scripts load on every page of your store.</p>
            
            <h4>Why it matters</h4>
            <ul>
                <li>Each script adds to page load time</li>
                <li>Scripts can conflict with each other</li>
                <li>Some scripts continue running after you uninstall the app</li>
                <li>Too many scripts significantly slow down your store</li>
            </ul>
            
            <h4>What to do</h4>
            <p>If you have many scripts and slow page loads, consider which apps are essential. Some apps offer "lazy loading" options to reduce performance impact.</p>
        `
    }
};

function showProtectionStat(key) {
    var data = protectionStatData[key];
    if (!data) return;

    document.getElementById('capability-modal-title').innerHTML = data.title;
    document.getElementById('capability-modal-body').innerHTML = data.content;
    document.getElementById('capability-modal').classList.remove('hidden');
}

function showCapability(key) {
    var data = capabilityData[key];
    if (!data) return;

    document.getElementById('capability-modal-title').innerHTML = data.title;
    document.getElementById('capability-modal-body').innerHTML = data.content;
    document.getElementById('capability-modal').classList.remove('hidden');
}

function closeCapabilityModal() {
    document.getElementById('capability-modal').classList.add('hidden');
}

// Initialize on DOM ready
document.addEventListener('DOMContentLoaded', function () {
    init();
    initRatingWidget();
});
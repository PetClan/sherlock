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
        '<div class="stat-card">' +
        '<div class="stat-value">' + totalScans + '</div>' +
        '<div class="stat-label">Investigations Run</div>' +
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
            updateCaseFiles(data.scan);
        } else {
            container.innerHTML =
                '<div class="empty-state">' +
                '<div class="empty-state-icon">🕵️</div>' +
                '<h3>No Investigation Yet</h3>' +
                '<p>Run your first investigation to see your store\'s protection status.</p>' +
                '</div>';

            // Reset case files to default
            resetCaseFiles();
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
        '<div class="protection-stat tooltip">' +
        '<span class="stat-info">ℹ️</span>' +
        '<span class="tooltip-text">Total number of files in your theme that Sherlock is monitoring for changes.</span>' +
        '<div class="protection-stat-value">' + (scan.files_total || 0) + '</div>' +
        '<div class="protection-stat-label">Total Files</div>' +
        '</div>' +
        '<div class="protection-stat tooltip">' +
        '<span class="stat-info">ℹ️</span>' +
        '<span class="tooltip-text">New files added since the last scan. Could be from theme updates or app installations.</span>' +
        '<div class="protection-stat-value ' + (scan.files_new > 0 ? 'warning' : '') + '">' + (scan.files_new || 0) + '</div>' +
        '<div class="protection-stat-label">New Files</div>' +
        '</div>' +
        '<div class="protection-stat tooltip">' +
        '<span class="stat-info">ℹ️</span>' +
        '<span class="tooltip-text">Files that have been modified since the last scan. Review to ensure changes are expected.</span>' +
        '<div class="protection-stat-value ' + (scan.files_changed > 0 ? 'warning' : '') + '">' + (scan.files_changed || 0) + '</div>' +
        '<div class="protection-stat-label">Changed</div>' +
        '</div>' +
        '<div class="protection-stat tooltip">' +
        '<span class="stat-info">ℹ️</span>' +
        '<span class="tooltip-text">CSS rules that don\'t use proper namespacing. These can conflict with your theme or other apps.</span>' +
        '<div class="protection-stat-value ' + (scan.css_issues_found > 0 ? 'danger' : '') + '">' + (scan.css_issues_found || 0) + '</div>' +
        '<div class="protection-stat-label">CSS Issues</div>' +
        '</div>' +
        '<div class="protection-stat tooltip">' +
        '<span class="stat-info">ℹ️</span>' +
        '<span class="tooltip-text">JavaScript files injected by apps via Shopify\'s Script Tags API.</span>' +
        '<div class="protection-stat-value">' + (scan.scripts_total || 0) + '</div>' +
        '<div class="protection-stat-label">Scripts</div>' +
        '</div>' +
        '</div>';
}

function updateCaseFiles(scan) {
    // Update Theme Files case
    var themeCard = document.getElementById('case-theme');
    var themeValue = document.getElementById('case-theme-value');
    var themeStatus = document.getElementById('case-theme-status');

    if (themeValue) themeValue.textContent = scan.files_total || 0;

    if (scan.files_new > 0 || scan.files_changed > 0) {
        themeCard.className = 'case-file status-warning';
        themeStatus.className = 'case-file-status warning';
        themeStatus.textContent = '⚠️ ' + (scan.files_new + scan.files_changed) + ' changes';
    } else {
        themeCard.className = 'case-file status-clean';
        themeStatus.className = 'case-file-status clean';
        themeStatus.textContent = '✓ Clean';
    }

    // Update Scripts case
    var scriptsCard = document.getElementById('case-scripts');
    var scriptsValue = document.getElementById('case-scripts-value');
    var scriptsStatus = document.getElementById('case-scripts-status');

    if (scriptsValue) scriptsValue.textContent = scan.scripts_total || 0;

    if (scan.scripts_new > 0) {
        scriptsCard.className = 'case-file status-warning';
        scriptsStatus.className = 'case-file-status warning';
        scriptsStatus.textContent = '⚠️ ' + scan.scripts_new + ' new';
    } else {
        scriptsCard.className = 'case-file status-clean';
        scriptsStatus.className = 'case-file-status clean';
        scriptsStatus.textContent = '✓ Clean';
    }

    // Update CSS case
    var cssCard = document.getElementById('case-css');
    var cssValue = document.getElementById('case-css-value');
    var cssStatus = document.getElementById('case-css-status');

    if (cssValue) {
        cssValue.textContent = scan.css_issues_found || 0;
        if (scan.css_issues_found > 0) {
            cssValue.className = 'metric-value ' + (scan.css_issues_found > 20 ? 'danger' : 'warning');
        }
    }

    if (scan.css_issues_found > 20) {
        cssCard.className = 'case-file status-danger';
        cssStatus.className = 'case-file-status danger';
        cssStatus.textContent = '🚨 ' + scan.css_issues_found + ' issues';
    } else if (scan.css_issues_found > 0) {
        cssCard.className = 'case-file status-warning';
        cssStatus.className = 'case-file-status warning';
        cssStatus.textContent = '⚠️ ' + scan.css_issues_found + ' issues';
    } else {
        cssCard.className = 'case-file status-clean';
        cssStatus.className = 'case-file-status clean';
        cssStatus.textContent = '✓ Clean';
    }
}

function resetCaseFiles() {
    document.getElementById('case-theme-value').textContent = '—';
    document.getElementById('case-scripts-value').textContent = '—';
    document.getElementById('case-css-value').textContent = '—';
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

// ==================== SCAN FUNCTIONS ====================

async function startScan(scanType) {
    if (state.isScanning) {
        showNotification('An investigation is already in progress', 'warning');
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
        showError('Failed to start investigation: ' + error.message);
        state.isScanning = false;
        hideProgressBanner();
    }
}

function pollScanStatus(diagnosisId) {
    state.pollInterval = setInterval(async function () {
        try {
            const status = await api('/scan/status/' + diagnosisId);
            showScanProgress(status);

            if (status.status === 'completed' || status.status === 'failed') {
                stopPolling();
                if (status.status === 'completed') {
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
        const report = await api('/scan/report/' + diagnosisId);
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
        const result = await api('/performance/' + state.shop + '/history');
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

// Initialize on DOM ready
document.addEventListener('DOMContentLoaded', init);
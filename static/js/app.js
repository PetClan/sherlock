/**
 * Sherlock Dashboard - Main JavaScript
 */

// Global state
const state = {
    shop: null,
    currentScan: null,
    pollInterval: null,
    isScanning: false,
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
function showNotification(message, type = 'info') {
    const container = document.getElementById('notifications');
    if (!container) return;

    const notification = document.createElement('div');
    notification.className = 'notification notification-' + type;
    notification.innerHTML =
        '<span>' + message + '</span>' +
        '<button class="notification-close" onclick="this.parentElement.remove()">&times;</button>';

    container.appendChild(notification);

    // Auto-remove after 5 seconds
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

// Initialize dashboard
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
function renderSuspectApps(appsData) {
    const container = document.getElementById('suspect-apps');
    const apps = appsData.apps || [];
    const suspects = apps.filter(function (a) { return a.is_suspect; });

    if (!suspects.length) {
        container.innerHTML =
            '<div class="empty-state">' +
            '<div class="empty-state-icon">✅</div>' +
            '<h3>No suspect apps</h3>' +
            '<p>All installed apps look healthy</p>' +
            '</div>';
        return;
    }

    let rows = '';
    suspects.forEach(function (app) {
        rows += '<tr>' +
            '<td>' +
            '<div class="app-row">' +
            '<div class="app-icon">📦</div>' +
            '<div class="app-info">' +
            '<h4>' + escapeHtml(app.app_name) + '</h4>' +
            '<p>Installed: ' + (app.installed_on ? formatDate(app.installed_on) : 'Unknown') + '</p>' +
            '</div>' +
            '</div>' +
            '</td>' +
            '<td>' +
            '<div class="risk-bar">' +
            '<div class="risk-bar-fill ' + getRiskClass(app.risk_score) + '" style="width: ' + app.risk_score + '%"></div>' +
            '</div>' +
            '<span style="font-size: 12px; color: var(--gray);">' + Math.round(app.risk_score) + '%</span>' +
            '</td>' +
            '<td>' +
            '<span class="badge ' + (app.risk_score >= 60 ? 'badge-danger' : 'badge-warning') + '">' +
            (app.risk_score >= 60 ? 'High Risk' : 'Medium Risk') +
            '</span>' +
            '</td>' +
            '<td style="max-width: 300px;">' +
            '<small style="color: var(--gray);">' +
            (app.risk_reasons ? app.risk_reasons.join(', ') : '—') +
            '</small>' +
            '</td>' +
            '</tr>';
    });

    container.innerHTML =
        '<div class="table-container">' +
        '<table>' +
        '<thead>' +
        '<tr>' +
        '<th>App</th>' +
        '<th>Risk Score</th>' +
        '<th>Status</th>' +
        '<th>Reasons</th>' +
        '</tr>' +
        '</thead>' +
        '<tbody>' + rows + '</tbody>' +
        '</table>' +
        '</div>';
}

// Start a new scan
async function startScan(scanType) {
    if (state.isScanning) {
        console.log('Scan already in progress');
        return;
    }

    state.isScanning = true;
    scanType = scanType || 'full';

    try {
        const result = await api('/scan/start', {
            method: 'POST',
            body: JSON.stringify({
                shop: state.shop,
                scan_type: scanType,
            }),
        });

        state.currentScan = result.diagnosis_id;
        showScanProgress(result);
        pollScanStatus(result.diagnosis_id);

    } catch (error) {
        console.error('Scan start error:', error);
        showError('Failed to start scan. Please try again.');
        state.isScanning = false;
    }
}

// Poll scan status
function pollScanStatus(diagnosisId) {
    stopPolling();
    state.isScanning = true;

    state.pollInterval = setInterval(async function () {
        try {
            const result = await api('/scan/' + diagnosisId);

            if (result.status === 'completed' || result.status === 'failed') {
                stopPolling();
                hideProgressBanner();

                if (result.status === 'completed') {
                    showSuccess('Scan complete! Found ' + result.issues_found + ' issues.');
                } else {
                    showError('Scan failed. Please try again.');
                }

                loadDashboard();
            }
        } catch (error) {
            console.error('Poll error:', error);
            stopPolling();
            hideProgressBanner();
            showError('Error checking scan status. Please refresh the page.');
        }
    }, 2000);
}

// Show scan progress
function showScanProgress(scan) {
    const container = document.getElementById('scan-progress');
    if (container) {
        container.style.display = 'block';
        container.innerHTML =
            '<div class="alert alert-info">' +
            '<span class="spinner" style="width:20px;height:20px;border-width:2px;"></span>' +
            '<div>' +
            '<strong>Scan in progress...</strong>' +
            '<p style="margin:0;">Running ' + scan.scan_type + ' diagnostic. This may take a minute.</p>' +
            '</div>' +
            '</div>';
    }
}

// View scan details
async function viewScan(diagnosisId) {
    try {
        stopPolling();
        hideProgressBanner();

        const report = await api('/scan/' + diagnosisId + '/report');
        renderScanReport(report);

    } catch (error) {
        console.error('View scan error:', error);
        showError('Failed to load scan report.');
    }
}

// Render scan report
function renderScanReport(report) {
    const mainContent = document.getElementById('main-content');

    const summaryClass = report.summary?.verdict === 'culprit_identified' ? 'danger' :
        report.summary?.verdict === 'suspects_found' ? 'warning' :
            report.summary?.verdict === 'no_issues' ? 'success' : '';

    let recommendationsHtml = '';
    const recs = (report.recommendations || []).filter(function (r) { return r.type !== 'guide'; }).slice(0, 5);
    recs.forEach(function (r) {
        recommendationsHtml +=
            '<div class="recommendation">' +
            '<div class="recommendation-priority ' + (r.priority === 1 ? 'high' : r.priority === 2 ? 'medium' : 'low') + '">' +
            r.priority +
            '</div>' +
            '<div class="recommendation-content">' +
            '<h4>' + escapeHtml(r.action) + '</h4>' +
            '<p>' + escapeHtml(r.reason || '') + '</p>' +
            '</div>' +
            '</div>';
    });

    let suspectsHtml = '';
    if (report.suspect_apps && report.suspect_apps.length) {
        suspectsHtml = '<div class="card"><div class="card-header"><h3 class="card-title">Suspect Apps</h3></div><ul style="list-style:none;">';
        report.suspect_apps.forEach(function (app) {
            suspectsHtml += '<li style="padding:8px 0;border-bottom:1px solid var(--light-gray);">📦 <strong>' + escapeHtml(app) + '</strong></li>';
        });
        suspectsHtml += '</ul></div>';
    }

    mainContent.innerHTML =
        '<div class="mb-2">' +
        '<button class="btn btn-secondary" onclick="backToDashboard()">← Back to Dashboard</button>' +
        '</div>' +
        '<div class="summary-box ' + summaryClass + '">' +
        '<h2>Diagnosis Summary</h2>' +
        '<p>' + (report.summary?.quick_summary || 'Scan completed.') + '</p>' +
        '</div>' +
        '<div class="grid grid-3 mb-2">' +
        '<div class="card stat-card">' +
        '<div class="stat-value">' + (report.total_apps_scanned || 0) + '</div>' +
        '<div class="stat-label">Apps Scanned</div>' +
        '</div>' +
        '<div class="card stat-card">' +
        '<div class="stat-value ' + (report.issues_found > 0 ? 'danger' : 'success') + '">' + (report.issues_found || 0) + '</div>' +
        '<div class="stat-label">Issues Found</div>' +
        '</div>' +
        '<div class="card stat-card">' +
        '<div class="stat-value ' + getScoreClass(report.performance_score) + '">' + (report.performance_score ? Math.round(report.performance_score) : '—') + '</div>' +
        '<div class="stat-label">Performance</div>' +
        '</div>' +
        '</div>' +
        '<div class="card">' +
        '<div class="card-header"><h3 class="card-title">Recommendations</h3></div>' +
        (recommendationsHtml || '<p style="color:var(--gray);">No specific recommendations.</p>') +
        '</div>' +
        suspectsHtml;
}

// Back to dashboard
function backToDashboard() {
    document.getElementById('main-content').innerHTML =
        '<div id="tab-dashboard" class="tab-content">' +
        '<div id="scan-progress" style="display:none;"></div>' +
        '<div id="stats-container"><div class="loading"><div class="spinner"></div></div></div>' +
        '<div class="grid grid-2">' +
        '<div class="card">' +
        '<div class="card-header">' +
        '<h3 class="card-title">Recent Scans</h3>' +
        '<div>' +
        '<button class="btn btn-secondary btn-sm" onclick="startScan(\'quick\')">⚡ Quick</button>' +
        '<button class="btn btn-primary btn-sm" onclick="startScan(\'full\')">🔍 Full Scan</button>' +
        '</div>' +
        '</div>' +
        '<div id="recent-scans"><div class="loading"><div class="spinner"></div><p>Loading...</p></div></div>' +
        '</div>' +
        '<div class="card">' +
        '<div class="card-header">' +
        '<h3 class="card-title">Suspect Apps</h3>' +
        '<button class="btn btn-secondary btn-sm" onclick="viewAllApps()">View All Apps</button>' +
        '</div>' +
        '<div id="suspect-apps"><div class="loading"><div class="spinner"></div><p>Loading...</p></div></div>' +
        '</div>' +
        '</div>' +
        '</div>';

    loadDashboard();
}

// View all apps
async function viewAllApps() {
    try {
        const appsData = await api('/apps/' + state.shop);
        renderAllApps(appsData);
    } catch (error) {
        console.error('Load apps error:', error);
        showError('Failed to load apps.');
    }
}

// Render all apps
function renderAllApps(appsData) {
    const mainContent = document.getElementById('main-content');
    const apps = appsData.apps || [];

    let rows = '';
    apps.forEach(function (app) {
        rows += '<tr>' +
            '<td>' +
            '<div class="app-row">' +
            '<div class="app-icon">' + (app.is_suspect ? '⚠️' : '📦') + '</div>' +
            '<div class="app-info">' +
            '<h4>' + escapeHtml(app.app_name) + '</h4>' +
            '<p>Installed: ' + (app.installed_on ? formatDate(app.installed_on) : 'Unknown') + '</p>' +
            '</div>' +
            '</div>' +
            '</td>' +
            '<td>' +
            '<div class="risk-bar">' +
            '<div class="risk-bar-fill ' + getRiskClass(app.risk_score) + '" style="width: ' + app.risk_score + '%"></div>' +
            '</div>' +
            '<span style="font-size: 12px;">' + Math.round(app.risk_score) + '%</span>' +
            '</td>' +
            '<td>' +
            (app.injects_scripts ? '<span class="badge badge-warning">Scripts</span>' : '') +
            (app.injects_theme_code ? '<span class="badge badge-warning">Theme</span>' : '') +
            '</td>' +
            '<td style="max-width: 300px;">' +
            '<small style="color: var(--gray);">' + (app.risk_reasons?.join(', ') || '—') + '</small>' +
            '</td>' +
            '</tr>';
    });

    mainContent.innerHTML =
        '<div class="mb-2">' +
        '<button class="btn btn-secondary" onclick="backToDashboard()">← Back to Dashboard</button>' +
        '</div>' +
        '<div class="card">' +
        '<div class="card-header">' +
        '<h3 class="card-title">All Installed Apps (' + apps.length + ')</h3>' +
        '<span class="badge ' + (appsData.suspect_count > 0 ? 'badge-danger' : 'badge-success') + '">' + appsData.suspect_count + ' suspects</span>' +
        '</div>' +
        '<div class="table-container">' +
        '<table>' +
        '<thead><tr><th>App</th><th>Risk Score</th><th>Injections</th><th>Risk Reasons</th></tr></thead>' +
        '<tbody>' + rows + '</tbody>' +
        '</table>' +
        '</div>' +
        '</div>';
}

// Utility functions
function showError(message) {
    const container = document.getElementById('notifications');
    if (container) {
        container.innerHTML =
            '<div class="alert alert-danger">' +
            '<span class="alert-icon">❌</span>' +
            '<div>' + escapeHtml(message) + '</div>' +
            '</div>';
        setTimeout(function () { container.innerHTML = ''; }, 5000);
    }
}

function showSuccess(message) {
    const container = document.getElementById('notifications');
    if (container) {
        container.innerHTML =
            '<div class="alert alert-success">' +
            '<span class="alert-icon">✅</span>' +
            '<div>' + escapeHtml(message) + '</div>' +
            '</div>';
        setTimeout(function () { container.innerHTML = ''; }, 5000);
    }
}

function capitalizeFirst(str) {
    return str ? str.charAt(0).toUpperCase() + str.slice(1) : '';
}

function formatDate(dateStr) {
    if (!dateStr) return '—';
    const date = new Date(dateStr);
    return date.toLocaleDateString('en-US', {
        month: 'short',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
    });
}

function escapeHtml(str) {
    if (!str) return '';
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

function getRiskClass(score) {
    if (score >= 60) return 'high';
    if (score >= 30) return 'medium';
    return 'low';
}

function getScoreClass(score) {
    if (!score) return '';
    if (score >= 70) return 'success';
    if (score >= 40) return 'warning';
    return 'danger';
}

// Tab Navigation
function switchTab(tabName) {
    document.querySelectorAll('.tab-content').forEach(function (el) {
        el.classList.add('hidden');
    });
    document.querySelectorAll('.tab').forEach(function (el) {
        el.classList.remove('active');
    });

    const tabContent = document.getElementById('tab-' + tabName);
    if (tabContent) {
        tabContent.classList.remove('hidden');
    }

    if (event && event.target) {
        event.target.classList.add('active');
    }

    // Load community data when tab opens
    if (tabName === 'community') {
        loadMostReportedApps();
    }

    // Load monitoring data when tab opens
    if (tabName === 'monitoring') {
        loadLatestMonitoringScan();
        loadMonitoringHistory();
    }
}

// Conflicts Tab
async function checkConflicts() {
    const container = document.getElementById('conflicts-content');
    container.innerHTML = '<div class="loading"><div class="spinner"></div><p>Checking conflicts...</p></div>';

    try {
        const result = await api('/conflicts/check?shop=' + state.shop, { method: 'POST' });
        renderConflicts(result);
    } catch (error) {
        console.error('Check conflicts error:', error);
        showError('Failed to check conflicts');
    }
}

function renderConflicts(data) {
    const container = document.getElementById('conflicts-content');

    let html = '';

    html += '<div class="alert ' + (data.conflicts_found > 0 ? 'alert-danger' : 'alert-success') + '" style="margin-bottom: 20px;">';
    html += '<span class="alert-icon">' + (data.conflicts_found > 0 ? '⚠️' : '✅') + '</span>';
    html += '<div><strong>' + (data.conflicts_found > 0 ? 'Found ' + data.conflicts_found + ' conflict(s)!' : 'No conflicts found!') + '</strong>';
    html += '<p style="margin:0;">' + data.installed_apps_count + ' apps analyzed</p></div></div>';

    if (data.conflicts && data.conflicts.length > 0) {
        html += '<h4 style="margin-bottom: 12px;">⚡ App Conflicts</h4>';
        data.conflicts.forEach(function (conflict) {
            var severityClass = conflict.severity === 'critical' ? 'danger' : conflict.severity === 'high' ? 'warning' : 'info';
            html += '<div class="recommendation" style="border-left: 4px solid var(--' + severityClass + ');">';
            html += '<div class="recommendation-priority ' + (severityClass === 'danger' ? 'high' : severityClass === 'warning' ? 'medium' : 'low') + '">';
            html += conflict.severity === 'critical' ? '!' : conflict.severity === 'high' ? '!!' : 'i';
            html += '</div><div class="recommendation-content">';
            html += '<h4>' + conflict.conflicting_apps.join(' ↔ ') + '</h4>';
            html += '<p>' + escapeHtml(conflict.description) + '</p>';
            html += '<p style="color: var(--success); margin-top: 8px;"><strong>Solution:</strong> ' + escapeHtml(conflict.solution) + '</p>';
            html += '<small style="color: var(--gray);">Community reports: ' + (conflict.community_reports || 0) + '</small>';
            html += '</div></div>';
        });
    }

    if (data.duplicate_functionality && Object.keys(data.duplicate_functionality).length > 0) {
        html += '<h4 style="margin: 20px 0 12px;">📦 Duplicate Functionality</h4>';
        for (var category in data.duplicate_functionality) {
            var apps = data.duplicate_functionality[category];
            html += '<div class="alert alert-warning"><span class="alert-icon">📦</span><div>';
            html += '<strong>Multiple ' + category.replace('_', ' ') + ' apps</strong>';
            html += '<p style="margin:0;">You have ' + apps.length + ' apps doing the same thing: ' + apps.join(', ') + '</p>';
            html += '</div></div>';
        }
    }

    container.innerHTML = html || '<div class="empty-state"><h3>No issues found!</h3></div>';
}

// Orphan Code Tab
async function scanOrphanCode() {
    const container = document.getElementById('orphan-content');
    container.innerHTML = '<div class="loading"><div class="spinner"></div><p>Scanning for orphan code...</p></div>';

    try {
        const result = await api('/orphan-code/scan?shop=' + state.shop, { method: 'POST' });
        renderOrphanCode(result);
    } catch (error) {
        console.error('Orphan code scan error:', error);
        showError('Failed to scan for orphan code');
    }
}

function renderOrphanCode(data) {
    const container = document.getElementById('orphan-content');

    let html = '';

    html += '<div class="alert ' + (data.total_orphan_instances > 0 ? 'alert-warning' : 'alert-success') + '" style="margin-bottom: 20px;">';
    html += '<span class="alert-icon">' + (data.total_orphan_instances > 0 ? '🧹' : '✅') + '</span>';
    html += '<div><strong>' + (data.total_orphan_instances > 0 ? 'Found ' + data.total_orphan_instances + ' orphan code instance(s)!' : 'No orphan code found!') + '</strong>';
    html += '<p style="margin:0;">' + (data.files_scanned || 0) + ' files scanned, ' + (data.uninstalled_apps_with_leftover_code || 0) + ' uninstalled apps left code behind</p></div></div>';

    if (data.orphan_code_by_app && data.orphan_code_by_app.length > 0) {
        html += '<h4 style="margin-bottom: 12px;">🧹 Leftover Code by App</h4>';
        data.orphan_code_by_app.forEach(function (app) {
            html += '<div class="card" style="margin-bottom: 12px; padding: 16px;">';
            html += '<h4 style="margin-bottom: 8px;">📦 ' + escapeHtml(app.app) + ' (uninstalled)</h4>';
            html += '<p style="margin-bottom: 8px; color: var(--gray);">Found ' + app.total_occurrences + ' code fragment(s) in ' + app.files_affected.length + ' file(s)</p>';
            html += '<p style="margin-bottom: 8px;"><strong>Files affected:</strong></p>';
            html += '<ul style="margin-left: 20px; margin-bottom: 8px;">';
            app.files_affected.slice(0, 5).forEach(function (f) {
                html += '<li><code>' + escapeHtml(f) + '</code></li>';
            });
            html += '</ul>';
            html += '<p style="color: var(--success);"><strong>How to fix:</strong> ' + escapeHtml(app.cleanup_guide) + '</p>';
            html += '</div>';
        });
    }

    container.innerHTML = html || '<div class="empty-state"><h3>No orphan code found!</h3></div>';
}

// Timeline Tab
async function loadTimeline() {
    const container = document.getElementById('timeline-content');
    container.innerHTML = '<div class="loading"><div class="spinner"></div><p>Loading timeline...</p></div>';

    try {
        const timeline = await api('/timeline/' + state.shop + '?days=90');
        const rankings = await api('/timeline/' + state.shop + '/impact-ranking');
        renderTimeline(timeline, rankings);
    } catch (error) {
        console.error('Load timeline error:', error);
        showError('Failed to load timeline');
    }
}

function renderTimeline(timeline, rankings) {
    const container = document.getElementById('timeline-content');

    let html = '';

    html += '<div class="grid grid-3" style="margin-bottom: 20px;">';
    html += '<div class="card stat-card"><div class="stat-value">' + (timeline.app_installs || 0) + '</div><div class="stat-label">Apps Installed (90 days)</div></div>';
    html += '<div class="card stat-card"><div class="stat-value">' + (timeline.performance_snapshots || 0) + '</div><div class="stat-label">Performance Tests</div></div>';
    html += '<div class="card stat-card"><div class="stat-value ' + ((timeline.correlations?.length || 0) > 0 ? 'danger' : 'success') + '">' + (timeline.correlations?.length || 0) + '</div><div class="stat-label">Negative Correlations</div></div>';
    html += '</div>';

    if (timeline.correlations && timeline.correlations.length > 0) {
        html += '<h4 style="margin-bottom: 12px;">📉 Apps that Degraded Performance</h4>';
        timeline.correlations.forEach(function (corr) {
            html += '<div class="recommendation"><div class="recommendation-priority high">!</div><div class="recommendation-content">';
            html += '<h4>' + escapeHtml(corr.app_name) + '</h4>';
            html += '<p><strong>Verdict:</strong> ' + escapeHtml(corr.verdict) + '</p>';
            html += '<div style="display: flex; gap: 20px; margin-top: 8px;">';
            html += '<span>Score: ' + (corr.changes?.performance_score?.before || '?') + ' → ' + (corr.changes?.performance_score?.after || '?') + '</span>';
            html += '<span>Load time: ' + (corr.changes?.load_time_ms?.change > 0 ? '+' : '') + (corr.changes?.load_time_ms?.change || 0) + 'ms</span>';
            html += '</div>';
            html += '<small style="color: var(--gray);">Installed: ' + formatDate(corr.installed_on) + ' | Confidence: ' + corr.confidence + '%</small>';
            html += '</div></div>';
        });
    }

    if (rankings.rankings && rankings.rankings.length > 0) {
        html += '<h4 style="margin: 20px 0 12px;">📊 App Impact Ranking</h4>';
        html += '<div class="table-container"><table><thead><tr><th>App</th><th>Impact Score</th><th>Perf Change</th><th>Load Time</th></tr></thead><tbody>';
        rankings.rankings.slice(0, 10).forEach(function (r) {
            var impactClass = r.is_negative_impact ? 'danger' : 'success';
            html += '<tr><td><strong>' + escapeHtml(r.app_name) + '</strong></td>';
            html += '<td><span class="badge badge-' + impactClass + '">' + (r.impact_score > 0 ? '+' : '') + r.impact_score + '</span></td>';
            html += '<td>' + (r.performance_change > 0 ? '+' : '') + r.performance_change + '</td>';
            html += '<td>' + (r.load_time_change_ms > 0 ? '+' : '') + r.load_time_change_ms + 'ms</td></tr>';
        });
        html += '</tbody></table></div>';
    }

    container.innerHTML = html || '<div class="empty-state"><h3>No timeline data yet</h3><p>Run some scans to build up performance history.</p></div>';
}

// Community Tab
async function loadCommunityInsights() {
    const container = document.getElementById('community-content');
    container.innerHTML = '<div class="loading"><div class="spinner"></div><p>Loading community insights...</p></div>';

    try {
        const insights = await api('/community/insights?shop=' + state.shop, { method: 'POST' });
        const trending = await api('/community/trending?months=3');
        renderCommunityInsights(insights, trending);
    } catch (error) {
        console.error('Load community insights error:', error);
        showError('Failed to load community insights');
    }
}

function renderCommunityInsights(insights, trending) {
    const container = document.getElementById('community-content');

    let html = '';

    var riskClass = insights.overall_risk === 'high' ? 'danger' : insights.overall_risk === 'medium' ? 'warning' : 'success';
    var riskIcon = insights.overall_risk === 'high' ? '🔴' : insights.overall_risk === 'medium' ? '🟡' : '🟢';

    html += '<div class="alert alert-' + riskClass + '" style="margin-bottom: 20px;">';
    html += '<span class="alert-icon">' + riskIcon + '</span>';
    html += '<div><strong>Overall Risk: ' + insights.overall_risk.toUpperCase() + '</strong>';
    html += '<p style="margin:0;">' + insights.apps_analyzed + ' apps analyzed, ' + insights.apps_with_known_issues + ' have known community issues</p></div></div>';

    if (insights.known_issues && insights.known_issues.length > 0) {
        html += '<h4 style="margin-bottom: 12px;">👥 Known Issues for Your Apps</h4>';
        insights.known_issues.forEach(function (issue) {
            html += '<div class="card" style="margin-bottom: 12px; padding: 16px;">';
            html += '<div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">';
            html += '<h4>📦 ' + escapeHtml(issue.app) + '</h4>';
            html += '<span class="badge badge-' + (issue.severity === 'high' ? 'danger' : issue.severity === 'medium' ? 'warning' : 'info') + '">' + issue.severity + ' severity</span>';
            html += '</div>';
            html += '<p style="margin-bottom: 8px; color: var(--gray);">' + issue.total_community_reports + ' community reports</p>';
            html += '<p style="margin-bottom: 8px;"><strong>Common symptoms:</strong></p>';
            html += '<ul style="margin-left: 20px; margin-bottom: 8px;">';
            issue.top_symptoms.forEach(function (s) {
                html += '<li>' + escapeHtml(s) + '</li>';
            });
            html += '</ul>';
            html += '<p style="color: var(--success);"><strong>Resolution:</strong> ' + escapeHtml(issue.typical_resolution) + '</p>';
            html += '<small style="color: var(--gray);">Resolution rate: ' + (issue.resolution_rate * 100).toFixed(0) + '%</small>';
            html += '</div>';
        });
    }

    if (trending.trending_issues && trending.trending_issues.length > 0) {
        html += '<h4 style="margin: 20px 0 12px;">🔥 Trending Issues</h4>';
        trending.trending_issues.forEach(function (issue) {
            var statusClass = issue.status === 'resolved' ? 'success' : issue.status === 'investigating' ? 'warning' : 'info';
            html += '<div class="alert alert-' + statusClass + '"><div>';
            html += '<strong>' + escapeHtml(issue.app) + '</strong> - ' + escapeHtml(issue.issue);
            html += '<p style="margin:0;"><small>' + issue.affected_users + ' affected users | Status: ' + issue.status + '</small></p>';
            html += '</div></div>';
        });
    }

    container.innerHTML = html || '<div class="empty-state"><h3>No community data available</h3></div>';
}


// ===== REPORT APP MODAL FUNCTIONS =====

function openReportModal() {
    const modal = document.getElementById('report-modal');
    if (modal) {
        modal.classList.remove('hidden');
        // Reset form
        document.getElementById('report-app-name').value = '';
        document.getElementById('report-issue-type').value = '';
        document.getElementById('report-when').value = '';
        document.getElementById('report-doing').value = '';
        document.getElementById('report-other-apps').value = '';
        document.getElementById('report-description').value = '';
        document.getElementById('report-results').classList.add('hidden');
        document.getElementById('report-submit-btn').classList.remove('loading');
        document.getElementById('report-submit-btn').textContent = '🔍 Search & Report';
    }
}

function closeReportModal() {
    const modal = document.getElementById('report-modal');
    if (modal) {
        modal.classList.add('hidden');
    }
}

// Close modal when clicking outside
document.addEventListener('click', function (e) {
    const modal = document.getElementById('report-modal');
    if (e.target === modal) {
        closeReportModal();
    }
});

// Close modal with Escape key
document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') {
        closeReportModal();
    }
});

async function submitAppReport() {
    const appName = document.getElementById('report-app-name').value.trim();
    const issueType = document.getElementById('report-issue-type').value;
    const when = document.getElementById('report-when').value;
    const doing = document.getElementById('report-doing').value;
    const otherApps = document.getElementById('report-other-apps').value.trim();
    const description = document.getElementById('report-description').value.trim();

    // Validation
    if (!appName) {
        alert('Please enter the app name');
        return;
    }
    if (!issueType) {
        alert('Please select an issue type');
        return;
    }
    if (!when) {
        alert('Please select when the issue started');
        return;
    }
    if (!doing) {
        alert('Please select what you were doing');
        return;
    }

    // Build description with context
    var fullDescription = description || '';
    fullDescription += '\n\nContext: Issue started ' + when.replace(/_/g, ' ') + '. Activity: ' + doing.replace(/_/g, ' ') + '.';
    if (otherApps) {
        fullDescription += '\n\nOther installed apps:\n' + otherApps;
    }

    // Show loading state
    const submitBtn = document.getElementById('report-submit-btn');
    submitBtn.classList.add('loading');
    submitBtn.textContent = 'Searching...';

    try {
        const params = new URLSearchParams({
            app_name: appName,
            shop: state.shop || 'anonymous',
            issue_type: issueType,
            description: fullDescription.trim()
        });

        const response = await fetch('/api/v1/reports/app?' + params.toString(), {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            }
        });

        const result = await response.json();

        if (response.ok) {
            showReportResults(result);
        } else {
            showReportError(result.detail || 'Failed to submit report');
        }
    } catch (error) {
        console.error('Report error:', error);
        showReportError('Network error. Please try again.');
    } finally {
        submitBtn.classList.remove('loading');
        submitBtn.textContent = '🔍 Search & Report';
    }
}

function showReportResults(result) {
    const resultsDiv = document.getElementById('report-results');
    resultsDiv.classList.remove('hidden', 'error');

    const redditData = result.reddit_data || {};
    const riskScore = redditData.risk_score || 0;
    const postsFound = redditData.posts_found || 0;
    const sentiment = redditData.sentiment || 'unknown';
    const commonIssues = redditData.common_issues || [];

    var riskLevel = 'low';
    var riskText = 'Low Risk';
    if (riskScore >= 70) {
        riskLevel = 'high';
        riskText = 'High Risk';
    } else if (riskScore >= 40) {
        riskLevel = 'medium';
        riskText = 'Medium Risk';
    }

    var issuesHtml = '';
    if (commonIssues.length > 0) {
        issuesHtml = '<div class="issue-list">';
        commonIssues.slice(0, 5).forEach(function (i) {
            issuesHtml += '<span class="issue-tag">' + i.issue + ' (' + i.mentions + ')</span>';
        });
        issuesHtml += '</div>';
    }

    resultsDiv.innerHTML =
        '<h4>✅ Report Submitted - Reddit Findings</h4>' +
        '<div class="reddit-findings">' +
        '<div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px;">' +
        '<span><strong>' + result.app_name + '</strong></span>' +
        '<span class="risk-badge ' + riskLevel + '">' + riskText + ' (' + riskScore + '/100)</span>' +
        '</div>' +
        '<p style="margin: 0; font-size: 0.9rem; color: #6b7280;">📊 ' + postsFound + ' Reddit posts found (past 12 months) • Sentiment: ' + sentiment + '</p>' +
        '<p style="margin: 4px 0 0 0; font-size: 0.8rem; color: #9ca3af;">🔍 Searched: r/shopify, r/ecommerce, r/shopifydev</p>' +
        issuesHtml +
        (redditData.recommendation ? '<p style="margin: 12px 0 0 0; font-size: 0.85rem; color: #374151;">💡 ' + redditData.recommendation + '</p>' : '') +
        '</div>' +
        '<p style="margin-top: 15px; font-size: 0.85rem; color: #059669;">' +
        (result.is_new_report ? 'This is the first report for this app.' : 'Total reports: ' + result.total_reports) +
        '</p>';
}

function showReportError(message) {
    const resultsDiv = document.getElementById('report-results');
    resultsDiv.classList.remove('hidden');
    resultsDiv.classList.add('error');
    resultsDiv.innerHTML = '<h4>❌ Error</h4><p>' + message + '</p>';
}

async function loadMostReportedApps() {
    const container = document.getElementById('most-reported-apps');
    if (!container) return;

    container.innerHTML = '<div class="loading"><div class="spinner"></div><p>Loading reported apps...</p></div>';

    try {
        const response = await fetch('/api/v1/reports/most-reported?limit=10');
        const result = await response.json();

        if (result.apps && result.apps.length > 0) {
            var html = '';
            result.apps.forEach(function (app) {
                var riskClass = app.reddit_risk_score >= 70 ? 'high' : app.reddit_risk_score >= 40 ? 'medium' : 'low';
                html += '<div class="reported-app-item">' +
                    '<div class="reported-app-info">' +
                    '<div class="reported-app-name">' + app.app_name + '</div>' +
                    '<div class="reported-app-meta">' +
                    app.total_reports + ' report' + (app.total_reports !== 1 ? 's' : '') + ' • ' +
                    (app.reddit_posts_found || 0) + ' Reddit posts • Sentiment: ' + (app.reddit_sentiment || 'unknown') +
                    '</div>' +
                    '</div>' +
                    '<div class="reported-app-score">' +
                    '<span class="risk-badge ' + riskClass + '">' + (app.reddit_risk_score || 0) + '/100</span>' +
                    '</div>' +
                    '</div>';
            });
            container.innerHTML = html;
        } else {
            container.innerHTML =
                '<div class="empty-state">' +
                '<div class="empty-state-icon">📭</div>' +
                '<h3>No Reports Yet</h3>' +
                '<p>Be the first to report a problematic app!</p>' +
                '<button class="btn btn-primary btn-sm" onclick="openReportModal()" style="margin-top: 10px;">🚨 Report an App</button>' +
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
// ==================== Monitoring Functions ====================

async function runMonitoringScan() {
    const btn = document.getElementById('monitoring-scan-btn');
    btn.classList.add('loading');
    btn.textContent = 'Scanning...';
    btn.disabled = true;

    const latestContainer = document.getElementById('monitoring-latest');
    latestContainer.innerHTML =
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
            renderMonitoringResults(result);
            loadMonitoringHistory();
            showNotification('Monitoring scan completed!', 'success');
        } else {
            throw new Error(result.detail || 'Scan failed');
        }
    } catch (error) {
        console.error('Monitoring scan error:', error);
        latestContainer.innerHTML =
            '<div class="empty-state">' +
            '<div class="empty-state-icon">❌</div>' +
            '<h3>Scan Failed</h3>' +
            '<p>' + error.message + '</p>' +
            '</div>';
        showNotification('Monitoring scan failed: ' + error.message, 'error');
    } finally {
        btn.classList.remove('loading');
        btn.textContent = '📸 Run Monitoring Scan';
        btn.disabled = false;
    }
}

function renderMonitoringResults(result) {
    const latestContainer = document.getElementById('monitoring-latest');
    const detailsContainer = document.getElementById('monitoring-details');
    const scriptsCard = document.getElementById('monitoring-scripts-card');

    // Risk level styling
    var riskClass = 'success';
    var riskIcon = '✅';
    if (result.risk_level === 'high') {
        riskClass = 'danger';
        riskIcon = '⚠️';
    } else if (result.risk_level === 'medium') {
        riskClass = 'warning';
        riskIcon = '⚡';
    }

    // Build risk reasons list
    var reasonsHtml = '';
    if (result.risk_reasons && result.risk_reasons.length > 0) {
        reasonsHtml = '<ul class="risk-reasons">';
        result.risk_reasons.forEach(function (reason) {
            reasonsHtml += '<li>' + reason + '</li>';
        });
        reasonsHtml += '</ul>';
    }

    // Latest scan summary
    latestContainer.innerHTML =
        '<div class="monitoring-summary">' +
        '<div class="monitoring-header">' +
        '<div class="risk-indicator ' + riskClass + '">' +
        '<span class="risk-icon">' + riskIcon + '</span>' +
        '<span class="risk-text">' + (result.risk_level || 'low').toUpperCase() + ' RISK</span>' +
        '</div>' +
        '<div class="scan-time">Scanned: ' + formatDate(result.completed_at) + '</div>' +
        '</div>' +
        '<div class="monitoring-summary-text">' + (result.summary || 'No summary available.') + '</div>' +
        reasonsHtml +
        '<div class="monitoring-stats">' +
        '<div class="monitoring-stat">' +
        '<div class="monitoring-stat-value">' + (result.files_total || 0) + '</div>' +
        '<div class="monitoring-stat-label">Total Files</div>' +
        '</div>' +
        '<div class="monitoring-stat">' +
        '<div class="monitoring-stat-value ' + (result.files_new > 0 ? 'warning' : '') + '">' + (result.files_new || 0) + '</div>' +
        '<div class="monitoring-stat-label">New Files</div>' +
        '</div>' +
        '<div class="monitoring-stat">' +
        '<div class="monitoring-stat-value ' + (result.files_changed > 0 ? 'warning' : '') + '">' + (result.files_changed || 0) + '</div>' +
        '<div class="monitoring-stat-label">Changed Files</div>' +
        '</div>' +
        '<div class="monitoring-stat">' +
        '<div class="monitoring-stat-value ' + (result.css_issues_found > 0 ? 'danger' : '') + '">' + (result.css_issues_found || 0) + '</div>' +
        '<div class="monitoring-stat-label">CSS Issues</div>' +
        '</div>' +
        '<div class="monitoring-stat">' +
        '<div class="monitoring-stat-value">' + (result.scripts_total || 0) + '</div>' +
        '<div class="monitoring-stat-label">Scripts</div>' +
        '</div>' +
        '</div>' +
        '</div>';

    // Show details section
    detailsContainer.style.display = 'grid';
    scriptsCard.style.display = 'block';

    // Load detailed data
    loadMonitoringScanDetails(result.scan_id);
}

async function loadMonitoringScanDetails(scanId) {
    try {
        const response = await fetch('/api/v1/monitoring/scan/' + scanId);
        const data = await response.json();

        // Render file changes
        const filesContainer = document.getElementById('monitoring-files');
        if (data.changed_files && data.changed_files.length > 0) {
            var filesHtml = '<ul class="file-list">';
            data.changed_files.forEach(function (file) {
                filesHtml += '<li class="file-item changed">' +
                    '<span class="file-icon">📝</span>' +
                    '<span class="file-path">' + file.file_path + '</span>' +
                    (file.is_app_owned ? '<span class="badge badge-warning">App-owned</span>' : '') +
                    '</li>';
            });
            filesHtml += '</ul>';
            filesContainer.innerHTML = filesHtml;
        } else if (data.new_files && data.new_files.length > 0) {
            var filesHtml = '<ul class="file-list">';
            data.new_files.slice(0, 20).forEach(function (file) {
                filesHtml += '<li class="file-item new">' +
                    '<span class="file-icon">🆕</span>' +
                    '<span class="file-path">' + file.file_path + '</span>' +
                    (file.is_app_owned ? '<span class="badge badge-warning">App-owned</span>' : '') +
                    '</li>';
            });
            if (data.new_files.length > 20) {
                filesHtml += '<li class="file-item">... and ' + (data.new_files.length - 20) + ' more files</li>';
            }
            filesHtml += '</ul>';
            filesContainer.innerHTML = filesHtml;
        } else {
            filesContainer.innerHTML = '<p class="text-muted">No file changes in this scan.</p>';
        }

        // Render CSS issues
        const cssContainer = document.getElementById('monitoring-css');
        if (data.non_namespaced_css && data.non_namespaced_css.length > 0) {
            var cssHtml = '<ul class="css-issues-list">';
            data.non_namespaced_css.slice(0, 10).forEach(function (issue) {
                var severityClass = issue.severity === 'high' ? 'danger' : issue.severity === 'medium' ? 'warning' : 'info';
                cssHtml += '<li class="css-issue">' +
                    '<div class="css-issue-header">' +
                    '<code class="css-selector">' + escapeHtml(issue.selector) + '</code>' +
                    '<span class="badge badge-' + severityClass + '">' + issue.severity + '</span>' +
                    '</div>' +
                    '<div class="css-issue-file">' + issue.file + '</div>' +
                    '<div class="css-issue-desc">' + issue.description + '</div>' +
                    '</li>';
            });
            if (data.non_namespaced_css.length > 10) {
                cssHtml += '<li class="css-issue">... and ' + (data.non_namespaced_css.length - 10) + ' more issues</li>';
            }
            cssHtml += '</ul>';
            cssContainer.innerHTML = cssHtml;
        } else {
            cssContainer.innerHTML = '<p class="text-muted text-success">✅ No CSS conflict risks detected.</p>';
        }

        // Render scripts
        const scriptsContainer = document.getElementById('monitoring-scripts');
        if (data.new_scripts && data.new_scripts.length > 0) {
            var scriptsHtml = '<ul class="scripts-list">';
            data.new_scripts.forEach(function (script) {
                scriptsHtml += '<li class="script-item new">' +
                    '<span class="script-icon">🆕</span>' +
                    '<span class="script-src">' + truncateUrl(script.src) + '</span>' +
                    (script.likely_app ? '<span class="badge badge-info">' + script.likely_app + '</span>' : '') +
                    '</li>';
            });
            scriptsHtml += '</ul>';
            scriptsContainer.innerHTML = scriptsHtml;
        } else {
            scriptsContainer.innerHTML = '<p class="text-muted">No new scripts detected in this scan.</p>';
        }

    } catch (error) {
        console.error('Error loading scan details:', error);
    }
}

async function loadMonitoringHistory() {
    const container = document.getElementById('monitoring-history');
    container.innerHTML = '<div class="loading"><div class="spinner"></div><p>Loading history...</p></div>';

    try {
        const response = await fetch('/api/v1/monitoring/scans/' + state.shop + '?limit=10');
        const data = await response.json();

        if (data.scans && data.scans.length > 0) {
            var html = '<div class="table-container"><table><thead><tr>' +
                '<th>Date</th><th>Risk</th><th>Files Changed</th><th>New Files</th><th>CSS Issues</th><th>Scripts</th>' +
                '</tr></thead><tbody>';

            data.scans.forEach(function (scan) {
                var riskClass = scan.risk_level === 'high' ? 'danger' : scan.risk_level === 'medium' ? 'warning' : 'success';
                html += '<tr onclick="viewMonitoringScan(\'' + scan.id + '\')" style="cursor: pointer;">' +
                    '<td>' + formatDate(scan.scan_date) + '</td>' +
                    '<td><span class="badge badge-' + riskClass + '">' + (scan.risk_level || 'low').toUpperCase() + '</span></td>' +
                    '<td>' + (scan.files_changed || 0) + '</td>' +
                    '<td>' + (scan.files_new || 0) + '</td>' +
                    '<td>' + (scan.css_issues_found || 0) + '</td>' +
                    '<td>' + (scan.scripts_new || 0) + ' new</td>' +
                    '</tr>';
            });

            html += '</tbody></table></div>';
            container.innerHTML = html;
        } else {
            container.innerHTML =
                '<div class="empty-state">' +
                '<div class="empty-state-icon">📅</div>' +
                '<h3>No Scan History</h3>' +
                '<p>Run your first monitoring scan to start tracking changes.</p>' +
                '</div>';
        }
    } catch (error) {
        console.error('Error loading monitoring history:', error);
        container.innerHTML =
            '<div class="empty-state">' +
            '<div class="empty-state-icon">❌</div>' +
            '<h3>Error Loading History</h3>' +
            '<p>Could not load scan history.</p>' +
            '</div>';
    }
}

async function loadLatestMonitoringScan() {
    try {
        const response = await fetch('/api/v1/monitoring/latest/' + state.shop);
        const data = await response.json();

        if (data.has_scan && data.scan) {
            renderMonitoringResults(data.scan);
        }
    } catch (error) {
        console.error('Error loading latest scan:', error);
    }
}

async function viewMonitoringScan(scanId) {
    try {
        const response = await fetch('/api/v1/monitoring/scan/' + scanId);
        const data = await response.json();

        // Format the data to match renderMonitoringResults expectations
        const result = {
            scan_id: data.id,
            risk_level: data.risk_level,
            risk_reasons: data.risk_reasons,
            summary: data.summary,
            files_total: data.files_total,
            files_new: data.files_new,
            files_changed: data.files_changed,
            css_issues_found: data.css_issues_found,
            scripts_total: data.scripts_total,
            scripts_new: data.scripts_new,
            completed_at: data.completed_at
        };

        renderMonitoringResults(result);
    } catch (error) {
        console.error('Error viewing scan:', error);
        showNotification('Failed to load scan details', 'error');
    }
}

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
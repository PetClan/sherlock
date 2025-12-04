# 🔍 Sherlock - Shopify App Diagnostics

**Find out which app is causing issues in your Shopify store.**

Sherlock is a diagnostic tool that helps Shopify merchants identify problematic apps by:
- Scanning installed apps and flagging suspects based on install date and known issues
- Analyzing theme code for conflicts and injected scripts
- Measuring performance impact of third-party apps
- Providing actionable recommendations

## Features

### Core Diagnostics
- **App Scanner**: Lists all installed apps, sorted by install date, with risk scoring
- **Theme Analyzer**: Detects code conflicts, duplicate scripts, and app-injected code
- **Performance Monitor**: Tracks load times, identifies slow resources and blocking scripts
- **Smart Diagnosis**: Combines all data to pinpoint the likely culprit
- **Scan History**: Track changes over time to see impact of app changes

### 🆕 Enhanced Features (v2.0)

#### ⚡ Conflict Detection
- **Known Conflicts Database** - 25+ documented app-to-app conflicts
- **Duplicate Functionality Detection** - Finds multiple apps doing the same thing
- **Community Report Integration** - Issues from Shopify forums, Reddit, etc.

#### 🧹 Orphan Code Scanner
- **Leftover Code Detection** - Finds code from uninstalled apps still in theme
- **12+ App Patterns** - Detects PageFly, GemPages, Shogun, Loox, and more
- **Cleanup Instructions** - Step-by-step guides to remove orphan code

#### 📈 Timeline Analysis
- **Before/After Comparison** - See performance changes after each app install
- **Impact Ranking** - Apps ranked by negative performance impact
- **Suggested Removal Order** - Data-driven order for testing app removals

#### 👥 Community Insights
- **15+ App Reports** - Detailed community reports for popular apps
- **Common Symptoms** - Known issues and their causes
- **Resolution Rates** - How often issues get resolved
- **Trending Issues** - Currently active problems in the community

## Tech Stack

- **Backend**: Python 3.11+, FastAPI
- **Database**: SQLAlchemy (async) with SQLite/PostgreSQL
- **Shopify**: Official Shopify Admin API

## Quick Start

### 1. Clone and Setup

```bash
cd sherlock
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Configure Environment

```bash
cp .env.example .env
# Edit .env with your Shopify app credentials
```

### 3. Run the Server

```bash
python main.py
# Or with uvicorn directly:
uvicorn main:app --reload
```

### 4. Access the API

- API Docs: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc
- Health Check: http://localhost:8000/health

## API Endpoints

### Authentication
- `GET /auth/shopify?shop=XXX` - Start OAuth flow
- `POST /auth/shopify/install` - Get install URL (JSON)
- `GET /auth/callback` - OAuth callback (Shopify redirects here)
- `GET /auth/verify?shop=XXX` - Check if app is installed
- `GET /auth/success` - Success page after install

### Scanning
- `POST /api/v1/scan/start` - Start a diagnostic scan
- `GET /api/v1/scan/{diagnosis_id}` - Get scan status
- `GET /api/v1/scan/{diagnosis_id}/report` - Get full report
- `GET /api/v1/scan/history/{shop}` - Get scan history

### Apps
- `GET /api/v1/apps/{shop}` - Get all installed apps with risk analysis
- `GET /api/v1/apps/{shop}/suspects` - Get only flagged suspect apps

### Theme Issues
- `GET /api/v1/theme-issues/{shop}` - Get detected theme conflicts

### Performance
- `GET /api/v1/performance/{shop}` - Get performance history
- `GET /api/v1/performance/{shop}/latest` - Get latest performance snapshot

### Webhooks (Shopify calls these)
- `POST /auth/webhooks/app/uninstalled` - App uninstall handler
- `POST /auth/webhooks/shop/update` - Shop update handler
- `POST /auth/webhooks/customers/data_request` - GDPR data request
- `POST /auth/webhooks/customers/redact` - GDPR customer redact
- `POST /auth/webhooks/shop/redact` - GDPR shop redact

### GDPR Compliance (Manual)
- `POST /api/v1/gdpr/customers/redact` - Customer data deletion
- `POST /api/v1/gdpr/shop/redact` - Shop data deletion
- `POST /api/v1/stores/deregister` - App uninstall handler

### 🆕 Enhanced Endpoints (v2.0)

#### Conflict Detection
- `POST /api/v1/conflicts/check?shop=XXX` - Check for known app conflicts

#### Orphan Code
- `POST /api/v1/orphan-code/scan?shop=XXX` - Scan for leftover code
- `GET /api/v1/orphan-code/cleanup/{app_name}` - Get cleanup instructions

#### Timeline Analysis
- `GET /api/v1/timeline/{shop}` - Get app install & performance timeline
- `GET /api/v1/timeline/{shop}/compare/{app_id}` - Before/after comparison
- `GET /api/v1/timeline/{shop}/impact-ranking` - Apps ranked by impact
- `GET /api/v1/timeline/{shop}/removal-order` - Suggested removal order

#### Community Insights
- `POST /api/v1/community/insights?shop=XXX` - Get insights for installed apps
- `GET /api/v1/community/app/{app_name}` - Detailed app report
- `GET /api/v1/community/trending` - Trending issues
- `POST /api/v1/community/match-symptoms` - Find apps matching symptoms

## Project Structure

```
sherlock/
├── app/
│   ├── core/
│   │   └── config.py         # Settings & environment
│   ├── db/
│   │   ├── database.py       # Database connection
│   │   └── models.py         # SQLAlchemy models
│   ├── api/
│   │   └── routers/
│   │       └── auth.py       # OAuth & webhooks
│   ├── services/
│   │   ├── app_scanner_service.py
│   │   ├── theme_analyzer_service.py
│   │   ├── performance_service.py
│   │   ├── diagnosis_service.py
│   │   ├── shopify_auth_service.py
│   │   ├── conflict_database.py      # 🆕 Known conflicts
│   │   ├── orphan_code_service.py    # 🆕 Orphan detection
│   │   ├── timeline_service.py       # 🆕 Timeline analysis
│   │   └── community_reports_service.py  # 🆕 Community data
│   └── models/               # Pydantic models
├── static/
│   ├── css/
│   │   └── style.css         # Dashboard styles
│   └── js/
│       └── app.js            # Dashboard JavaScript
├── templates/
│   ├── dashboard.html        # Main dashboard (with tabs)
│   └── install.html          # Install landing page
├── main.py                   # FastAPI app entry point
├── requirements.txt
├── .env.example
└── README.md
```

## Frontend Pages

| Page | URL | Description |
|------|-----|-------------|
| Install | `/install` | Landing page for new merchants |
| Dashboard | `/dashboard?shop=XXX` | Main diagnostic dashboard |
| API Docs | `/docs` | Swagger/OpenAPI documentation |

## Shopify App Scopes Required

- `read_themes` - To analyze theme code
- `read_products` - To test product pages
- `read_script_tags` - To detect injected scripts
- `read_content` - To access metafields and settings

## Shopify OAuth Setup

### 1. Create App in Shopify Partner Dashboard

1. Go to [partners.shopify.com](https://partners.shopify.com)
2. Create a new app (or use existing)
3. Set up App URL: `https://your-app.com`
4. Set up Redirect URL: `https://your-app.com/auth/callback`
5. Copy API Key and API Secret to your `.env` file

### 2. Configure Required Webhooks

In your Shopify Partner Dashboard, register these webhooks:

| Webhook Topic | Endpoint |
|---------------|----------|
| `app/uninstalled` | `/auth/webhooks/app/uninstalled` |
| `shop/update` | `/auth/webhooks/shop/update` |
| `customers/data_request` | `/auth/webhooks/customers/data_request` |
| `customers/redact` | `/auth/webhooks/customers/redact` |
| `shop/redact` | `/auth/webhooks/shop/redact` |

### 3. OAuth Flow

```
1. Merchant visits: /auth/shopify?shop=my-store.myshopify.com
2. Redirected to Shopify to approve permissions
3. Shopify redirects back to: /auth/callback?code=XXX&shop=XXX
4. App exchanges code for access token
5. Merchant redirected to success page
```

### 4. Testing OAuth Locally

For local development, use ngrok to create a tunnel:

```bash
ngrok http 8000
```

Then update your `.env`:
```
APP_URL=https://your-ngrok-url.ngrok.io
```

## License

MIT

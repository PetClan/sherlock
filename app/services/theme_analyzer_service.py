"""
Sherlock - Theme Analyzer Service
Analyzes Shopify theme code for conflicts, injected scripts, and issues
"""

from datetime import datetime
from typing import Optional, List, Dict, Any, Tuple
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import httpx
import re
import json

from app.db.models import Store, ThemeIssue


# Patterns that indicate app-injected code
APP_INJECTION_PATTERNS = [
    # Script injections
    (r'<script[^>]*src=["\'][^"\']*pagefly[^"\']*["\']', "PageFly", "injected_script"),
    (r'<script[^>]*src=["\'][^"\']*gempages[^"\']*["\']', "GemPages", "injected_script"),
    (r'<script[^>]*src=["\'][^"\']*shogun[^"\']*["\']', "Shogun", "injected_script"),
    (r'<script[^>]*src=["\'][^"\']*loox[^"\']*["\']', "Loox", "injected_script"),
    (r'<script[^>]*src=["\'][^"\']*judge\.?me[^"\']*["\']', "Judge.me", "injected_script"),
    (r'<script[^>]*src=["\'][^"\']*klaviyo[^"\']*["\']', "Klaviyo", "injected_script"),
    (r'<script[^>]*src=["\'][^"\']*privy[^"\']*["\']', "Privy", "injected_script"),
    (r'<script[^>]*src=["\'][^"\']*justuno[^"\']*["\']', "JustUno", "injected_script"),
    (r'<script[^>]*src=["\'][^"\']*bold[^"\']*["\']', "Bold", "injected_script"),
    (r'<script[^>]*src=["\'][^"\']*recharge[^"\']*["\']', "ReCharge", "injected_script"),
    (r'<script[^>]*src=["\'][^"\']*zipify[^"\']*["\']', "Zipify", "injected_script"),
    (r'<script[^>]*src=["\'][^"\']*vitals[^"\']*["\']', "Vitals", "injected_script"),
    (r'<script[^>]*src=["\'][^"\']*omnisend[^"\']*["\']', "Omnisend", "injected_script"),
    (r'<script[^>]*src=["\'][^"\']*yotpo[^"\']*["\']', "Yotpo", "injected_script"),
    (r'<script[^>]*src=["\'][^"\']*stamped[^"\']*["\']', "Stamped", "injected_script"),
    (r'<script[^>]*src=["\'][^"\']*tidio[^"\']*["\']', "Tidio", "injected_script"),
    (r'<script[^>]*src=["\'][^"\']*gorgias[^"\']*["\']', "Gorgias", "injected_script"),
    (r'<script[^>]*src=["\'][^"\']*weglot[^"\']*["\']', "Weglot", "injected_script"),
    (r'<script[^>]*src=["\'][^"\']*langify[^"\']*["\']', "Langify", "injected_script"),
    
    # Liquid includes/renders
    (r'{%\s*render\s+["\']pagefly[^"\']*["\']', "PageFly", "liquid_render"),
    (r'{%\s*render\s+["\']gempages[^"\']*["\']', "GemPages", "liquid_render"),
    (r'{%\s*include\s+["\']pagefly[^"\']*["\']', "PageFly", "liquid_include"),
    (r'{%\s*include\s+["\']gempages[^"\']*["\']', "GemPages", "liquid_include"),
    
       
    # Common problematic patterns
    (r'<script[^>]*>.*?document\.write', "Unknown", "document_write"),
    (r'<script[^>]*>.*?eval\s*\(', "Unknown", "eval_usage"),
]

# Files that commonly contain app code
CRITICAL_FILES = [
    "layout/theme.liquid",
    "layout/checkout.liquid",
    "templates/product.liquid",
    "templates/product.json",
    "templates/collection.liquid",
    "templates/collection.json",
    "templates/cart.liquid",
    "templates/cart.json",
    "templates/index.liquid",
    "templates/index.json",
    "snippets/",
    "sections/",
]

# Error patterns in Liquid code
LIQUID_ERROR_PATTERNS = [
    (r'{%\s*(?!end)[a-z]+[^%]*(?<!%)}(?!})', "Unclosed Liquid tag"),
    (r'{{[^}]*(?!}})$', "Unclosed Liquid output"),
    (r'{%\s*if\s+[^%]*%}(?!.*{%\s*endif\s*%})', "Missing endif"),
    (r'{%\s*for\s+[^%]*%}(?!.*{%\s*endfor\s*%})', "Missing endfor"),
]


class ThemeAnalyzerService:
    """Service for analyzing Shopify theme code"""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def fetch_theme_files(self, store: Store, theme_id: Optional[str] = None) -> Dict[str, str]:
        """
        Fetch theme files from Shopify Admin API
        Returns dict of {file_path: content}
        """
        if not store.access_token:
            print(f"⚠️ [ThemeAnalyzer] No access token for {store.shopify_domain}")
            return {}
        
        files = {}
        
        try:
            async with httpx.AsyncClient() as client:
                # Get active theme if no theme_id specified
                if not theme_id:
                    theme_id = await self._get_active_theme_id(client, store)
                    if not theme_id:
                        return {}
                
                # Fetch theme assets
                response = await client.get(
                    f"https://{store.shopify_domain}/admin/api/2024-01/themes/{theme_id}/assets.json",
                    headers={
                        "X-Shopify-Access-Token": store.access_token,
                        "Content-Type": "application/json"
                    },
                    timeout=30.0
                )
                
                if response.status_code != 200:
                    print(f"⚠️ [ThemeAnalyzer] Assets API error: {response.status_code}")
                    return {}
                
                assets = response.json().get("assets", [])
                
                # Fetch content of critical files
                for asset in assets:
                    key = asset.get("key", "")
                    
                    # Only fetch files we care about
                    if self._is_critical_file(key):
                        content = await self._fetch_asset_content(
                            client, store, theme_id, key
                        )
                        if content:
                            files[key] = content
                
                print(f"📁 [ThemeAnalyzer] Fetched {len(files)} theme files")
                return files
                
        except Exception as e:
            print(f"❌ [ThemeAnalyzer] Error fetching theme: {e}")
            return {}
    
    async def _get_active_theme_id(self, client: httpx.AsyncClient, store: Store) -> Optional[str]:
        """Get the active/published theme ID"""
        try:
            response = await client.get(
                f"https://{store.shopify_domain}/admin/api/2024-01/themes.json",
                headers={
                    "X-Shopify-Access-Token": store.access_token,
                    "Content-Type": "application/json"
                },
                timeout=30.0
            )
            
            if response.status_code == 200:
                themes = response.json().get("themes", [])
                for theme in themes:
                    if theme.get("role") == "main":
                        return str(theme.get("id"))
            
            return None
        except Exception as e:
            print(f"❌ [ThemeAnalyzer] Error getting theme ID: {e}")
            return None
    
    async def _fetch_asset_content(
        self, 
        client: httpx.AsyncClient, 
        store: Store, 
        theme_id: str, 
        key: str
    ) -> Optional[str]:
        """Fetch content of a single theme asset"""
        try:
            response = await client.get(
                f"https://{store.shopify_domain}/admin/api/2024-01/themes/{theme_id}/assets.json",
                params={"asset[key]": key},
                headers={
                    "X-Shopify-Access-Token": store.access_token,
                    "Content-Type": "application/json"
                },
                timeout=30.0
            )
            
            if response.status_code == 200:
                asset = response.json().get("asset", {})
                return asset.get("value")
            
            return None
        except:
            return None
    
    def _is_critical_file(self, key: str) -> bool:
        """Check if a file is one we should analyze"""
        # Always check .liquid and .json files in key directories
        if key.endswith(".liquid") or key.endswith(".json"):
            for critical in CRITICAL_FILES:
                if key.startswith(critical) or key == critical.rstrip("/"):
                    return True
        return False
    
    async def analyze_theme(self, store: Store, theme_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Full theme analysis:
        1. Fetch theme files
        2. Scan for app injections
        3. Check for conflicts
        4. Detect errors
        5. Store issues in database
        """
        print(f"🔍 [ThemeAnalyzer] Analyzing theme for {store.shopify_domain}")
        
        # Fetch theme files
        files = await self.fetch_theme_files(store, theme_id)
        
        if not files:
            return {
                "success": False,
                "error": "Could not fetch theme files",
                "issues": []
            }
        
        all_issues = []
        
        # Analyze each file
        for file_path, content in files.items():
            issues = await self._analyze_file(store, file_path, content, theme_id)
            all_issues.extend(issues)
        
        # Check for duplicate scripts across files
        duplicate_issues = await self._check_duplicate_scripts(store, files, theme_id)
        all_issues.extend(duplicate_issues)
        
        # Store issues in database
        for issue_data in all_issues:
            issue = ThemeIssue(
                store_id=store.id,
                theme_id=theme_id,
                theme_name=None,
                file_path=(issue_data.get("file_path") or "unknown")[:250],
                issue_type=(issue_data.get("issue_type") or "unknown")[:50],
                severity=issue_data.get("severity", "medium"),
                line_number=issue_data.get("line_number"),
                code_snippet=(issue_data.get("code_snippet") or "")[:250],
                likely_source=(issue_data.get("likely_source") or "")[:250] if issue_data.get("likely_source") else None,
                confidence=issue_data.get("confidence", 0.0)
            )
            self.db.add(issue)
        
        await self.db.flush()
        
        # Summarize by severity
        summary = {
            "critical": sum(1 for i in all_issues if i["severity"] == "critical"),
            "high": sum(1 for i in all_issues if i["severity"] == "high"),
            "medium": sum(1 for i in all_issues if i["severity"] == "medium"),
            "low": sum(1 for i in all_issues if i["severity"] == "low"),
        }
        
        print(f"✅ [ThemeAnalyzer] Found {len(all_issues)} issues")
        
        return {
            "success": True,
            "files_analyzed": len(files),
            "total_issues": len(all_issues),
            "by_severity": summary,
            "issues": all_issues,
            "apps_detected": list(set(
                i.get("likely_source") for i in all_issues 
                if i.get("likely_source") and i["likely_source"] != "Unknown"
            ))
        }
    
    async def _analyze_file(
        self, 
        store: Store, 
        file_path: str, 
        content: str,
        theme_id: Optional[str]
    ) -> List[Dict[str, Any]]:
        """Analyze a single file for issues"""
        issues = []
        
        if not content:
            return issues
        
        lines = content.split("\n")
        
        # Check for app injection patterns
        for pattern, app_name, issue_type in APP_INJECTION_PATTERNS:
            matches = list(re.finditer(pattern, content, re.IGNORECASE | re.DOTALL))
            
            for match in matches:
                # Find line number
                line_num = content[:match.start()].count("\n") + 1
                
                # Get code snippet (the line + context)
                start_line = max(0, line_num - 2)
                end_line = min(len(lines), line_num + 2)
                snippet = "\n".join(lines[start_line:end_line])
                
                # Determine severity
                severity = self._get_severity(issue_type, file_path)
                
                issues.append({
                    "file_path": file_path,
                    "issue_type": issue_type,
                    "severity": severity,
                    "line_number": line_num,
                    "code_snippet": snippet[:500],  # Limit size
                    "likely_source": app_name,
                    "confidence": 85.0 if app_name != "Unknown" else 50.0
                })
        
        # Check for Liquid syntax errors
        for pattern, error_desc in LIQUID_ERROR_PATTERNS:
            if re.search(pattern, content, re.MULTILINE):
                issues.append({
                    "file_path": file_path,
                    "issue_type": "syntax_error",
                    "severity": "high",
                    "likely_source": None,
                    "confidence": 60.0,
                    "code_snippet": error_desc
                })
        
        # Check for excessive inline scripts
        inline_scripts = re.findall(r'<script[^>]*>.*?</script>', content, re.DOTALL)
        if len(inline_scripts) > 5:
            issues.append({
                "file_path": file_path,
                "issue_type": "excessive_scripts",
                "severity": "medium",
                "likely_source": "Multiple apps",
                "confidence": 70.0,
                "code_snippet": f"Found {len(inline_scripts)} inline script blocks"
            })
        
        return issues
    
    async def _check_duplicate_scripts(
        self,
        store: Store,
        files: Dict[str, str],
        theme_id: Optional[str]
    ) -> List[Dict[str, Any]]:
        """Check for duplicate script includes across files"""
        issues = []
        script_sources = {}  # {script_url: [file_paths]}
        
        for file_path, content in files.items():
            # Find all script src attributes
            scripts = re.findall(r'<script[^>]*src=["\']([^"\']+)["\']', content, re.IGNORECASE)
            
            for src in scripts:
                if src not in script_sources:
                    script_sources[src] = []
                script_sources[src].append(file_path)
        
        # Find duplicates
        for src, paths in script_sources.items():
            if len(paths) > 1:
                # Use first file as the file_path (not the full list)
                primary_file = paths[0]
                
                # Create a short description
                snippet = f"Script '{src[:100]}' loaded in {len(paths)} files"
                
                issues.append({
                    "file_path": primary_file,
                    "issue_type": "duplicate_script",
                    "severity": "medium",
                    "likely_source": self._extract_app_from_url(src),
                    "confidence": 80.0,
                    "code_snippet": snippet
                })
        
        return issues
    
    def _get_severity(self, issue_type: str, file_path: str) -> str:
        """Determine severity based on issue type and location"""
        # Critical locations
        if "checkout" in file_path.lower():
            return "critical"
        
        if "theme.liquid" in file_path.lower():
            if issue_type in ["document_write", "eval_usage"]:
                return "critical"
            return "high"
        
        # Issue type severity
        severity_map = {
            "document_write": "high",
            "eval_usage": "high",
            "syntax_error": "high",
            "injected_script": "medium",
            "liquid_render": "medium",
            "liquid_include": "medium",
            "excessive_scripts": "medium",
            "duplicate_script": "medium",
            "app_block": "low",
            "app_section": "low",
        }
        
        return severity_map.get(issue_type, "medium")
    
    def _extract_app_from_url(self, url: str) -> str:
        """Extract app name from a script URL"""
        url_lower = url.lower()
        
        known_apps = [
            "pagefly", "gempages", "shogun", "loox", "klaviyo",
            "privy", "justuno", "bold", "recharge", "zipify",
            "vitals", "omnisend", "yotpo", "stamped", "tidio",
            "gorgias", "weglot", "langify", "judge.me", "judgeme"
        ]
        
        for app in known_apps:
            if app in url_lower:
                return app.title().replace(".", "")
        
        return "Unknown"
    
    async def get_issues_by_severity(
        self, 
        store: Store, 
        severity: Optional[str] = None
    ) -> List[ThemeIssue]:
        """Get theme issues, optionally filtered by severity"""
        query = select(ThemeIssue).where(
            ThemeIssue.store_id == store.id,
            ThemeIssue.is_resolved == False
        )
        
        if severity:
            query = query.where(ThemeIssue.severity == severity)
        
        query = query.order_by(ThemeIssue.detected_at.desc())
        
        result = await self.db.execute(query)
        return list(result.scalars().all())
    
    async def mark_issue_resolved(self, issue_id: str, notes: Optional[str] = None) -> bool:
        """Mark a theme issue as resolved"""
        result = await self.db.execute(
            select(ThemeIssue).where(ThemeIssue.id == issue_id)
        )
        issue = result.scalar_one_or_none()
        
        if issue:
            issue.is_resolved = True
            issue.resolved_at = datetime.utcnow()
            issue.resolution_notes = notes
            await self.db.flush()
            return True
        
        return False

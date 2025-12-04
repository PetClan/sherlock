"""
Sherlock - Orphan Code Detection Service
Finds leftover code from uninstalled apps that may still cause issues
"""

import re
from datetime import datetime
from typing import Optional, List, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import httpx

from app.db.models import Store, InstalledApp, ThemeIssue
from app.services.conflict_database import ConflictDatabase, ORPHAN_CODE_PATTERNS


class OrphanCodeService:
    """Service for detecting leftover code from uninstalled apps"""
    
    def __init__(self, db: AsyncSession):
        self.db = db
        self.conflict_db = ConflictDatabase()
    
    async def scan_for_orphan_code(self, store: Store) -> Dict[str, Any]:
        """
        Scan theme files for orphan code from uninstalled apps
        
        This finds code patterns that suggest an app was previously installed
        but may not be currently active, leaving behind dead code that
        slows down the store or causes conflicts.
        """
        print(f"🔍 [OrphanCode] Scanning for leftover code in {store.shopify_domain}")
        
        if not store.access_token:
            return {"success": False, "error": "No access token"}
        
        # Get currently installed apps
        result = await self.db.execute(
            select(InstalledApp).where(InstalledApp.store_id == store.id)
        )
        installed_apps = [app.app_name.lower() for app in result.scalars().all()]
        
        # Fetch theme files
        theme_files = await self._fetch_theme_files(store)
        
        if not theme_files:
            return {"success": False, "error": "Could not fetch theme files"}
        
        orphan_findings = []
        
        # Check each app's orphan patterns
        for pattern_data in ORPHAN_CODE_PATTERNS:
            app_name = pattern_data["app"].lower()
            
            # Skip if app is currently installed (not orphan)
            app_is_installed = any(app_name in installed for installed in installed_apps)
            
            # Scan files for patterns
            for file_path, content in theme_files.items():
                # Only check relevant files
                relevant_file = any(
                    f in file_path for f in pattern_data["files"]
                )
                
                if not relevant_file:
                    continue
                
                for pattern in pattern_data["patterns"]:
                    matches = list(re.finditer(pattern, content, re.IGNORECASE))
                    
                    if matches:
                        # Found pattern!
                        for match in matches[:3]:  # Limit to 3 examples per pattern
                            line_num = content[:match.start()].count("\n") + 1
                            
                            # Get context (the line containing the match)
                            lines = content.split("\n")
                            context_start = max(0, line_num - 2)
                            context_end = min(len(lines), line_num + 1)
                            snippet = "\n".join(lines[context_start:context_end])
                            
                            finding = {
                                "app": pattern_data["app"],
                                "app_installed": app_is_installed,
                                "is_orphan": not app_is_installed,
                                "file_path": file_path,
                                "line_number": line_num,
                                "pattern_matched": pattern,
                                "code_snippet": snippet[:300],
                                "cleanup_guide": pattern_data["cleanup_guide"],
                            }
                            
                            # Only add unique findings
                            if not any(
                                f["file_path"] == file_path and 
                                f["app"] == pattern_data["app"] and
                                f["line_number"] == line_num
                                for f in orphan_findings
                            ):
                                orphan_findings.append(finding)
        
        # Filter to only orphan code (from uninstalled apps)
        orphan_only = [f for f in orphan_findings if f["is_orphan"]]
        active_app_code = [f for f in orphan_findings if not f["is_orphan"]]
        
        # Store orphan issues in database
        for finding in orphan_only:
            issue = ThemeIssue(
                store_id=store.id,
                file_path=finding["file_path"],
                issue_type="orphan_code",
                severity="medium",
                line_number=finding["line_number"],
                code_snippet=finding["code_snippet"],
                likely_source=f"{finding['app']} (uninstalled)",
                confidence=85.0
            )
            self.db.add(issue)
        
        await self.db.flush()
        
        # Group findings by app
        orphan_by_app = {}
        for finding in orphan_only:
            app = finding["app"]
            if app not in orphan_by_app:
                orphan_by_app[app] = {
                    "app": app,
                    "files_affected": [],
                    "total_occurrences": 0,
                    "cleanup_guide": finding["cleanup_guide"],
                }
            orphan_by_app[app]["files_affected"].append(finding["file_path"])
            orphan_by_app[app]["total_occurrences"] += 1
        
        # Dedupe files
        for app_data in orphan_by_app.values():
            app_data["files_affected"] = list(set(app_data["files_affected"]))
        
        print(f"✅ [OrphanCode] Found {len(orphan_only)} orphan code instances from {len(orphan_by_app)} uninstalled apps")
        
        return {
            "success": True,
            "total_orphan_instances": len(orphan_only),
            "uninstalled_apps_with_leftover_code": len(orphan_by_app),
            "orphan_code_by_app": list(orphan_by_app.values()),
            "active_app_code_detected": len(active_app_code),
            "files_scanned": len(theme_files),
            "recommendations": self._generate_orphan_recommendations(orphan_by_app),
        }
    
    async def _fetch_theme_files(self, store: Store) -> Dict[str, str]:
        """Fetch theme files that commonly contain app code"""
        files = {}
        
        try:
            async with httpx.AsyncClient() as client:
                # Get active theme
                response = await client.get(
                    f"https://{store.shopify_domain}/admin/api/2024-01/themes.json",
                    headers={
                        "X-Shopify-Access-Token": store.access_token,
                        "Content-Type": "application/json"
                    },
                    timeout=30.0
                )
                
                if response.status_code != 200:
                    return {}
                
                themes = response.json().get("themes", [])
                theme_id = None
                for theme in themes:
                    if theme.get("role") == "main":
                        theme_id = str(theme.get("id"))
                        break
                
                if not theme_id:
                    return {}
                
                # Fetch asset list
                response = await client.get(
                    f"https://{store.shopify_domain}/admin/api/2024-01/themes/{theme_id}/assets.json",
                    headers={
                        "X-Shopify-Access-Token": store.access_token,
                        "Content-Type": "application/json"
                    },
                    timeout=30.0
                )
                
                if response.status_code != 200:
                    return {}
                
                assets = response.json().get("assets", [])
                
                # Files to check for orphan code
                target_files = [
                    "layout/theme.liquid",
                    "layout/checkout.liquid",
                    "config/settings_data.json",
                ]
                
                # Also check snippets and sections
                for asset in assets:
                    key = asset.get("key", "")
                    if key.startswith("snippets/") or key.startswith("sections/"):
                        target_files.append(key)
                    if key.startswith("templates/") and key.endswith(".liquid"):
                        target_files.append(key)
                
                # Fetch each file
                for key in target_files[:50]:  # Limit to 50 files
                    try:
                        response = await client.get(
                            f"https://{store.shopify_domain}/admin/api/2024-01/themes/{theme_id}/assets.json",
                            params={"asset[key]": key},
                            headers={
                                "X-Shopify-Access-Token": store.access_token,
                                "Content-Type": "application/json"
                            },
                            timeout=15.0
                        )
                        
                        if response.status_code == 200:
                            asset = response.json().get("asset", {})
                            content = asset.get("value")
                            if content:
                                files[key] = content
                    except:
                        continue
                
                return files
                
        except Exception as e:
            print(f"❌ [OrphanCode] Error fetching theme: {e}")
            return {}
    
    def _generate_orphan_recommendations(self, orphan_by_app: Dict) -> List[Dict[str, Any]]:
        """Generate recommendations for cleaning up orphan code"""
        recommendations = []
        
        for app_name, data in orphan_by_app.items():
            severity = "high" if data["total_occurrences"] > 5 else "medium"
            
            recommendations.append({
                "priority": 1 if severity == "high" else 2,
                "type": "cleanup_orphan_code",
                "app": app_name,
                "action": f"Remove leftover code from '{app_name}' - found in {len(data['files_affected'])} file(s)",
                "reason": f"This app appears to be uninstalled but left behind {data['total_occurrences']} code fragments",
                "impact": "May slow down store and cause unexpected behavior",
                "how_to_fix": data["cleanup_guide"],
                "files_to_check": data["files_affected"][:5],  # Limit to 5
            })
        
        # Sort by priority
        recommendations.sort(key=lambda x: x["priority"])
        
        return recommendations
    
    async def get_cleanup_instructions(self, app_name: str) -> Optional[Dict[str, Any]]:
        """Get detailed cleanup instructions for a specific app"""
        pattern_data = self.conflict_db.get_orphan_patterns(app_name)
        
        if not pattern_data:
            return None
        
        return {
            "app": pattern_data["app"],
            "patterns_to_search": pattern_data["patterns"],
            "files_to_check": pattern_data["files"],
            "cleanup_guide": pattern_data["cleanup_guide"],
            "steps": [
                f"1. Go to Online Store > Themes > Edit Code",
                f"2. Search for these patterns: {', '.join(pattern_data['patterns'][:3])}",
                f"3. Check these files: {', '.join(pattern_data['files'])}",
                f"4. {pattern_data['cleanup_guide']}",
                f"5. Save changes and test your store",
            ],
            "warning": "Always backup your theme before making changes!",
        }

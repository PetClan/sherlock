"""
Google Custom Search Service
Searches the web for Shopify app reviews, issues, and complaints
"""

import httpx
from typing import Optional, Dict, List, Any
from datetime import datetime
import os


class GoogleSearchService:
    """Service for searching Google for app reviews and issues"""
    
    BASE_URL = "https://www.googleapis.com/customsearch/v1"
    
    def __init__(self):
        self.api_key = os.getenv("GOOGLE_API_KEY")
        self.search_engine_id = os.getenv("GOOGLE_SEARCH_ENGINE_ID")
    
    def _is_configured(self) -> bool:
        """Check if API credentials are configured"""
        return bool(self.api_key and self.search_engine_id)
    
    async def search_app_reviews(self, app_name: str, limit: int = 10) -> Dict[str, Any]:
        """
        Search for reviews and complaints about a Shopify app
        """
        if not self._is_configured():
            return {
                "success": False,
                "error": "Google Search API not configured",
                "app_name": app_name
            }
        
        # Search query targeting reviews and issues
        query = f'"{app_name}" shopify app review OR issue OR problem OR slow OR conflict'
        
        return await self._perform_search(query, app_name, limit)
    async def search_reddit_discussions(self, app_name: str, limit: int = 10) -> Dict[str, Any]:
        """
        Search Reddit discussions about a Shopify app via Google
        Uses site:reddit.com to find Reddit posts
        """
        if not self._is_configured():
            return {
                "success": False,
                "error": "Google Search API not configured",
                "app_name": app_name,
                "posts": []
            }
        
        # Search Reddit specifically for app issues
        query = f'site:reddit.com "{app_name}" shopify (issue OR problem OR slow OR broken OR conflict OR review)'
        
        result = await self._perform_search(query, app_name, limit, search_type="reddit")
        
        # Transform results to match Reddit format expected by investigate endpoint
        if result.get("success"):
            posts = []
            for item in result.get("results", []):
                posts.append({
                    "title": item.get("title", ""),
                    "url": item.get("link", ""),
                    "snippet": item.get("snippet", ""),
                    "subreddit": self._extract_subreddit(item.get("link", "")),
                    "source": "google_reddit_search"
                })
            
            result["posts"] = posts
            result["risk_score"] = result.get("google_risk_score", 0) // 10  # Scale to 0-10
            result["negative_posts"] = result.get("sentiment", {}).get("negative", 0)
        
        return result
    
    def _extract_subreddit(self, url: str) -> str:
        """Extract subreddit name from Reddit URL"""
        try:
            # URL format: https://www.reddit.com/r/shopify/...
            if "/r/" in url:
                parts = url.split("/r/")[1].split("/")
                return parts[0] if parts else "unknown"
            return "unknown"
        except:
            return "unknown"
        
    async def search_app_conflicts(self, app_name: str, limit: int = 10) -> Dict[str, Any]:
        """
        Search specifically for app conflicts
        """
        if not self._is_configured():
            return {
                "success": False,
                "error": "Google Search API not configured",
                "app_name": app_name
            }
        
        query = f'"{app_name}" shopify conflict OR "doesn\'t work with" OR "breaks" OR "incompatible"'
        
        return await self._perform_search(query, app_name, limit, search_type="conflicts")
    
    async def search_app_alternatives(self, app_name: str, limit: int = 10) -> Dict[str, Any]:
        """
        Search for alternatives to an app
        """
        if not self._is_configured():
            return {
                "success": False,
                "error": "Google Search API not configured",
                "app_name": app_name
            }
        
        query = f'"{app_name}" shopify alternative OR "better than" OR "instead of" OR "switched from"'
        
        return await self._perform_search(query, app_name, limit, search_type="alternatives")
    
    async def _perform_search(
        self, 
        query: str, 
        app_name: str, 
        limit: int = 10,
        search_type: str = "reviews"
    ) -> Dict[str, Any]:
        """
        Perform the actual Google search
        """
        params = {
            "key": self.api_key,
            "cx": self.search_engine_id,
            "q": query,
            "num": min(limit, 10),  # Google allows max 10 per request
            "dateRestrict": "y2",  # Only results from last 2 years
        }
        
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.get(self.BASE_URL, params=params)
                
                if response.status_code == 403:
                    return {
                        "success": False,
                        "error": "API quota exceeded or invalid API key",
                        "app_name": app_name
                    }
                
                if response.status_code != 200:
                    return {
                        "success": False,
                        "error": f"Search failed with status {response.status_code}",
                        "app_name": app_name
                    }
                
                data = response.json()
                return self._parse_results(data, app_name, search_type)
                
        except httpx.TimeoutException:
            return {
                "success": False,
                "error": "Search request timed out",
                "app_name": app_name
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "app_name": app_name
            }
    
    def _parse_results(self, data: Dict, app_name: str, search_type: str) -> Dict[str, Any]:
        """
        Parse Google search results
        """
        items = data.get("items", [])
        search_info = data.get("searchInformation", {})
        
        results = []
        sources = set()
        
        for item in items:
            result = {
                "title": item.get("title", ""),
                "link": item.get("link", ""),
                "snippet": item.get("snippet", ""),
                "source": self._extract_domain(item.get("link", "")),
            }
            results.append(result)
            sources.add(result["source"])
        
        # Analyze sentiment from snippets
        sentiment_analysis = self._analyze_snippets(results)
        
        # Calculate risk score based on findings
        risk_score = self._calculate_risk_score(results, sentiment_analysis)
        
        return {
            "success": True,
            "app_name": app_name,
            "search_type": search_type,
            "total_results": int(search_info.get("totalResults", 0)),
            "results_returned": len(results),
            "results": results,
            "sources": list(sources),
            "sentiment": sentiment_analysis,
            "google_risk_score": risk_score,
            "fetched_at": datetime.utcnow().isoformat()
        }
    
    def _extract_domain(self, url: str) -> str:
        """Extract domain from URL"""
        try:
            from urllib.parse import urlparse
            parsed = urlparse(url)
            domain = parsed.netloc
            # Remove www. prefix
            if domain.startswith("www."):
                domain = domain[4:]
            return domain
        except:
            return "unknown"
    
    def _analyze_snippets(self, results: List[Dict]) -> Dict[str, Any]:
        """
        Analyze sentiment from search result snippets
        """
        positive_words = [
            'great', 'excellent', 'amazing', 'love', 'perfect', 'best', 
            'awesome', 'fantastic', 'helpful', 'easy', 'recommended', 
            'works great', 'no issues', 'smooth'
        ]
        negative_words = [
            'bad', 'terrible', 'awful', 'slow', 'broken', 'issue', 
            'problem', 'bug', 'worst', 'horrible', "doesn't work", 
            'not working', 'crash', 'conflict', 'broke', 'ruined',
            'frustrating', 'disappointed', 'avoid', 'warning'
        ]
        
        positive_count = 0
        negative_count = 0
        neutral_count = 0
        issues_found = []
        
        for result in results:
            snippet = result.get("snippet", "").lower()
            title = result.get("title", "").lower()
            combined = f"{title} {snippet}"
            
            pos = sum(1 for word in positive_words if word in combined)
            neg = sum(1 for word in negative_words if word in combined)
            
            if neg > pos:
                negative_count += 1
                # Extract potential issues
                for word in negative_words:
                    if word in combined and word not in ['bad', 'worst', 'terrible', 'awful', 'horrible']:
                        issues_found.append(word)
            elif pos > neg:
                positive_count += 1
            else:
                neutral_count += 1
        
        total = len(results)
        if total == 0:
            overall = "unknown"
        elif negative_count > positive_count:
            overall = "negative"
        elif positive_count > negative_count:
            overall = "positive"
        else:
            overall = "mixed"
        
        # Count issue occurrences
        issue_counts = {}
        for issue in issues_found:
            issue_counts[issue] = issue_counts.get(issue, 0) + 1
        
        # Sort by frequency
        common_issues = sorted(issue_counts.items(), key=lambda x: x[1], reverse=True)[:5]
        
        return {
            "overall": overall,
            "positive": positive_count,
            "negative": negative_count,
            "neutral": neutral_count,
            "total_analyzed": total,
            "common_issues": [{"issue": k, "mentions": v} for k, v in common_issues]
        }
    
    def _calculate_risk_score(self, results: List[Dict], sentiment: Dict) -> int:
        """
        Calculate risk score based on Google search findings
        0 = no risk, 100 = high risk
        """
        if not results:
            return 0  # No data, can't determine risk
        
        score = 0
        
        # Base score from sentiment
        negative_ratio = sentiment["negative"] / max(sentiment["total_analyzed"], 1)
        score += int(negative_ratio * 50)  # Up to 50 points from sentiment
        
        # Additional points for specific issues found
        issues = sentiment.get("common_issues", [])
        high_risk_issues = ['conflict', 'broke', 'crash', "doesn't work", 'not working']
        
        for issue_data in issues:
            issue = issue_data["issue"]
            mentions = issue_data["mentions"]
            if issue in high_risk_issues:
                score += min(mentions * 10, 30)  # Up to 30 points for critical issues
            else:
                score += min(mentions * 5, 20)  # Up to 20 points for other issues
        
        return min(score, 100)
    
    async def get_combined_app_insights(self, app_name: str) -> Dict[str, Any]:
        """
        Get comprehensive insights by combining multiple searches
        """
        # Run all searches
        reviews = await self.search_app_reviews(app_name, limit=10)
        conflicts = await self.search_app_conflicts(app_name, limit=5)
        
        if not reviews.get("success"):
            return reviews
        
        # Combine results
        all_sources = set(reviews.get("sources", []))
        if conflicts.get("success"):
            all_sources.update(conflicts.get("sources", []))
        
        # Combine issues
        all_issues = {}
        for issue in reviews.get("sentiment", {}).get("common_issues", []):
            all_issues[issue["issue"]] = all_issues.get(issue["issue"], 0) + issue["mentions"]
        if conflicts.get("success"):
            for issue in conflicts.get("sentiment", {}).get("common_issues", []):
                all_issues[issue["issue"]] = all_issues.get(issue["issue"], 0) + issue["mentions"]
        
        sorted_issues = sorted(all_issues.items(), key=lambda x: x[1], reverse=True)[:5]
        
        # Average risk score
        risk_scores = [reviews.get("google_risk_score", 0)]
        if conflicts.get("success"):
            risk_scores.append(conflicts.get("google_risk_score", 0))
        avg_risk = sum(risk_scores) // len(risk_scores)
        
        # Determine severity
        if avg_risk >= 70:
            severity = "high"
        elif avg_risk >= 40:
            severity = "medium"
        else:
            severity = "low"
        
        # Generate recommendation
        if avg_risk >= 70:
            recommendation = f"Multiple sources report significant issues with {app_name}. Consider alternatives or proceed with caution."
        elif avg_risk >= 40:
            recommendation = f"Some users have reported issues with {app_name}. Monitor for problems after installation."
        else:
            recommendation = f"Limited negative feedback found for {app_name}. Appears generally stable based on web search."
        
        return {
            "success": True,
            "app_name": app_name,
            "google_risk_score": avg_risk,
            "severity": severity,
            "total_results": reviews.get("total_results", 0),
            "results_analyzed": reviews.get("results_returned", 0),
            "sources": list(all_sources),
            "common_issues": [{"issue": k, "mentions": v} for k, v in sorted_issues],
            "sentiment": reviews.get("sentiment", {}).get("overall", "unknown"),
            "recommendation": recommendation,
            "fetched_at": datetime.utcnow().isoformat()
        }


# Create singleton instance
google_search_service = GoogleSearchService()
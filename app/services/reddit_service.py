"""
Sherlock - Reddit Integration Service
Fetches public data from r/shopify and r/ecommerce for app issues
"""

import asyncio
import httpx
from typing import Optional
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)


class RedditService:
    """Service for fetching Shopify app discussions from Reddit"""
    
    BASE_URL = "https://www.reddit.com"
    USER_AGENT = "Sherlock:v2.0 (Shopify App Diagnostics)"
    
    # Subreddits to search
    SUBREDDITS = ["shopify", "ecommerce", "shopifydev"]
    
    # Cache to avoid hitting rate limits
    _cache = {}
    _cache_ttl = timedelta(minutes=15)
    
    def __init__(self):
        self.client = None
    
    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client"""
        if self.client is None:
            self.client = httpx.AsyncClient(
                headers={"User-Agent": self.USER_AGENT},
                timeout=30.0,
                follow_redirects=True
            )
        return self.client
    
    async def close(self):
        """Close HTTP client"""
        if self.client:
            await self.client.aclose()
            self.client = None
    
    def _get_cache_key(self, query: str, subreddit: str) -> str:
        """Generate cache key"""
        return f"{subreddit}:{query.lower()}"
    
    def _is_cache_valid(self, cache_key: str) -> bool:
        """Check if cache entry is still valid"""
        if cache_key not in self._cache:
            return False
        cached_time, _ = self._cache[cache_key]
        return datetime.now() - cached_time < self._cache_ttl
    
    async def search_app_issues(
        self,
        app_name: str,
        limit: int = 25,
        time_filter: str = "year"
    ) -> dict:
        """
        Search Reddit for issues related to a Shopify app
        
        Args:
            app_name: Name of the app to search for
            limit: Maximum number of results per subreddit
            time_filter: Time range (hour, day, week, month, year, all)
        
        Returns:
            Dictionary with search results and analysis
        """
        all_posts = []
        
        for subreddit in self.SUBREDDITS:
            try:
                posts = await self._search_subreddit(
                    subreddit=subreddit,
                    query=f"{app_name} (issue OR problem OR bug OR slow OR conflict)",
                    limit=limit,
                    time_filter=time_filter
                )
                all_posts.extend(posts)
            except Exception as e:
                logger.warning(f"Error searching r/{subreddit}: {e}")
        
        # Analyze the posts
        analysis = self._analyze_posts(all_posts, app_name)
        
        return {
            "app_name": app_name,
            "total_posts_found": len(all_posts),
            "subreddits_searched": self.SUBREDDITS,
            "time_filter": time_filter,
            "posts": all_posts[:20],  # Return top 20
            "analysis": analysis,
            "searched_at": datetime.now().isoformat()
        }
    
    async def _search_subreddit(
        self,
        subreddit: str,
        query: str,
        limit: int = 25,
        time_filter: str = "year"
    ) -> list:
        """Search a specific subreddit"""
        cache_key = self._get_cache_key(query, subreddit)
        
        # Check cache
        if self._is_cache_valid(cache_key):
            _, cached_data = self._cache[cache_key]
            return cached_data
        
        client = await self._get_client()
        
        url = f"{self.BASE_URL}/r/{subreddit}/search.json"
        params = {
            "q": query,
            "restrict_sr": "1",  # Restrict to subreddit
            "sort": "relevance",
            "t": time_filter,
            "limit": limit
        }
        
        try:
            response = await client.get(url, params=params)
            response.raise_for_status()
            data = response.json()
            
            posts = []
            for child in data.get("data", {}).get("children", []):
                post_data = child.get("data", {})
                posts.append({
                    "id": post_data.get("id"),
                    "title": post_data.get("title"),
                    "subreddit": subreddit,
                    "score": post_data.get("score", 0),
                    "num_comments": post_data.get("num_comments", 0),
                    "created_utc": post_data.get("created_utc"),
                    "url": f"https://reddit.com{post_data.get('permalink', '')}",
                    "selftext": post_data.get("selftext", "")[:500],  # First 500 chars
                    "author": post_data.get("author"),
                })
            
            # Cache the results
            self._cache[cache_key] = (datetime.now(), posts)
            
            # Rate limiting - be nice to Reddit
            await asyncio.sleep(1)
            
            return posts
            
        except httpx.HTTPStatusError as e:
            logger.error(f"Reddit API error: {e.response.status_code}")
            return []
        except Exception as e:
            logger.error(f"Reddit search error: {e}")
            return []
    
    def _analyze_posts(self, posts: list, app_name: str) -> dict:
        """Analyze posts to extract insights"""
        if not posts:
            return {
                "sentiment": "unknown",
                "common_issues": [],
                "severity": "low",
                "recommendation": "No recent discussions found about this app."
            }
        
        # Count engagement
        total_score = sum(p.get("score", 0) for p in posts)
        total_comments = sum(p.get("num_comments", 0) for p in posts)
        
        # Extract common issue keywords
        issue_keywords = {
            "slow": 0,
            "crash": 0,
            "bug": 0,
            "conflict": 0,
            "broken": 0,
            "not working": 0,
            "error": 0,
            "problem": 0,
            "issue": 0,
            "support": 0,
            "refund": 0,
            "uninstall": 0,
        }
        
        positive_keywords = {
            "great": 0,
            "love": 0,
            "works": 0,
            "recommend": 0,
            "best": 0,
            "amazing": 0,
        }
        
        for post in posts:
            text = (post.get("title", "") + " " + post.get("selftext", "")).lower()
            for keyword in issue_keywords:
                if keyword in text:
                    issue_keywords[keyword] += 1
            for keyword in positive_keywords:
                if keyword in text:
                    positive_keywords[keyword] += 1
        
        # Determine common issues
        common_issues = [
            {"issue": k, "mentions": v}
            for k, v in sorted(issue_keywords.items(), key=lambda x: -x[1])
            if v > 0
        ][:5]
        
        # Calculate sentiment
        negative_count = sum(issue_keywords.values())
        positive_count = sum(positive_keywords.values())
        
        if negative_count > positive_count * 2:
            sentiment = "negative"
        elif positive_count > negative_count * 2:
            sentiment = "positive"
        else:
            sentiment = "mixed"
        
        # Determine severity
        if len(posts) > 10 and negative_count > 5:
            severity = "high"
        elif len(posts) > 5 and negative_count > 2:
            severity = "medium"
        else:
            severity = "low"
        
        # Generate recommendation
        if severity == "high":
            recommendation = f"Multiple users have reported issues with {app_name}. Consider reviewing alternatives or contacting support."
        elif severity == "medium":
            recommendation = f"Some users have reported issues with {app_name}. Monitor for problems after installation."
        else:
            recommendation = f"Limited negative feedback found for {app_name}. Appears to be generally stable."
        
        return {
            "sentiment": sentiment,
            "severity": severity,
            "total_engagement": total_score + total_comments,
            "posts_analyzed": len(posts),
            "common_issues": common_issues,
            "positive_mentions": positive_count,
            "negative_mentions": negative_count,
            "recommendation": recommendation
        }
    
    async def get_trending_issues(self, limit: int = 10) -> dict:
        """Get trending Shopify app issues from Reddit"""
        client = await self._get_client()
        
        all_posts = []
        
        # Search for general app issues
        queries = [
            "shopify app slow",
            "shopify app conflict",
            "shopify app problem",
            "shopify app broke",
        ]
        
        for query in queries:
            try:
                url = f"{self.BASE_URL}/r/shopify/search.json"
                params = {
                    "q": query,
                    "restrict_sr": "1",
                    "sort": "new",
                    "t": "month",
                    "limit": 10
                }
                
                response = await client.get(url, params=params)
                response.raise_for_status()
                data = response.json()
                
                for child in data.get("data", {}).get("children", []):
                    post_data = child.get("data", {})
                    all_posts.append({
                        "title": post_data.get("title"),
                        "score": post_data.get("score", 0),
                        "num_comments": post_data.get("num_comments", 0),
                        "created_utc": post_data.get("created_utc"),
                        "url": f"https://reddit.com{post_data.get('permalink', '')}",
                    })
                
                await asyncio.sleep(1)  # Rate limiting
                
            except Exception as e:
                logger.warning(f"Error fetching trending: {e}")
        
        # Sort by engagement and recency
        all_posts.sort(key=lambda x: x.get("score", 0) + x.get("num_comments", 0), reverse=True)
        
        # Remove duplicates
        seen_titles = set()
        unique_posts = []
        for post in all_posts:
            if post["title"] not in seen_titles:
                seen_titles.add(post["title"])
                unique_posts.append(post)
        
        return {
            "trending_issues": unique_posts[:limit],
            "fetched_at": datetime.now().isoformat()
        }
    
    async def check_app_reputation(self, app_name: str) -> dict:
        """
        Quick reputation check for an app
        Returns a simple risk assessment
        """
        results = await self.search_app_issues(app_name, limit=15, time_filter="year")
        
        analysis = results.get("analysis", {})
        posts_found = results.get("total_posts_found", 0)
        
        # Calculate risk score (0-100)
        risk_score = 0
        
        if posts_found > 20:
            risk_score += 20
        elif posts_found > 10:
            risk_score += 10
        
        if analysis.get("severity") == "high":
            risk_score += 40
        elif analysis.get("severity") == "medium":
            risk_score += 20
        
        if analysis.get("sentiment") == "negative":
            risk_score += 30
        elif analysis.get("sentiment") == "mixed":
            risk_score += 15
        
        negative_mentions = analysis.get("negative_mentions", 0)
        if negative_mentions > 10:
            risk_score += 20
        elif negative_mentions > 5:
            risk_score += 10
        
        # Cap at 100
        risk_score = min(risk_score, 100)
        
        return {
            "app_name": app_name,
            "reddit_risk_score": risk_score,
            "posts_found": posts_found,
            "sentiment": analysis.get("sentiment", "unknown"),
            "severity": analysis.get("severity", "unknown"),
            "common_issues": analysis.get("common_issues", [])[:3],
            "recommendation": analysis.get("recommendation", ""),
            "sample_posts": results.get("posts", [])[:5],
            "checked_at": datetime.now().isoformat()
        }


# Singleton instance
reddit_service = RedditService()
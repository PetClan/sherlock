"""
Sherlock - CSS Risk Detection Service
Scans CSS files for global/non-namespaced selectors that could break themes
"""

import re
from typing import Dict, Any, List, Optional
from dataclasses import dataclass


@dataclass
class CSSIssue:
    """Represents a CSS risk issue found"""
    file_path: str
    selector: str
    issue_type: str  # "global_class", "global_element", "important_override", "broad_selector"
    severity: str  # "low", "medium", "high"
    line_number: Optional[int] = None
    description: str = ""


class CSSRiskService:
    """Service for detecting risky CSS patterns that could break themes"""
    
    # Common element selectors that are risky when used globally
    RISKY_ELEMENT_SELECTORS = [
        "button", "input", "select", "textarea", "form",
        "a", "p", "h1", "h2", "h3", "h4", "h5", "h6",
        "ul", "ol", "li", "table", "tr", "td", "th",
        "div", "span", "section", "article", "header", "footer", "nav",
        "img", "video", "iframe"
    ]
    
    # Common class names that apps often use without namespacing
    RISKY_CLASS_SELECTORS = [
        "button", "btn", "btn-primary", "btn-secondary", "btn-submit",
        "container", "wrapper", "content", "inner", "outer",
        "header", "footer", "nav", "menu", "sidebar",
        "card", "box", "panel", "modal", "popup", "overlay",
        "title", "subtitle", "heading", "text", "label",
        "image", "img", "icon", "logo",
        "link", "active", "disabled", "hidden", "visible",
        "error", "success", "warning", "info",
        "form", "input", "field", "checkbox", "radio",
        "list", "item", "row", "column", "col", "grid",
        "slider", "carousel", "tab", "tabs", "accordion",
        "dropdown", "select", "option",
        "loading", "spinner", "loader",
        "close", "open", "toggle",
        "small", "medium", "large", "full", "half",
        "left", "right", "center", "top", "bottom"
    ]
    
    # Patterns that indicate properly namespaced CSS
    NAMESPACE_PATTERNS = [
        r"^\.[a-z]+-[a-z]+-",  # .app-name-component
        r"^\.[a-z]+__",  # .block__element (BEM)
        r"^\.[a-z]+--",  # .block--modifier (BEM)
        r"^\.shopify-",  # Shopify's own namespace
        r"^\#[a-z]+-[a-z]+-",  # #app-name-id
        r"^\[data-[a-z]+-",  # [data-app-attribute]
    ]
    
    def __init__(self):
        pass
    
    def extract_selectors(self, css_content: str) -> List[Dict[str, Any]]:
        """
        Extract all CSS selectors from content
        
        Args:
            css_content: Raw CSS content
            
        Returns:
            List of selector info dicts with selector, line_number
        """
        selectors = []
        
        # Remove comments
        css_no_comments = re.sub(r'/\*[\s\S]*?\*/', '', css_content)
        
        # Split by lines for line number tracking
        lines = css_no_comments.split('\n')
        
        current_line = 0
        for line in lines:
            current_line += 1
            
            # Find selectors (anything before {)
            # Match patterns like: .class { or element { or .class, .class2 {
            selector_match = re.match(r'^([^{]+)\{', line.strip())
            if selector_match:
                selector_text = selector_match.group(1).strip()
                
                # Split multiple selectors (comma-separated)
                individual_selectors = [s.strip() for s in selector_text.split(',')]
                
                for sel in individual_selectors:
                    if sel:
                        selectors.append({
                            "selector": sel,
                            "line_number": current_line
                        })
        
        # Also find selectors that span multiple lines or are in minified CSS
        # Pattern to match selector { ... }
        pattern = r'([^{}]+)\s*\{[^{}]*\}'
        for match in re.finditer(pattern, css_no_comments):
            selector_text = match.group(1).strip()
            individual_selectors = [s.strip() for s in selector_text.split(',')]
            
            for sel in individual_selectors:
                if sel and not any(s["selector"] == sel for s in selectors):
                    selectors.append({
                        "selector": sel,
                        "line_number": None  # Can't determine line in minified
                    })
        
        return selectors
    
    def is_namespaced(self, selector: str) -> bool:
        """
        Check if a selector appears to be properly namespaced
        
        Args:
            selector: CSS selector string
            
        Returns:
            True if appears namespaced, False otherwise
        """
        for pattern in self.NAMESPACE_PATTERNS:
            if re.match(pattern, selector, re.IGNORECASE):
                return True
        
        # Check for compound selectors that indicate scoping
        # e.g., ".my-app .button" is scoped, ".button" is not
        parts = selector.split()
        if len(parts) >= 2:
            # Has a parent selector, likely scoped
            return True
        
        return False
    
    def check_selector_risk(self, selector: str) -> Optional[Dict[str, Any]]:
        """
        Check if a selector is risky
        
        Args:
            selector: CSS selector string
            
        Returns:
            Risk info dict if risky, None if safe
        """
        selector_clean = selector.strip().lower()
        
        # Skip if already namespaced
        if self.is_namespaced(selector):
            return None
        
        # Skip @media, @keyframes, etc.
        if selector_clean.startswith('@'):
            return None
        
        # Skip :root and html/body (usually intentional)
        if selector_clean in [':root', 'html', 'body', '*']:
            return None
        
        # Check for bare element selectors
        for element in self.RISKY_ELEMENT_SELECTORS:
            if selector_clean == element:
                return {
                    "issue_type": "global_element",
                    "severity": "high",
                    "description": f"Bare element selector '{element}' affects all {element} elements on the page"
                }
        
        # Check for risky class selectors without namespace
        if selector_clean.startswith('.'):
            class_name = selector_clean[1:].split(':')[0].split('[')[0]  # Remove pseudo/attr
            
            if class_name in self.RISKY_CLASS_SELECTORS:
                return {
                    "issue_type": "global_class",
                    "severity": "high",
                    "description": f"Generic class '.{class_name}' may conflict with theme styles"
                }
            
            # Short generic class names are risky
            if len(class_name) <= 3 and class_name.isalpha():
                return {
                    "issue_type": "global_class",
                    "severity": "medium",
                    "description": f"Short generic class '.{class_name}' may conflict with other styles"
                }
        
        # Check for !important overrides
        # (This would need to be checked in the full rule, not just selector)
        
        return None
    
    def scan_css_content(self, css_content: str, file_path: str) -> List[CSSIssue]:
        """
        Scan CSS content for risky patterns
        
        Args:
            css_content: Raw CSS content
            file_path: Path to the CSS file (for reporting)
            
        Returns:
            List of CSSIssue objects
        """
        issues = []
        
        # Extract selectors
        selectors = self.extract_selectors(css_content)
        
        for sel_info in selectors:
            selector = sel_info["selector"]
            line_number = sel_info["line_number"]
            
            risk = self.check_selector_risk(selector)
            
            if risk:
                issue = CSSIssue(
                    file_path=file_path,
                    selector=selector,
                    issue_type=risk["issue_type"],
                    severity=risk["severity"],
                    line_number=line_number,
                    description=risk["description"]
                )
                issues.append(issue)
        
        # Check for !important usage
        important_count = len(re.findall(r'!important', css_content, re.IGNORECASE))
        if important_count > 5:
            issues.append(CSSIssue(
                file_path=file_path,
                selector="(multiple)",
                issue_type="important_override",
                severity="medium",
                description=f"Excessive use of !important ({important_count} times) may cause style conflicts"
            ))
        
        return issues
    
    def scan_theme_file(self, content: str, file_path: str) -> List[CSSIssue]:
        """
        Scan a theme file for CSS risks (handles both .css and .liquid files)
        
        Args:
            content: File content
            file_path: File path
            
        Returns:
            List of CSSIssue objects
        """
        issues = []
        
        # For .css files, scan directly
        if file_path.endswith('.css'):
            issues = self.scan_css_content(content, file_path)
        
        # For .liquid files, extract <style> blocks
        elif file_path.endswith('.liquid'):
            style_pattern = r'<style[^>]*>([\s\S]*?)</style>'
            for match in re.finditer(style_pattern, content, re.IGNORECASE):
                css_content = match.group(1)
                css_issues = self.scan_css_content(css_content, file_path)
                issues.extend(css_issues)
            
            # Also check for inline style={{ }} in schema or sections
            # This is Liquid-specific
        
        return issues
    
    def calculate_risk_score(self, issues: List[CSSIssue]) -> Dict[str, Any]:
        """
        Calculate overall CSS risk score from issues
        
        Args:
            issues: List of CSSIssue objects
            
        Returns:
            Risk assessment dict
        """
        if not issues:
            return {
                "score": 0,
                "level": "low",
                "summary": "No CSS risks detected"
            }
        
        # Score calculation
        score = 0
        high_count = 0
        medium_count = 0
        low_count = 0
        
        for issue in issues:
            if issue.severity == "high":
                score += 20
                high_count += 1
            elif issue.severity == "medium":
                score += 10
                medium_count += 1
            else:
                score += 5
                low_count += 1
        
        # Cap at 100
        score = min(score, 100)
        
        # Determine level
        if score >= 60 or high_count >= 3:
            level = "high"
        elif score >= 30 or high_count >= 1:
            level = "medium"
        else:
            level = "low"
        
        # Generate summary
        summary_parts = []
        if high_count > 0:
            summary_parts.append(f"{high_count} high-risk selectors")
        if medium_count > 0:
            summary_parts.append(f"{medium_count} medium-risk selectors")
        if low_count > 0:
            summary_parts.append(f"{low_count} low-risk selectors")
        
        summary = "Found " + ", ".join(summary_parts) if summary_parts else "No issues"
        
        return {
            "score": score,
            "level": level,
            "summary": summary,
            "high_count": high_count,
            "medium_count": medium_count,
            "low_count": low_count,
            "total_issues": len(issues)
        }
    
    def get_recommendations(self, issues: List[CSSIssue]) -> List[str]:
        """
        Generate recommendations based on CSS issues found
        
        Args:
            issues: List of CSSIssue objects
            
        Returns:
            List of recommendation strings
        """
        recommendations = []
        
        issue_types = set(i.issue_type for i in issues)
        
        if "global_element" in issue_types:
            recommendations.append(
                "Some CSS uses bare element selectors (e.g., 'button', 'input'). "
                "This can break your theme's styling. Contact the app developer "
                "to request properly namespaced CSS."
            )
        
        if "global_class" in issue_types:
            recommendations.append(
                "Some CSS uses generic class names that may conflict with your theme. "
                "Consider disabling the app's CSS injection or using custom CSS to override."
            )
        
        if "important_override" in issue_types:
            recommendations.append(
                "Excessive use of !important was detected. This can make it difficult "
                "to customize styles and may indicate poorly written CSS."
            )
        
        if not recommendations:
            recommendations.append("CSS appears to be properly namespaced. Low conflict risk.")
        
        return recommendations
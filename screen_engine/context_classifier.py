"""
J.A.R.V.I.S. — screen_engine/context_classifier.py
Classifies screen context from ScreenVision output into structured app context.
Used by SuggestionEngine and the gateway to understand what the user is doing.

Author: Hitansu Parichha | Nisum Technologies
Phase 5 — Blueprint v6.0
"""

from dataclasses import dataclass
from typing import Optional

# App categories
APP_CODING = "vscode"
APP_BROWSER = "browser"
APP_TERMINAL = "terminal"
APP_FILES = "finder"
APP_COMMUNICATION = "slack"
APP_DESIGN = "figma"
APP_MEDIA = "media_player"
APP_DOCUMENT = "pdf_viewer"
APP_OTHER = "other"

# Context types for routing
CONTEXT_CODE_EDITING = "code_editing"
CONTEXT_WEB_BROWSING = "web_browsing"
CONTEXT_SHOPPING = "shopping"
CONTEXT_TERMINAL_USE = "terminal_use"
CONTEXT_FILE_MANAGEMENT = "file_management"
CONTEXT_COMMUNICATION = "communication"
CONTEXT_READING = "reading"
CONTEXT_IDLE = "idle"
CONTEXT_UNKNOWN = "unknown"

# Shopping indicators
SHOPPING_KEYWORDS = [
    "flipkart", "amazon", "myntra", "meesho", "nykaa", "swiggy", "zomato",
    "cart", "checkout", "product", "buy now", "add to cart", "price",
    "rupees", "rs.", "₹", "offer", "discount", "delivery",
]

# Code file extensions
CODE_EXTENSIONS = [
    ".py", ".ts", ".tsx", ".js", ".jsx", ".java", ".go", ".rs", ".cpp",
    ".c", ".h", ".cs", ".rb", ".php", ".swift", ".kt", ".sql",
]

@dataclass
class ScreenContext:
    app: str                      # Primary app detected
    context_type: str             # One of the CONTEXT_* constants
    is_shopping: bool             # True if user is on a shopping site
    is_coding: bool               # True if user is writing code
    file_path: str                # Detected file path (empty if not coding)
    current_line: int             # Detected line number (0 if unknown)
    language: str                 # Programming language (empty if not coding)
    url: str                      # Detected URL (empty if not browser)
    site_name: str                # Detected site name (empty if not browser)
    raw_context: str              # The raw context string from ScreenVision
    raw_description: str          # The full description from ScreenVision
    suggestions: list[str]        # Suggestions from ScreenVision
    timestamp: str                # ISO 8601 timestamp

class ContextClassifier:
    def classify(self, vision_output: dict) -> ScreenContext:
        """
        Classify a vision output dict (from ScreenVision.capture_and_describe())
        into a structured ScreenContext.

        Args:
            vision_output: The dict returned by capture_and_describe().

        Returns:
            ScreenContext with all fields populated from available information.
        """
        app = vision_output.get("app_detected", "other").lower()
        context_str = vision_output.get("context", "").lower()
        description = vision_output.get("description", "").lower()
        suggestions = vision_output.get("suggestions", [])
        timestamp = vision_output.get("timestamp", "")

        # Combined text for analysis
        full_text = f"{context_str} {description}"

        # Determine context type
        context_type = self._classify_context_type(app, full_text)

        # Extract coding details
        is_coding = (app == APP_CODING or context_type == CONTEXT_CODE_EDITING)
        file_path, language = self._extract_file_info(full_text)
        current_line = self._extract_line_number(full_text)

        # Extract browser details
        is_shopping = self._detect_shopping(full_text)
        url, site_name = self._extract_url_info(full_text)

        return ScreenContext(
            app=app,
            context_type=context_type,
            is_shopping=is_shopping,
            is_coding=is_coding,
            file_path=file_path,
            current_line=current_line,
            language=language,
            url=url,
            site_name=site_name,
            raw_context=vision_output.get("context", ""),
            raw_description=vision_output.get("description", ""),
            suggestions=suggestions,
            timestamp=timestamp,
        )

    def _classify_context_type(self, app: str, text: str) -> str:
        """Classify what the user is doing based on app and screen text."""
        if app == APP_CODING:
            return CONTEXT_CODE_EDITING
        if app == APP_TERMINAL:
            return CONTEXT_TERMINAL_USE
        if app == APP_FILES:
            return CONTEXT_FILE_MANAGEMENT
        if app in (APP_COMMUNICATION, "slack", "notion"):
            return CONTEXT_COMMUNICATION
        if app == APP_DOCUMENT or app == APP_MEDIA:
            return CONTEXT_READING
        if app == APP_BROWSER:
            if self._detect_shopping(text):
                return CONTEXT_SHOPPING
            return CONTEXT_WEB_BROWSING
        # Heuristic fallback from text
        if any(ext in text for ext in CODE_EXTENSIONS):
            return CONTEXT_CODE_EDITING
        if any(kw in text for kw in SHOPPING_KEYWORDS):
            return CONTEXT_SHOPPING
        return CONTEXT_UNKNOWN

    def _extract_file_info(self, text: str) -> tuple[str, str]:
        """Extract file path and programming language from context text."""
        import re
        # Look for file patterns like "auth.ts", "main.py", "/src/components/Login.tsx"
        file_match = re.search(
            r'[\w/.-]+\.(' +
            '|'.join(ext.lstrip('.') for ext in CODE_EXTENSIONS) +
            r')', text
        )
        if file_match:
            file_name = file_match.group(0)
            ext = '.' + file_match.group(1)
            lang_map = {
                '.py': 'Python', '.ts': 'TypeScript', '.tsx': 'TypeScript/React',
                '.js': 'JavaScript', '.jsx': 'JavaScript/React', '.java': 'Java',
                '.go': 'Go', '.rs': 'Rust', '.cpp': 'C++', '.c': 'C',
                '.cs': 'C#', '.rb': 'Ruby', '.php': 'PHP', '.swift': 'Swift',
                '.kt': 'Kotlin', '.sql': 'SQL',
            }
            return file_name, lang_map.get(ext, ext.lstrip('.').upper())
        return "", ""

    def _extract_line_number(self, text: str) -> int:
        """Extract line number from context text like 'line 26' or ':26'."""
        import re
        match = re.search(r'line\s+(\d+)|:(\d+)', text)
        if match:
            num = match.group(1) or match.group(2)
            try:
                return int(num)
            except ValueError:
                pass
        return 0

    def _detect_shopping(self, text: str) -> bool:
        """Detect if the user is on a shopping site."""
        return any(kw in text.lower() for kw in SHOPPING_KEYWORDS)

    def _extract_url_info(self, text: str) -> tuple[str, str]:
        """Extract URL and site name from browser context."""
        import re
        url_match = re.search(r'https?://[\w./%-]+', text)
        if url_match:
            url = url_match.group(0)
            # Extract domain as site name
            domain_match = re.search(r'https?://([^/]+)', url)
            site = domain_match.group(1) if domain_match else ""
            return url, site
        # Try known site names without URL
        for site in SHOPPING_KEYWORDS:
            if site in text:
                return "", site
        return "", ""

    def to_memory_observation(self, context: ScreenContext) -> str:
        """
        Convert a ScreenContext to a string for ConversationLogger.log_screen_observation().
        Strips any sensitive data. Returns a concise observation string.
        """
        if context.context_type == CONTEXT_CODE_EDITING:
            lang = context.language or "code"
            file_info = f" ({context.file_path})" if context.file_path else ""
            line_info = f" at line {context.current_line}" if context.current_line else ""
            return f"User editing {lang}{file_info}{line_info}"

        if context.context_type == CONTEXT_SHOPPING:
            return f"User browsing shopping on {context.site_name or 'shopping site'}"

        if context.context_type == CONTEXT_WEB_BROWSING:
            site = context.site_name or "browser"
            return f"User browsing web on {site}"

        if context.context_type == CONTEXT_TERMINAL_USE:
            return "User working in terminal"

        if context.context_type == CONTEXT_FILE_MANAGEMENT:
            return "User managing files in Finder"

        if context.context_type == CONTEXT_COMMUNICATION:
            return f"User on {context.app}"

        return f"User on {context.app}: {context.raw_context[:100]}"

_classifier_instance: Optional[ContextClassifier] = None

def get_context_classifier() -> ContextClassifier:
    global _classifier_instance
    if _classifier_instance is None:
        _classifier_instance = ContextClassifier()
    return _classifier_instance

import pytest
from screen_engine.context_classifier import (
    ContextClassifier, ScreenContext, get_context_classifier,
    CONTEXT_CODE_EDITING, CONTEXT_SHOPPING, CONTEXT_TERMINAL_USE, CONTEXT_WEB_BROWSING
)

def test_context_classifier_initializes():
    cc = ContextClassifier()
    assert cc is not None

def test_classify_vscode_context():
    cc = ContextClassifier()
    res = cc.classify({"app_detected": "vscode", "context": "auth.ts line 26", "description": ""})
    assert res.app == "vscode"
    assert res.is_coding is True
    assert res.context_type == CONTEXT_CODE_EDITING

def test_classify_browser_shopping():
    cc = ContextClassifier()
    res = cc.classify({"app_detected": "browser", "context": "flipkart.com Samsung tablet", "description": ""})
    assert res.is_shopping is True
    assert res.context_type == CONTEXT_SHOPPING

def test_classify_terminal():
    cc = ContextClassifier()
    res = cc.classify({"app_detected": "terminal", "context": "running npm test", "description": ""})
    assert res.context_type == CONTEXT_TERMINAL_USE
    assert res.is_coding is False

def test_classify_browser_non_shopping():
    cc = ContextClassifier()
    res = cc.classify({"app_detected": "browser", "context": "stackoverflow.com python error", "description": ""})
    assert res.is_shopping is False
    assert res.context_type == CONTEXT_WEB_BROWSING

def test_extract_file_info_typescript():
    cc = ContextClassifier()
    path, lang = cc._extract_file_info("editing auth.ts at line 26")
    assert path == "auth.ts"
    assert lang == "TypeScript"

def test_extract_file_info_python():
    cc = ContextClassifier()
    path, lang = cc._extract_file_info("main.py function definition")
    assert path == "main.py"
    assert lang == "Python"

def test_extract_line_number_found():
    cc = ContextClassifier()
    assert cc._extract_line_number("editing line 42") == 42

def test_extract_line_number_colon_format():
    cc = ContextClassifier()
    assert cc._extract_line_number("auth.ts:26") == 26

def test_extract_line_number_not_found():
    cc = ContextClassifier()
    assert cc._extract_line_number("no line info here") == 0

def test_detect_shopping_flipkart():
    cc = ContextClassifier()
    assert cc._detect_shopping("browsing flipkart.com") is True

def test_detect_shopping_amazon():
    cc = ContextClassifier()
    assert cc._detect_shopping("amazon.in samsung phone") is True

def test_detect_shopping_non_shopping():
    cc = ContextClassifier()
    assert cc._detect_shopping("editing Python code in VS Code") is False

def test_to_memory_observation_code():
    cc = ContextClassifier()
    ctx = ScreenContext("vscode", CONTEXT_CODE_EDITING, False, True, "auth.ts", 26, "TypeScript", "", "", "", "", [], "")
    obs = cc.to_memory_observation(ctx)
    assert "TypeScript" in obs
    assert "auth.ts" in obs

def test_to_memory_observation_shopping():
    cc = ContextClassifier()
    ctx = ScreenContext("browser", CONTEXT_SHOPPING, True, False, "", 0, "", "", "flipkart", "", "", [], "")
    obs = cc.to_memory_observation(ctx)
    assert "flipkart" in obs

def test_get_context_classifier_singleton():
    a = get_context_classifier()
    b = get_context_classifier()
    assert a is b

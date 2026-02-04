"""
PHOENIX Translation Service

Provides bidirectional translation capabilities for foreign web content.
Supports automatic language detection and live form input translation.

Features:
- Automatic language detection from page content
- Page content translation (foreign → user language)
- Form input translation (user language → site language)
- JavaScript injection for live input handling
- Support for all major language pairs

Supported backends:
- MyMemory API (free, 5000 chars/day anonymous, 50000 with email)
- LibreTranslate (free, self-hostable)
- Google Translate API (paid, high quality) - requires API key
"""

import re
import json
import requests
from html.parser import HTMLParser
from functools import lru_cache
from typing import Optional, List, Dict, Tuple
from urllib.parse import quote

# Extended language support - all major world languages
SUPPORTED_LANGUAGES = {
    # Major Western European
    "en": "English",
    "es": "Spanish",
    "fr": "French",
    "de": "German",
    "it": "Italian",
    "pt": "Portuguese",
    "nl": "Dutch",
    "sv": "Swedish",
    "no": "Norwegian",
    "da": "Danish",
    "fi": "Finnish",
    "pl": "Polish",
    "cs": "Czech",
    "sk": "Slovak",
    "hu": "Hungarian",
    "ro": "Romanian",
    "bg": "Bulgarian",
    "hr": "Croatian",
    "sl": "Slovenian",
    "el": "Greek",

    # Eastern European / Cyrillic
    "ru": "Russian",
    "uk": "Ukrainian",
    "be": "Belarusian",
    "sr": "Serbian",

    # Asian
    "ja": "Japanese",
    "ko": "Korean",
    "zh": "Chinese (Simplified)",
    "zh-TW": "Chinese (Traditional)",
    "th": "Thai",
    "vi": "Vietnamese",
    "id": "Indonesian",
    "ms": "Malay",
    "tl": "Filipino",
    "my": "Burmese",
    "km": "Khmer",
    "lo": "Lao",

    # South Asian
    "hi": "Hindi",
    "bn": "Bengali",
    "ta": "Tamil",
    "te": "Telugu",
    "mr": "Marathi",
    "gu": "Gujarati",
    "kn": "Kannada",
    "ml": "Malayalam",
    "pa": "Punjabi",
    "ur": "Urdu",
    "ne": "Nepali",
    "si": "Sinhala",

    # Middle Eastern
    "ar": "Arabic",
    "he": "Hebrew",
    "fa": "Persian",
    "tr": "Turkish",

    # African
    "sw": "Swahili",
    "am": "Amharic",
    "ha": "Hausa",
    "yo": "Yoruba",
    "zu": "Zulu",
    "af": "Afrikaans",
}

# Language codes grouped by region for UI display
LANGUAGE_REGIONS = {
    "Western European": ["en", "es", "fr", "de", "it", "pt", "nl"],
    "Nordic": ["sv", "no", "da", "fi"],
    "Eastern European": ["pl", "cs", "sk", "hu", "ro", "bg", "hr", "sl", "el"],
    "Slavic": ["ru", "uk", "be", "sr"],
    "East Asian": ["ja", "ko", "zh", "zh-TW"],
    "Southeast Asian": ["th", "vi", "id", "ms", "tl", "my", "km", "lo"],
    "South Asian": ["hi", "bn", "ta", "te", "mr", "gu", "kn", "ml", "pa", "ur", "ne", "si"],
    "Middle Eastern": ["ar", "he", "fa", "tr"],
    "African": ["sw", "am", "ha", "yo", "zu", "af"],
}

# Translation API configuration
TRANSLATION_CONFIG = {
    "mymemory": {
        "enabled": True,
        "url": "https://api.mymemory.translated.net/get",
        "email": None,
    },
    "libretranslate": {
        "enabled": False,
        "url": "https://libretranslate.com/translate",
        "api_key": None,
    },
    "google": {
        "enabled": False,
        "api_key": None,
    },
}

# Enhanced language detection patterns
LANGUAGE_PATTERNS = {
    # East Asian
    "ja": re.compile(r'[\u3040-\u309F\u30A0-\u30FF]'),  # Hiragana + Katakana (unique to Japanese)
    "ko": re.compile(r'[\uAC00-\uD7AF\u1100-\u11FF]'),  # Hangul
    "zh": re.compile(r'[\u4E00-\u9FFF]'),  # CJK (Chinese characters - also used in Japanese)

    # South Asian
    "hi": re.compile(r'[\u0900-\u097F]'),  # Devanagari
    "bn": re.compile(r'[\u0980-\u09FF]'),  # Bengali
    "ta": re.compile(r'[\u0B80-\u0BFF]'),  # Tamil
    "te": re.compile(r'[\u0C00-\u0C7F]'),  # Telugu
    "gu": re.compile(r'[\u0A80-\u0AFF]'),  # Gujarati
    "kn": re.compile(r'[\u0C80-\u0CFF]'),  # Kannada
    "ml": re.compile(r'[\u0D00-\u0D7F]'),  # Malayalam
    "pa": re.compile(r'[\u0A00-\u0A7F]'),  # Gurmukhi (Punjabi)
    "si": re.compile(r'[\u0D80-\u0DFF]'),  # Sinhala

    # Southeast Asian
    "th": re.compile(r'[\u0E00-\u0E7F]'),  # Thai
    "my": re.compile(r'[\u1000-\u109F]'),  # Myanmar
    "km": re.compile(r'[\u1780-\u17FF]'),  # Khmer
    "lo": re.compile(r'[\u0E80-\u0EFF]'),  # Lao

    # Middle Eastern
    "ar": re.compile(r'[\u0600-\u06FF]'),  # Arabic
    "he": re.compile(r'[\u0590-\u05FF]'),  # Hebrew
    "fa": re.compile(r'[\u0600-\u06FF\uFB50-\uFDFF]'),  # Persian (Arabic script + extensions)

    # Cyrillic
    "ru": re.compile(r'[\u0400-\u04FF]'),  # Cyrillic

    # Greek
    "el": re.compile(r'[\u0370-\u03FF]'),  # Greek

    # African
    "am": re.compile(r'[\u1200-\u137F]'),  # Ethiopic (Amharic)
}

# Script to language mapping for disambiguation
SCRIPT_LANGUAGES = {
    "cyrillic": ["ru", "uk", "be", "bg", "sr"],
    "arabic": ["ar", "fa", "ur"],
    "devanagari": ["hi", "mr", "ne"],
}


def detect_language(text: str) -> str:
    """
    Detect language from text using character patterns.
    Uses script detection with heuristics for disambiguation.

    Args:
        text: Text to analyze

    Returns:
        ISO 639-1 language code (defaults to 'en' if unknown)
    """
    if not text or not text.strip():
        return "en"

    # Remove HTML tags for cleaner detection
    clean_text = re.sub(r'<[^>]+>', '', text)

    # Count characters matching each pattern
    scores = {}
    for lang, pattern in LANGUAGE_PATTERNS.items():
        matches = pattern.findall(clean_text)
        if matches:
            scores[lang] = len(matches)

    if not scores:
        # Check for Latin characters with accents for European languages
        if re.search(r'[àáâãäåæçèéêëìíîïñòóôõöùúûüý]', clean_text.lower()):
            # Could be Spanish, French, Portuguese, etc.
            # Default to detecting common words
            if re.search(r'\b(el|la|los|las|de|en|que|es|un|una)\b', clean_text.lower()):
                return "es"
            elif re.search(r'\b(le|la|les|de|du|des|et|est|un|une)\b', clean_text.lower()):
                return "fr"
            elif re.search(r'\b(der|die|das|und|ist|ein|eine|für)\b', clean_text.lower()):
                return "de"
        return "en"

    # Handle Japanese vs Chinese disambiguation
    if "ja" in scores and "zh" in scores:
        # If Hiragana/Katakana present, it's Japanese
        if scores.get("ja", 0) > 0:
            return "ja"
        return "zh"

    # Return highest scoring language
    return max(scores, key=scores.get)


def detect_language_from_html(html: str) -> str:
    """
    Detect language from HTML, checking lang attribute first.

    Args:
        html: HTML content

    Returns:
        ISO 639-1 language code
    """
    # Check html lang attribute
    lang_match = re.search(r'<html[^>]*\slang=["\']?([a-z]{2}(?:-[A-Z]{2})?)', html, re.IGNORECASE)
    if lang_match:
        lang = lang_match.group(1).lower().split('-')[0]
        if lang in SUPPORTED_LANGUAGES:
            return lang

    # Check Content-Language meta tag
    meta_match = re.search(r'<meta[^>]*http-equiv=["\']?Content-Language["\']?[^>]*content=["\']?([a-z]{2})', html, re.IGNORECASE)
    if meta_match:
        lang = meta_match.group(1).lower()
        if lang in SUPPORTED_LANGUAGES:
            return lang

    # Fall back to text detection
    text_only = re.sub(r'<[^>]+>', ' ', html)
    return detect_language(text_only)


def translate_mymemory(text: str, source: str, target: str) -> Optional[str]:
    """Translate using MyMemory API (free tier)."""
    config = TRANSLATION_CONFIG["mymemory"]
    if not config["enabled"]:
        return None

    # Handle language code variations
    source = source.replace("-", "_")
    target = target.replace("-", "_")

    try:
        params = {
            "q": text[:500],  # Limit to avoid API issues
            "langpair": f"{source}|{target}",
        }

        if config.get("email"):
            params["de"] = config["email"]

        response = requests.get(config["url"], params=params, timeout=10)

        if response.status_code == 200:
            data = response.json()
            if data.get("responseStatus") == 200:
                translated = data["responseData"]["translatedText"]
                # Check for untranslated response
                if translated and translated.upper() != text.upper():
                    return translated

    except Exception as e:
        print(f"MyMemory translation error: {e}")

    return None


def translate_libretranslate(text: str, source: str, target: str) -> Optional[str]:
    """Translate using LibreTranslate API."""
    config = TRANSLATION_CONFIG["libretranslate"]
    if not config["enabled"]:
        return None

    try:
        payload = {"q": text, "source": source, "target": target}
        if config.get("api_key"):
            payload["api_key"] = config["api_key"]

        response = requests.post(config["url"], json=payload, timeout=10)

        if response.status_code == 200:
            return response.json().get("translatedText")

    except Exception as e:
        print(f"LibreTranslate error: {e}")

    return None


@lru_cache(maxsize=2000)
def translate_text(text: str, source: str = "auto", target: str = "en") -> str:
    """
    Translate text with caching. Supports any language pair.

    Args:
        text: Text to translate
        source: Source language code ('auto' for detection)
        target: Target language code

    Returns:
        Translated text (original if translation fails)
    """
    if not text or not text.strip():
        return text

    # Auto-detect source if needed
    if source == "auto":
        source = detect_language(text)

    # Skip if same language
    if source == target:
        return text

    # Try backends
    result = translate_mymemory(text, source, target)
    if result:
        return result

    result = translate_libretranslate(text, source, target)
    if result:
        return result

    return text


def translate_form_input(text: str, user_lang: str, site_lang: str) -> str:
    """
    Translate user form input from user's language to site's language.
    Used for bidirectional translation when submitting forms.

    Args:
        text: User's input text
        user_lang: User's preferred language
        site_lang: Website's language

    Returns:
        Translated text in site's language
    """
    if not text or user_lang == site_lang:
        return text

    return translate_text(text, source=user_lang, target=site_lang)


def translate_form_data(form_data: Dict[str, str], user_lang: str, site_lang: str,
                        translate_fields: List[str] = None) -> Dict[str, str]:
    """
    Translate form data from user's language to site's language.

    Args:
        form_data: Dictionary of form field names to values
        user_lang: User's preferred language
        site_lang: Website's language
        translate_fields: List of field names to translate (None = translate all text fields)

    Returns:
        Dictionary with translated values
    """
    if user_lang == site_lang:
        return form_data

    # Fields that typically should NOT be translated
    skip_fields = {
        'email', 'password', 'phone', 'tel', 'zip', 'postal', 'code',
        'card', 'cvv', 'cvc', 'number', 'date', 'time', 'csrf', 'token',
        'id', 'hidden', 'submit', 'button'
    }

    # Fields that typically SHOULD be translated
    text_fields = {
        'name', 'firstname', 'first_name', 'lastname', 'last_name',
        'address', 'street', 'city', 'state', 'country', 'region',
        'message', 'comment', 'note', 'description', 'reason'
    }

    translated = {}
    for key, value in form_data.items():
        key_lower = key.lower()

        # Skip non-string or empty values
        if not isinstance(value, str) or not value.strip():
            translated[key] = value
            continue

        # Determine if field should be translated
        should_translate = False

        if translate_fields is not None:
            should_translate = key in translate_fields
        else:
            # Check if it's a text field that should be translated
            if any(skip in key_lower for skip in skip_fields):
                should_translate = False
            elif any(tf in key_lower for tf in text_fields):
                should_translate = True
            elif detect_language(value) == user_lang:
                # If value appears to be in user's language, translate it
                should_translate = True

        if should_translate:
            translated[key] = translate_form_input(value, user_lang, site_lang)
        else:
            translated[key] = value

    return translated


class HTMLTranslator(HTMLParser):
    """HTML parser that translates content while preserving structure."""

    def __init__(self, source: str, target: str):
        super().__init__()
        self.source = source
        self.target = target
        self.result = []
        self.skip_tags = {'script', 'style', 'code', 'pre', 'noscript'}
        self.skip_depth = 0
        self.in_head = False

    def handle_starttag(self, tag, attrs):
        if tag == 'head':
            self.in_head = True

        # Track nested skip tags
        if tag in self.skip_tags:
            self.skip_depth += 1

        # Build tag with potentially translated attributes
        attrs_list = []
        for name, value in attrs:
            if value is None:
                attrs_list.append(name)
            else:
                # Translate certain attributes
                if name in ('alt', 'title', 'placeholder', 'aria-label') and value and self.skip_depth == 0:
                    value = translate_text(value, self.source, self.target)
                # Escape quotes in value
                value = value.replace('"', '&quot;')
                attrs_list.append(f'{name}="{value}"')

        attrs_str = ' '.join(attrs_list)
        if attrs_str:
            self.result.append(f'<{tag} {attrs_str}>')
        else:
            self.result.append(f'<{tag}>')

    def handle_endtag(self, tag):
        self.result.append(f'</{tag}>')
        if tag == 'head':
            self.in_head = False
        if tag in self.skip_tags and self.skip_depth > 0:
            self.skip_depth -= 1

    def handle_data(self, data):
        # Skip translation for script/style content and head section
        if self.skip_depth > 0 or self.in_head or not data.strip():
            self.result.append(data)
        else:
            # Translate text content
            translated = translate_text(data, self.source, self.target)
            self.result.append(translated)

    def handle_comment(self, data):
        self.result.append(f'<!--{data}-->')

    def handle_decl(self, decl):
        self.result.append(f'<!{decl}>')

    def handle_startendtag(self, tag, attrs):
        attrs_list = []
        for name, value in attrs:
            if value is None:
                attrs_list.append(name)
            else:
                if name in ('alt', 'title', 'placeholder', 'aria-label') and value:
                    value = translate_text(value, self.source, self.target)
                value = value.replace('"', '&quot;')
                attrs_list.append(f'{name}="{value}"')

        attrs_str = ' '.join(attrs_list)
        if attrs_str:
            self.result.append(f'<{tag} {attrs_str}/>')
        else:
            self.result.append(f'<{tag}/>')

    def get_result(self):
        return ''.join(self.result)


def translate_html(html: str, source: str = "auto", target: str = "en") -> str:
    """
    Translate HTML content while preserving structure.

    Args:
        html: HTML content
        source: Source language ('auto' for detection)
        target: Target language

    Returns:
        Translated HTML
    """
    if not html:
        return html

    if source == "auto":
        source = detect_language_from_html(html)

    if source == target:
        return html

    try:
        translator = HTMLTranslator(source, target)
        translator.feed(html)
        return translator.get_result()
    except Exception as e:
        print(f"HTML translation error: {e}")
        return html


def get_translation_script(site_lang: str, user_lang: str, api_endpoint: str = "/api/translate") -> str:
    """
    Generate JavaScript for live input translation in proxied pages.

    This script:
    - Intercepts form submissions
    - Translates user inputs from user_lang to site_lang
    - Provides visual feedback during translation

    Args:
        site_lang: Website's language
        user_lang: User's preferred language
        api_endpoint: Backend API endpoint for translation

    Returns:
        JavaScript code to inject into proxied pages
    """
    if site_lang == user_lang:
        return ""

    return f'''
<script>
(function() {{
    const SITE_LANG = "{site_lang}";
    const USER_LANG = "{user_lang}";
    const API_ENDPOINT = "{api_endpoint}";

    // Skip if same language
    if (SITE_LANG === USER_LANG) return;

    // Translation cache
    const cache = new Map();

    // Translate text via API
    async function translateText(text, fromLang, toLang) {{
        if (!text || !text.trim()) return text;

        const cacheKey = `${{fromLang}}|${{toLang}}|${{text}}`;
        if (cache.has(cacheKey)) return cache.get(cacheKey);

        try {{
            const response = await fetch(API_ENDPOINT, {{
                method: 'POST',
                headers: {{ 'Content-Type': 'application/json' }},
                body: JSON.stringify({{ text, source: fromLang, target: toLang }})
            }});

            if (response.ok) {{
                const data = await response.json();
                if (data.translated) {{
                    cache.set(cacheKey, data.translated);
                    return data.translated;
                }}
            }}
        }} catch (e) {{
            console.warn('Translation error:', e);
        }}

        return text;
    }}

    // Add translation indicator to input
    function addIndicator(input) {{
        if (input.dataset.ffTranslate) return;
        input.dataset.ffTranslate = 'true';

        const wrapper = document.createElement('div');
        wrapper.style.cssText = 'position:relative;display:inline-block;width:100%;';

        const indicator = document.createElement('span');
        indicator.className = 'ff-translate-indicator';
        indicator.style.cssText = `
            position:absolute;right:8px;top:50%;transform:translateY(-50%);
            font-size:10px;color:#4361ee;background:#f0f4ff;
            padding:2px 6px;border-radius:3px;pointer-events:none;
            opacity:0;transition:opacity 0.2s;
        `;
        indicator.textContent = 'Translating...';

        input.parentNode.insertBefore(wrapper, input);
        wrapper.appendChild(input);
        wrapper.appendChild(indicator);

        input._ffIndicator = indicator;
    }}

    // Handle input translation
    async function handleInput(e) {{
        const input = e.target;
        if (!input.matches('input[type="text"], input:not([type]), textarea')) return;
        if (input.dataset.ffSkip === 'true') return;

        // Skip certain field types
        const name = (input.name || input.id || '').toLowerCase();
        if (/email|password|phone|tel|zip|postal|card|cvv|cvc|date|time/i.test(name)) {{
            input.dataset.ffSkip = 'true';
            return;
        }}

        const text = input.value;
        if (!text || text.length < 2) return;

        // Store original value
        if (!input.dataset.ffOriginal) {{
            input.dataset.ffOriginal = text;
        }}

        // Show indicator
        addIndicator(input);
        if (input._ffIndicator) {{
            input._ffIndicator.style.opacity = '1';
        }}

        // Translate after user stops typing
        clearTimeout(input._ffTimeout);
        input._ffTimeout = setTimeout(async () => {{
            const translated = await translateText(text, USER_LANG, SITE_LANG);

            if (translated !== text) {{
                input.dataset.ffTranslated = translated;
                if (input._ffIndicator) {{
                    input._ffIndicator.textContent = '✓ Translated';
                    input._ffIndicator.style.background = '#d4edda';
                    input._ffIndicator.style.color = '#155724';
                }}
            }}

            setTimeout(() => {{
                if (input._ffIndicator) input._ffIndicator.style.opacity = '0';
            }}, 2000);
        }}, 500);
    }}

    // Intercept form submission
    function handleSubmit(e) {{
        const form = e.target;
        const inputs = form.querySelectorAll('input[type="text"], input:not([type]), textarea');

        inputs.forEach(input => {{
            if (input.dataset.ffTranslated) {{
                input.value = input.dataset.ffTranslated;
            }}
        }});
    }}

    // Initialize
    document.addEventListener('input', handleInput, true);
    document.addEventListener('submit', handleSubmit, true);

    // Add styles
    const style = document.createElement('style');
    style.textContent = `
        .ff-translate-indicator {{
            font-family: -apple-system, BlinkMacSystemFont, sans-serif !important;
        }}
    `;
    document.head.appendChild(style);

    console.log('[PHOENIX] Translation active: ' + USER_LANG + ' → ' + SITE_LANG);
}})();
</script>
'''


def get_language_name(code: str) -> str:
    """Get display name for language code."""
    return SUPPORTED_LANGUAGES.get(code, code.upper())


def get_languages_by_region() -> Dict[str, List[Tuple[str, str]]]:
    """Get languages grouped by region for UI display."""
    result = {}
    for region, codes in LANGUAGE_REGIONS.items():
        result[region] = [(code, SUPPORTED_LANGUAGES[code]) for code in codes if code in SUPPORTED_LANGUAGES]
    return result


# Test function
if __name__ == "__main__":
    print("Testing translation service...")

    # Test language detection
    tests = [
        ("Hello world", "en"),
        ("こんにちは世界", "ja"),
        ("안녕하세요", "ko"),
        ("Привет мир", "ru"),
        ("مرحبا بالعالم", "ar"),
        ("สวัสดีโลก", "th"),
    ]

    print("\nLanguage Detection:")
    for text, expected in tests:
        detected = detect_language(text)
        status = "✓" if detected == expected else "✗"
        print(f"  {status} '{text[:20]}...' → {detected} (expected {expected})")

    # Test translation
    print("\nTranslation:")
    ja_text = "こんにちは世界"
    result = translate_text(ja_text, "ja", "en")
    print(f"  Japanese → English: '{ja_text}' → '{result}'")

    # Test form data translation
    print("\nForm Data Translation:")
    form_data = {
        "name": "John Smith",
        "email": "john@example.com",
        "address": "123 Main Street",
        "city": "New York",
    }
    translated = translate_form_data(form_data, "en", "ja")
    for key, value in translated.items():
        orig = form_data[key]
        if orig != value:
            print(f"  {key}: '{orig}' → '{value}'")
        else:
            print(f"  {key}: '{orig}' (unchanged)")

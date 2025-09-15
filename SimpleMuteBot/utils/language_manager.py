import json
from pathlib import Path
from typing import Dict, Any, Optional

class LanguageManager:
    def __init__(self, default_lang: str = 'ru'):
        self.languages: Dict[str, Dict[str, Any]] = {}
        self.default_lang = default_lang
        self.locales_dir = Path(__file__).parent.parent / 'locales'
        self.load_languages()

    def load_languages(self):
        if not self.locales_dir.exists():
            self.locales_dir.mkdir(parents=True)
            return

        for lang_file in self.locales_dir.glob('*.json'):
            lang_code = lang_file.stem
            try:
                with open(lang_file, 'r', encoding='utf-8') as f:
                    self.languages[lang_code] = json.load(f)
            except (json.JSONDecodeError, IOError) as e:
                print(f"Error loading language {lang_code}: {e}")

    def get(self, key: str, lang: Optional[str] = None, **kwargs) -> str:
        lang = lang or self.default_lang
        keys = key.split('.')
        
        try:
            value = self.languages.get(lang, self.languages[self.default_lang])
            for k in keys:
                value = value[k]
            
            if isinstance(value, str) and kwargs:
                return value.format(**kwargs)
            return value
        except (KeyError, TypeError):
            if lang != self.default_lang:
                return self.get(key, self.default_lang, **kwargs)
            return f"[[{key}]]"  # Return key if not found

    def set_language(self, lang: str) -> bool:
        if lang in self.languages:
            self.default_lang = lang
            return True
        return False

# Create a global instance
language_manager = LanguageManager()

def get_text(key: str, lang: Optional[str] = None, **kwargs) -> str:
    return language_manager.get(key, lang, **kwargs)

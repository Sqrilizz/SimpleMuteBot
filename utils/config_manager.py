import json
from pathlib import Path
from typing import Dict, Optional

class ConfigManager:
    def __init__(self, config_file: str = 'bot_config.json'):
        self.config_file = Path(config_file)
        self.config = self._load_config()
    
    def _load_config(self) -> Dict:
        if not self.config_file.exists():
            return {}
        try:
            with open(self.config_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return {}
    
    def _save_config(self):
        with open(self.config_file, 'w', encoding='utf-8') as f:
            json.dump(self.config, f, ensure_ascii=False, indent=4)
    
    def set_guild_language(self, guild_id: int, language: str):
        if 'guilds' not in self.config:
            self.config['guilds'] = {}
        self.config['guilds'][str(guild_id)] = {'language': language}
        self._save_config()
    
    def get_guild_language(self, guild_id: int) -> str:
        return self.config.get('guilds', {}).get(str(guild_id), {}).get('language', 'ru')

# Global instance
config_manager = ConfigManager()

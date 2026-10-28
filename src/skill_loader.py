import os

class SkillLoader:
    def __init__(self, skill_path="skills/CloseClawdio/SKILL.md"):
        # Resolve path relative to the script location or current directory
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.skill_path = os.path.join(base_dir, skill_path)

    def get_system_prompt(self) -> str:
        """Reads and returns the FP&A persona from the SKILL.md file."""
        try:
            with open(self.skill_path, 'r', encoding='utf-8') as f:
                content = f.read()
            return content
        except Exception as e:
            print(f"Error loading SKILL.md: {e}")
            return "You are CloseClawdio, a financial AI Agent. Handle financial queries carefully. (Failed to load full profile)."

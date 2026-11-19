"""Regression checks for UI copy and navigation contrast."""
import unittest
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app.py"


def luminance(hex_color: str) -> float:
    vals = [int(hex_color[i:i+2], 16) / 255 for i in (1, 3, 5)]
    linear = [v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4 for v in vals]
    return sum(w*v for w,v in zip((0.2126, 0.7152, 0.0722), linear))


def contrast(a: str, b: str) -> float:
    hi, lo = sorted((luminance(a), luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


class TestUiPresentation(unittest.TestCase):
    def setUp(self):
        self.source = APP.read_text(encoding="utf-8")

    def test_technical_notes_not_in_user_facing_navigation(self):
        for phrase in (
            "GovTech · Демонстрационный прототип",
            "ДЕМОНСТРАЦИОННАЯ СРЕДА",
            "Демо · автономный режим",
            "🟢 Аналитическое ядро локально",
            "🟢 SQLite · журнал решений",
            "🟡 Госреестры · имитация",
            "Контур проверки · v1.0.0",
        ):
            self.assertNotIn(phrase, self.source, phrase)

    def test_no_sidebar_white_text_catchall(self):
        self.assertNotIn('[data-testid="stSidebar"] * { color:', self.source)
        self.assertIn('button[kind="secondary"]', self.source)
        self.assertIn('button[kind="primary"]', self.source)

    def test_navigation_colour_contrast(self):
        self.assertGreaterEqual(contrast("#F7FAFC", "#203F52"), 4.5)
        self.assertGreaterEqual(contrast("#FFFFFF", "#08747C"), 4.5)
        self.assertGreaterEqual(contrast("#163B50", "#FFFFFF"), 4.5)

    def test_data_limits_remain_clear(self):
        self.assertIn('Нет реальных интеграций.', self.source)
        self.assertIn('Не загружайте реальные персональные данные.', self.source)
        self.assertIn('правил', self.source)


if __name__ == "__main__":
    unittest.main()

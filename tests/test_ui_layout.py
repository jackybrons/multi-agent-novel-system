import unittest

from app import CSS


class UiLayoutTest(unittest.TestCase):
    def test_workspace_uses_fixed_two_column_layout(self):
        self.assertIn("height: calc(100vh", CSS)
        self.assertIn("overflow: hidden", CSS)
        self.assertIn("overflow-y: auto", CSS)
        self.assertIn(".left-panel", CSS)
        self.assertIn(".right-panel", CSS)


if __name__ == "__main__":
    unittest.main()

import unittest
import inspect

from app import CSS, build_app


class UiLayoutTest(unittest.TestCase):
    def test_workspace_uses_fixed_two_column_layout(self):
        self.assertIn("height: calc(100vh", CSS)
        self.assertIn("overflow: hidden", CSS)
        self.assertIn("overflow-y: auto", CSS)
        self.assertIn(".left-panel", CSS)
        self.assertIn(".right-panel", CSS)

    def test_manuscript_has_its_own_scrollable_reader(self):
        source = inspect.getsource(build_app)
        self.assertIn("gr.Markdown", source)
        self.assertIn('elem_classes="manuscript"', source)
        self.assertIn(".manuscript", CSS)


if __name__ == "__main__":
    unittest.main()

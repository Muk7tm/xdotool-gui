import unittest

from PySide6.QtWidgets import QApplication

from xdotool_gui.tabs import StructuredAutomationTab


class StructuredAutomationTabTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_undo_redo_tracks_row_count(self) -> None:
        tab = StructuredAutomationTab()
        initial_rows = tab.table.rowCount()

        tab.add_step()
        tab.add_step()
        self.assertEqual(tab.table.rowCount(), initial_rows + 2)

        tab.table.setCurrentCell(0, 0)
        tab.remove_step()
        self.assertEqual(tab.table.rowCount(), initial_rows + 1)

        tab.undo()
        self.assertEqual(tab.table.rowCount(), initial_rows + 2)

        tab.redo()
        self.assertEqual(tab.table.rowCount(), initial_rows + 1)


if __name__ == "__main__":
    unittest.main()

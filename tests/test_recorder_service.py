import unittest

from xdotool_gui.models import RecorderEvent
from xdotool_gui.services.recorder import RecorderService


class RecorderServiceTests(unittest.TestCase):
    def test_move_events_are_throttled_by_distance_and_time(self) -> None:
        service = RecorderService()

        self.assertFalse(service._should_record_move(100, 100, 102, 100, 0.0, 0.0))
        self.assertTrue(service._should_record_move(100, 100, 106, 100, 0.0, 0.0))
        self.assertTrue(service._should_record_move(100, 100, 103, 100, 0.025, 0.0))

    def test_drain_returns_pending_events_in_order(self) -> None:
        service = RecorderService()
        service._buffer_event(RecorderEvent(timestamp=1.0, type="MouseMove", x=1, y=2))
        service._buffer_event(RecorderEvent(timestamp=2.0, type="KeyDown", key="a"))

        drained = service.drain_events()

        self.assertEqual([event.type for event in drained], ["MouseMove", "KeyDown"])
        self.assertEqual(drained[0].x, 1)
        self.assertEqual(drained[1].key, "a")


if __name__ == "__main__":
    unittest.main()

"""The registered vision tool preserves the active viewport when requested."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class ViewportCaptureTest(unittest.TestCase):
    def test_registered_capture_preserves_full_default_and_viewport_choice(self):
        from tools import browser_tool  # Registers the real handler.
        from tools.registry import registry

        with tempfile.TemporaryDirectory() as directory:
            screenshot = Path(directory) / 'shot.png'
            screenshot.write_bytes(b'original screenshot')
            with (
                patch('tools.browser_tool._is_camofox_mode', return_value=False),
                patch('tools.browser_tool_cloud._get_browser_engine', return_value='chrome'),
                patch('tools.browser_tool_session._run_browser_command', return_value={'success': True, 'data': {'path': str(screenshot)}}) as command,
                patch('tools.browser_tool_vision._lightpanda_vision_preroute', return_value=(False, None, screenshot)),
                patch('tools.browser_tool_vision._native_vision_result', return_value={'_multimodal': True, 'content': [], 'meta': {'screenshot_path': str(screenshot)}}),
                patch('tools.vision_tools._should_use_native_vision_fast_path', return_value=True),
                patch('tools.browser_tool_lifecycle._cleanup_old_screenshots'),
                patch('hermes_constants.get_hermes_dir', return_value=Path(directory)),
            ):
                for arguments, full in [({}, True), ({'full_page': False}, False), ({'full_page': True, 'annotate': True}, True)]:
                    result = registry.dispatch('browser_vision', {'question': 'Inspect', **arguments}, task_id='viewport-test')
                    self.assertIsInstance(result, dict, result)
                    self.assertEqual('--full' in command.call_args.args[2], full)
                    self.assertEqual(command.call_args.args[0], 'viewport-test')
                    self.assertEqual(screenshot.read_bytes(), b'original screenshot')
                with patch('tools.browser_tool._is_camofox_mode', return_value=True):
                    result = registry.dispatch('browser_vision', {'question': 'Inspect', 'full_page': False})
                    self.assertFalse(json.loads(result)['success'])
                with (
                    patch('tools.browser_tool_cloud._get_browser_engine', return_value='lightpanda'),
                    patch('tools.browser_tool_cloud._should_inject_engine', return_value=True),
                ):
                    result = registry.dispatch('browser_vision', {'question': 'Inspect', 'full_page': False})
                    self.assertFalse(json.loads(result)['success'])


if __name__ == '__main__':
    unittest.main()

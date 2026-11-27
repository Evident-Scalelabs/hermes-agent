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
                patch('tools.browser_tool_cloud._get_browser_engine', return_value='chrome'),
                patch('tools.browser_tool_cloud._is_local_backend', return_value=False),
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
                with (
                    patch('tools.browser_tool_cloud._get_browser_engine', return_value='lightpanda'),
                    patch('tools.browser_tool_cloud._should_inject_engine', return_value=True),
                ):
                    result = registry.dispatch('browser_vision', {'question': 'Inspect', 'full_page': False})
                    self.assertFalse(json.loads(result)['success'])


    def test_local_viewport_timeout_keeps_the_capture_off_cli_recovery(self):
        from tools import browser_tool
        from tools.registry import registry

        with tempfile.TemporaryDirectory() as directory:
            screenshot = Path(directory) / 'shot.png'
            screenshot.write_bytes(b'original viewport')
            with (
                patch('tools.browser_tool_cloud._is_local_backend', return_value=True),
                patch('tools.browser_tool_cloud._get_browser_engine', return_value='chrome'),
                patch('tools.browser_tool_session.sandbox_screenshot_path', return_value=None),
                patch('tools.browser_tool_session._run_browser_command', return_value={'success': True, 'data': {'path': str(screenshot)}}) as command,
                patch('tools.browser_tool_capture.capture_browser_screenshot', side_effect=[
                    {'success': True, 'data': {'path': str(screenshot), 'screenshot_scale_factor': 1}},
                    {'success': False, 'code': 'capture_timeout', 'error': 'Capture timed out'},
                    {'success': True, 'data': {'path': str(screenshot), 'screenshot_scale_factor': 1}},
                ]) as capture,
                patch('tools.browser_tool_vision._lightpanda_vision_preroute', return_value=(False, None, screenshot)),
                patch('tools.browser_tool_vision._native_vision_result', return_value={'_multimodal': True, 'content': [], 'meta': {'screenshot_path': str(screenshot)}}),
                patch('tools.vision_tools._should_use_native_vision_fast_path', return_value=True),
                patch('tools.browser_tool_lifecycle._cleanup_old_screenshots'),
                patch('hermes_constants.get_hermes_dir', return_value=Path(directory)),
            ):
                result = registry.dispatch('browser_vision', {'question': 'Inspect', 'full_page': False}, task_id='owned-mobile')
                self.assertTrue(result['_multimodal'])
                self.assertEqual(capture.call_args.args[:2], ('owned-mobile', screenshot))
                failed = registry.dispatch('browser_vision', {'question': 'Inspect', 'full_page': False}, task_id='owned-mobile')
                self.assertFalse(json.loads(failed)['success'])
                command.assert_not_called()
                with (
                    patch('tools.vision_tools._should_use_native_vision_fast_path', return_value=False),
                    patch('tools.browser_tool_vision._analyze_screenshot_with_aux_llm', return_value='Observed mobile viewport'),
                ):
                    result = registry.dispatch('browser_vision', {'question': 'Inspect', 'full_page': False}, task_id='owned-mobile')
                    self.assertEqual(json.loads(result)['screenshot_scale_factor'], 1)
                registry.dispatch('browser_vision', {'question': 'Inspect'}, task_id='owned-mobile')
                self.assertIn('--full', command.call_args.args[2])


if __name__ == '__main__':
    unittest.main()

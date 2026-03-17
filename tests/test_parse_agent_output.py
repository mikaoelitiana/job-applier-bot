import importlib
import sys
import types
import unittest


def _load_agent_module():
    """Import src.agent with minimal stubs for heavy dependencies."""
    for mod in ("src.agent", "src.config", "browser_use"):
        if mod in sys.modules:
            del sys.modules[mod]

    fake_browser_use = types.ModuleType("browser_use")
    fake_browser_use.Agent = object
    fake_browser_use.BrowserProfile = object
    fake_browser_use.BrowserSession = object
    fake_browser_use.ChatAnthropic = object
    fake_browser_use.ChatOpenAI = object
    sys.modules["browser_use"] = fake_browser_use

    fake_config = types.ModuleType("src.config")
    fake_config.settings = types.SimpleNamespace(
        llm_model="opencode/claude-sonnet-4-5",
        opencode_api_key="key",
        perplexity_api_key=None,
        openrouter_api_key=None,
        ollamacloud_api_key=None,
        minimax_api_key=None,
    )
    sys.modules["src.config"] = fake_config

    return importlib.import_module("src.agent")


class ParseAgentOutputTests(unittest.TestCase):
    def setUp(self):
        self.agent = _load_agent_module()

    def tearDown(self):
        for mod in ("src.agent", "src.config", "browser_use"):
            sys.modules.pop(mod, None)

    # ------------------------------------------------------------------
    # happy-path cases
    # ------------------------------------------------------------------

    def test_clean_json_string(self):
        text = '{"job_title":"Engineer","company":"Acme","status":"applied","notes":"ok"}'
        result = self.agent._parse_agent_output(text, "http://x.com")
        self.assertTrue(result.success)
        self.assertEqual(result.job_title, "Engineer")
        self.assertEqual(result.company, "Acme")
        self.assertEqual(result.notes, "ok")

    def test_json_embedded_in_prose(self):
        text = (
            'Here is the result:\n'
            '{"job_title":"Dev","company":"Corp","status":"applied","notes":"done"}\n'
            'All finished.'
        )
        result = self.agent._parse_agent_output(text, "http://x.com")
        self.assertTrue(result.success)
        self.assertEqual(result.job_title, "Dev")

    def test_nested_json_object(self):
        """The old regex rejected objects with nested braces; the new scanner must handle them."""
        text = (
            '{"job_title":"PM","company":"Biz","status":"applied",'
            '"notes":"ok","meta":{"source":"linkedin"}}'
        )
        result = self.agent._parse_agent_output(text, "http://x.com")
        self.assertTrue(result.success)
        self.assertEqual(result.job_title, "PM")
        self.assertEqual(result.company, "Biz")

    def test_failed_status(self):
        text = '{"job_title":"X","company":"Y","status":"failed","notes":"captcha"}'
        result = self.agent._parse_agent_output(text, "http://x.com")
        self.assertFalse(result.success)
        self.assertEqual(result.notes, "captcha")

    # ------------------------------------------------------------------
    # fallback / error cases
    # ------------------------------------------------------------------

    def test_no_json_returns_failure(self):
        result = self.agent._parse_agent_output("No JSON here at all.", "http://x.com")
        self.assertFalse(result.success)
        self.assertEqual(result.job_title, "Unknown")

    def test_empty_string_returns_failure(self):
        result = self.agent._parse_agent_output("", "http://x.com")
        self.assertFalse(result.success)

    def test_json_without_job_title_is_skipped(self):
        text = '{"foo":"bar"} then {"job_title":"QA","company":"Z","status":"applied","notes":""}'
        result = self.agent._parse_agent_output(text, "http://x.com")
        self.assertTrue(result.success)
        self.assertEqual(result.job_title, "QA")


if __name__ == "__main__":
    unittest.main()

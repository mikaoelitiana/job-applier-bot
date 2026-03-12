import asyncio
import importlib
import sys
import types
import unittest


class _FakeResult:
    def final_result(self):
        return '{"job_title":"Engineer","company":"Acme","status":"applied","notes":"ok"}'


class _FakeAgent:
    last_kwargs = None

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        _FakeAgent.last_kwargs = kwargs

    async def run(self):
        return _FakeResult()


class _FakeBrowserProfile:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


class _FakeBrowserSession:
    def __init__(self, **kwargs):
        self.kwargs = kwargs

    async def stop(self):
        return None


class _FakeChatOpenAI:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


class _FakeChatAnthropic:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


class ApplyToJobFallbackLlmTests(unittest.TestCase):
    def setUp(self) -> None:
        for module_name in ("src.agent", "src.config", "browser_use"):
            if module_name in sys.modules:
                del sys.modules[module_name]

        fake_browser_use = types.ModuleType("browser_use")
        fake_browser_use.Agent = _FakeAgent
        fake_browser_use.BrowserProfile = _FakeBrowserProfile
        fake_browser_use.BrowserSession = _FakeBrowserSession
        fake_browser_use.ChatOpenAI = _FakeChatOpenAI
        fake_browser_use.ChatAnthropic = _FakeChatAnthropic
        sys.modules["browser_use"] = fake_browser_use

        fake_config = types.ModuleType("src.config")
        fake_config.settings = types.SimpleNamespace(
            llm_model="openrouter/arcee-ai/trinity-large-preview:free",
            fallback_llm_model="opencode/claude-sonnet-4-5",
            opencode_api_key="test-opencode-key",
            openrouter_api_key="test-openrouter-key",
            perplexity_api_key=None,
            ollamacloud_api_key=None,
            minimax_api_key=None,
            resume_path="assets/resume.pdf",
            profile_path="assets/profile.json",
        )
        sys.modules["src.config"] = fake_config

    def tearDown(self) -> None:
        for module_name in ("src.agent", "src.config", "browser_use"):
            if module_name in sys.modules:
                del sys.modules[module_name]

    def test_apply_to_job_passes_fallback_llm_to_agent(self) -> None:
        agent_module = importlib.import_module("src.agent")
        agent_module._load_profile = lambda: {}

        async def _fake_chromium_executable() -> str:
            return "/tmp/chromium"

        agent_module._chromium_executable = _fake_chromium_executable

        result = asyncio.run(agent_module.apply_to_job("https://example.com/job"))

        self.assertTrue(result.success)
        self.assertIn("fallback_llm", _FakeAgent.last_kwargs)

        fallback_llm = _FakeAgent.last_kwargs["fallback_llm"]
        self.assertIsInstance(fallback_llm, _FakeChatAnthropic)
        self.assertEqual(fallback_llm.kwargs["model"], "claude-sonnet-4-5")
        self.assertEqual(fallback_llm.kwargs["api_key"], "test-opencode-key")
        self.assertEqual(fallback_llm.kwargs["base_url"], "https://opencode.ai/zen/v1/messages")


if __name__ == "__main__":
    unittest.main()

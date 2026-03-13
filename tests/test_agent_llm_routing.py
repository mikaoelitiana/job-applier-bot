import importlib
import sys
import types
import unittest


class _FakeChatAnthropic:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


class _FakeChatOpenAI:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


class BuildLlmRoutingTests(unittest.TestCase):
    def setUp(self) -> None:
        if "src.agent" in sys.modules:
            del sys.modules["src.agent"]

        fake_browser_use = types.ModuleType("browser_use")
        fake_browser_use.Agent = object
        fake_browser_use.BrowserProfile = object
        fake_browser_use.BrowserSession = object
        fake_browser_use.ChatAnthropic = _FakeChatAnthropic
        fake_browser_use.ChatOpenAI = _FakeChatOpenAI
        sys.modules["browser_use"] = fake_browser_use

        fake_config = types.ModuleType("src.config")
        fake_config.settings = types.SimpleNamespace(
            llm_model="opencode/claude-sonnet-4-5",
            opencode_api_key="test-opencode-key",
            perplexity_api_key=None,
            openrouter_api_key="test-openrouter-key",
            ollamacloud_api_key=None,
            minimax_api_key=None,
        )
        sys.modules["src.config"] = fake_config

    def tearDown(self) -> None:
        for module_name in ("src.agent", "src.config", "browser_use"):
            if module_name in sys.modules:
                del sys.modules[module_name]

    def test_opencode_claude_uses_anthropic_client_and_endpoint(self) -> None:
        agent_module = importlib.import_module("src.agent")

        llm = agent_module._build_llm()

        self.assertIsInstance(llm, _FakeChatAnthropic)
        self.assertEqual(llm.kwargs["model"], "claude-sonnet-4-5")
        self.assertEqual(llm.kwargs["api_key"], "test-opencode-key")
        self.assertEqual(llm.kwargs["base_url"], "https://opencode.ai/zen/v1/messages")

    def test_openrouter_free_uses_full_router_model_id(self) -> None:
        agent_module = importlib.import_module("src.agent")

        llm = agent_module._build_llm("openrouter/free")

        self.assertIsInstance(llm, _FakeChatOpenAI)
        self.assertEqual(llm.kwargs["model"], "openrouter/free")
        self.assertEqual(llm.kwargs["api_key"], "test-openrouter-key")
        self.assertEqual(llm.kwargs["base_url"], "https://openrouter.ai/api/v1")


if __name__ == "__main__":
    unittest.main()

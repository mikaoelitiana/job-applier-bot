import unittest
import sys
import types


class _FakeBrowserSession:
    def __init__(self, browser_profile):
        self.browser_profile = browser_profile
        
    async def get_current_page(self):
        return None
        
    async def stop(self):
        pass


class _FakeBrowserProfile:
    def __init__(self, headless=True, executable_path=None):
        self.headless = headless
        self.executable_path = executable_path


class _FakeAgent:
    def __init__(self, task, llm, browser, **kwargs):
        self.task = task
        self.llm = llm
        self.browser = browser
        
    async def run(self):
        class Result:
            def final_result(self):
                return '{"job_title": "Senior Software Engineer", "company": "Test Co", "description": "Great job", "requirements": "Python, React"}'
        return Result()


class _FakeChatAnthropic:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


class _FakeLangchainChatAnthropic:
    def __init__(self, model):
        self.model = model
        
    async def ainvoke(self, messages):
        class Response:
            content = '{"is_match": true, "match_score": 0.85, "reasoning": "Good match", "key_matches": ["Python", "React"], "concerns": []}'
        return Response()


class JobValidatorTests(unittest.TestCase):
    
    def setUp(self):
        # Clean up any existing modules
        for module_name in ("src.job_validator", "src.config", "src.agent", "browser_use", "langchain_anthropic"):
            if module_name in sys.modules:
                del sys.modules[module_name]
        
        # Mock browser_use module
        fake_browser_use = types.ModuleType("browser_use")
        fake_browser_use.BrowserSession = _FakeBrowserSession
        fake_browser_use.BrowserProfile = _FakeBrowserProfile
        fake_browser_use.Agent = _FakeAgent
        fake_browser_use.ChatAnthropic = _FakeChatAnthropic
        fake_browser_use.ChatOpenAI = object
        fake_browser_use.ChatGoogle = object
        fake_browser_use.ChatOllama = object
        sys.modules["browser_use"] = fake_browser_use
        
        # Mock langchain_anthropic module
        fake_langchain = types.ModuleType("langchain_anthropic")
        fake_langchain.ChatAnthropic = _FakeLangchainChatAnthropic
        sys.modules["langchain_anthropic"] = fake_langchain
        
        # Mock config settings
        fake_config = types.ModuleType("src.config")
        fake_config.settings = types.SimpleNamespace(
            llm_model="anthropic/claude-sonnet-4-6",
            profile_path="assets/profile.json",
            resume_path="assets/resume.pdf",
        )
        sys.modules["src.config"] = fake_config
        
    def tearDown(self):
        for module_name in ("src.job_validator", "src.config", "src.agent", "browser_use", "langchain_anthropic"):
            if module_name in sys.modules:
                del sys.modules[module_name]
    
    def test_extract_job_description_returns_structured_data(self):
        """extract_job_description should return JobDescription with title, company, description, requirements"""
        from src.job_validator import extract_job_description
        import asyncio
        
        result = asyncio.run(extract_job_description("https://example.com/job"))
        
        self.assertIsNotNone(result)
        self.assertEqual(result.job_title, "Senior Software Engineer")
        self.assertEqual(result.company, "Test Co")
        self.assertIn("Great job", result.description)
        self.assertIn("Python", result.requirements)
    
    def test_validate_job_match_returns_validation_result(self):
        """validate_job_match should return ValidationResult with match decision and reasoning"""
        from src.job_validator import validate_job_match, JobDescription
        import asyncio
        
        job_desc = JobDescription(
            job_title="Senior Software Engineer",
            company="Test Co",
            description="We need a senior engineer",
            requirements="Python, React, 5+ years experience"
        )
        
        profile = {
            "skills": ["Python", "React", "TypeScript"],
            "years_of_experience": 10,
            "desired_roles": ["Senior Software Engineer"]
        }
        
        result = asyncio.run(validate_job_match(job_desc, profile))
        
        self.assertIsNotNone(result)
        self.assertIsInstance(result.is_match, bool)
        self.assertIsInstance(result.match_score, float)
        self.assertIsInstance(result.reasoning, str)
        self.assertIsInstance(result.key_matches, list)
        self.assertIsInstance(result.concerns, list)


if __name__ == "__main__":
    unittest.main()

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path

from browser_use import Agent, BrowserProfile, BrowserSession

from src.config import settings

logger = logging.getLogger(__name__)


@dataclass
class ApplicationResult:
    success: bool
    job_title: str
    company: str
    notes: str


def _build_llm():
    """Instantiate the LLM based on the LLM_MODEL setting.

    Format: <provider>/<model-name>
    Examples:
        anthropic/claude-sonnet-4-0
        openai/gpt-4o
        gemini/gemini-flash-latest
        ollama/llama3.1:8b
    """
    model_str = settings.llm_model
    if "/" not in model_str:
        raise ValueError(
            f"LLM_MODEL must be in the form <provider>/<model>, got: {model_str!r}"
        )
    provider, model_name = model_str.split("/", 1)

    if provider == "anthropic":
        from browser_use import ChatAnthropic
        return ChatAnthropic(model=model_name)

    if provider == "openai":
        from browser_use import ChatOpenAI
        return ChatOpenAI(model=model_name)

    if provider == "gemini":
        from browser_use import ChatGoogle
        return ChatGoogle(model=model_name)

    if provider == "ollama":
        from browser_use import ChatOllama
        return ChatOllama(model=model_name)

    if provider == "perplexity":
        from browser_use import ChatOpenAI
        return ChatOpenAI(
            model=model_name,
            api_key=settings.perplexity_api_key,
            base_url="https://api.perplexity.ai",
        )

    if provider == "openrouter":
        from browser_use import ChatOpenAI
        return ChatOpenAI(
            model=model_name,
            api_key=settings.openrouter_api_key,
            base_url="https://openrouter.ai/api/v1",
        )

    if provider == "ollamacloud":
        from browser_use import ChatOpenAI
        return ChatOpenAI(
            model=model_name,
            api_key=settings.ollamacloud_api_key,
            base_url="https://cloud.ollama.ai/v1",
        )

    if provider == "minimax":
        from browser_use import ChatOpenAI
        return ChatOpenAI(
            model=model_name,
            api_key="dummy",  # Required but we use header for auth
            base_url="https://api.minimax.io/v1",
            extra_headers={"Authorization": f"Bearer {settings.minimax_api_key}"},
        )

    if provider == "opencode":
        import os
        os.environ["OPENAI_API_KEY"] = settings.opencode_api_key
        from browser_use import ChatOpenAI
        return ChatOpenAI(
            model=model_name,
            base_url="https://opencode.ai/zen/v1",
        )

    raise ValueError(f"Unsupported LLM provider: {provider!r}. Supported: anthropic, openai, gemini, ollama, perplexity, openrouter, ollamacloud, minimax, opencode")


def _load_profile() -> dict:
    profile_path = Path(settings.profile_path)
    if not profile_path.exists():
        raise FileNotFoundError(f"Profile not found at {profile_path}. Copy assets/profile.json and fill in your details.")
    with profile_path.open() as f:
        return json.load(f)


def _build_task(url: str, profile: dict, resume_path: str) -> str:
    """Build the natural-language task instruction for the browser agent."""
    profile_text = json.dumps(profile, indent=2)
    abs_resume = str(Path(resume_path).resolve())

    return f"""You are applying for a job on behalf of a candidate.

CANDIDATE PROFILE:
{profile_text}

RESUME FILE PATH (for upload): {abs_resume}

YOUR TASK:
1. Navigate to this URL: {url}
2. Read the full job description and note the job title and company name.
3. Find the application form or "Apply" button. If there is an "Apply" button, click it.
4. Fill in ALL required fields using the candidate profile above. Guidelines:
   - For name fields, use full_name.
   - For email, phone, location fields, use the corresponding profile values.
   - For resume/CV upload fields, upload the file at: {abs_resume}
   - For cover letter fields, write a tailored 2-3 paragraph cover letter using the candidate's
     cover_letter_intro and skills, customized to match the job description you read.
   - For salary/compensation fields, use the desired_salary values.
   - For "how did you hear about us" or similar optional questions, answer "Online job board".
   - For any other required free-text field, provide a reasonable answer based on the profile.
5. Submit the application form.
6. Confirm the submission was successful (look for a confirmation message or page).
7. Return ONLY a valid JSON object - no additional text, explanations, or markdown. Format:
   {{"job_title": "<title>", "company": "<company>", "status": "applied" or "failed", "notes": "<summary>"}}

CRITICAL:
- Output ONLY the JSON. Do not include any other text before or after the JSON.
- Do NOT skip required fields — fill them all before submitting.
- If the form requires creating an account or logging in, set status to "failed" and explain in notes.
- If a CAPTCHA or bot-detection blocks submission, set status to "failed" and explain in notes.
- Always return the JSON object at the end, even if the application failed.
"""


async def _chromium_executable() -> str:
    """Return the path to the Playwright-installed Chromium binary."""
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        return p.chromium.executable_path


async def apply_to_job(url: str) -> ApplicationResult:
    """Run the browser agent to apply for the job at the given URL."""
    profile = _load_profile()
    resume_path = settings.resume_path

    if not Path(resume_path).exists():
        logger.warning("Resume file not found at %s — upload steps will be skipped", resume_path)

    task = _build_task(url, profile, resume_path)
    llm = _build_llm()

    browser = BrowserSession(
        browser_profile=BrowserProfile(
            headless=True,
            executable_path=await _chromium_executable(),
        )
    )

    try:
        agent = Agent(
            task=task,
            llm=llm,
            browser=browser,
            available_file_paths=[str(Path(resume_path).resolve())],
        )
        result = await agent.run()

        # Extract the JSON summary the agent was asked to return
        output_text = ""
        if result and hasattr(result, "final_result"):
            output_text = result.final_result() or ""

        parsed = _parse_agent_output(output_text, url)
        return parsed

    except Exception as e:
        logger.exception("Agent failed while processing %s", url)
        return ApplicationResult(
            success=False,
            job_title="Unknown",
            company="Unknown",
            notes=f"Agent error: {e}",
        )
    finally:
        await browser.stop()


def _parse_agent_output(text: str, url: str) -> ApplicationResult:
    """Extract structured data from the agent's final text output."""
    import re

    # Try to find a JSON block in the output
    json_match = re.search(r"\{[^{}]*\"job_title\"[^{}]*\}", text, re.DOTALL)
    if json_match:
        try:
            data = json.loads(json_match.group())
            return ApplicationResult(
                success=data.get("status") == "applied",
                job_title=data.get("job_title", "Unknown"),
                company=data.get("company", "Unknown"),
                notes=data.get("notes", ""),
            )
        except json.JSONDecodeError:
            pass

    # Fallback: could not parse structured output
    logger.error("Could not parse structured JSON from agent output for %s. Raw output:\n%s", url, text)
    return ApplicationResult(
        success=False,
        job_title="Unknown",
        company="Unknown",
        notes=f"Agent did not return valid JSON. Output: {text[:500]}" if text else "Agent returned no output",
    )

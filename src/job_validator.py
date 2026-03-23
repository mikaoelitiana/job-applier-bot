import json
import logging
import re
from dataclasses import dataclass

from src.config import settings
from src.agent import _build_llm, _chromium_executable, _browser_use_module

logger = logging.getLogger(__name__)


@dataclass
class JobDescription:
    job_title: str
    company: str
    description: str
    requirements: str


@dataclass
class ValidationResult:
    is_match: bool
    match_score: float
    reasoning: str
    key_matches: list[str]
    concerns: list[str]


async def extract_job_description(url: str) -> JobDescription | None:
    """Extract job description from URL using browser agent.
    
    Returns JobDescription with title, company, description and requirements,
    or None if extraction fails.
    """
    task = f"""Navigate to this URL and extract the job information: {url}

Your task:
1. Navigate to the URL
2. Read the complete job posting page
3. Extract:
   - Job title
   - Company name
   - Full job description (responsibilities, about the role, what you'll do, etc.)
   - Requirements (qualifications, skills needed, experience required, etc.)

Return ONLY a valid JSON object with no additional text. Format:
{{"job_title": "<title>", "company": "<company>", "description": "<description>", "requirements": "<requirements>"}}

CRITICAL:
- Output ONLY the JSON. No markdown, no explanations, no additional text.
- Make description and requirements detailed - include all relevant information.
- If you cannot find certain fields, use empty string.
"""
    
    llm = _build_llm()
    browser_use = _browser_use_module()
    browser = browser_use.BrowserSession(
        browser_profile=browser_use.BrowserProfile(
            headless=True,
            executable_path=await _chromium_executable(),
        )
    )
    
    try:
        agent = browser_use.Agent(
            task=task,
            llm=llm,
            browser=browser,
        )
        result = await agent.run()
        
        output_text = ""
        if result and hasattr(result, "final_result"):
            output_text = result.final_result() or ""
        
        return _parse_job_description(output_text, url)
    
    except Exception as e:
        logger.exception("Failed to extract job description from %s", url)
        return None
    finally:
        await browser.stop()


def _parse_job_description(text: str, url: str) -> JobDescription | None:
    """Parse job description JSON from agent output."""
    # Try direct parse first
    try:
        data = json.loads(text.strip())
        if "job_title" in data:
            return JobDescription(
                job_title=data.get("job_title", ""),
                company=data.get("company", ""),
                description=data.get("description", ""),
                requirements=data.get("requirements", ""),
            )
    except (json.JSONDecodeError, AttributeError):
        pass
    
    # Scan for balanced JSON objects containing job_title
    for match in re.finditer(r"\{", text):
        start = match.start()
        depth, i = 0, start
        while i < len(text):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
            if depth == 0:
                try:
                    data = json.loads(text[start : i + 1])
                    if "job_title" in data:
                        return JobDescription(
                            job_title=data.get("job_title", ""),
                            company=data.get("company", ""),
                            description=data.get("description", ""),
                            requirements=data.get("requirements", ""),
                        )
                except json.JSONDecodeError:
                    pass
                break
            i += 1
    
    logger.error("Could not parse job description JSON from %s. Raw output:\n%s", url, text)
    return None


async def validate_job_match(job_desc: JobDescription, profile: dict) -> ValidationResult:
    """Validate if job matches candidate profile using LLM.
    
    Returns ValidationResult with match decision, score, reasoning and details.
    """
    # Import langchain_anthropic here to avoid import errors in tests
    try:
        from langchain_anthropic import ChatAnthropic
    except ImportError:
        logger.error("langchain_anthropic not installed. Install with: pip install langchain-anthropic")
        # Return a default "match" to avoid blocking applications
        return ValidationResult(
            is_match=True,
            match_score=0.5,
            reasoning="Could not validate match - langchain_anthropic not installed",
            key_matches=[],
            concerns=["Validation skipped - missing dependency"],
        )
    
    prompt = f"""You are a job matching expert. Analyze if this job is a good match for the candidate.

JOB INFORMATION:
Title: {job_desc.job_title}
Company: {job_desc.company}
Description: {job_desc.description}
Requirements: {job_desc.requirements}

CANDIDATE PROFILE:
{json.dumps(profile, indent=2)}

Analyze the match considering:
1. Skills alignment - does the candidate have the required technical skills?
2. Experience level - does the candidate's experience match the role level (junior/mid/senior)?
3. Role alignment - is this one of the candidate's desired roles?
4. Location/remote - does the job location match candidate preferences?
5. Any red flags or concerns?

Return ONLY a valid JSON object with no additional text. Format:
{{
  "is_match": true/false,
  "match_score": 0.0-1.0,
  "reasoning": "Brief explanation of the match assessment",
  "key_matches": ["list", "of", "matching", "points"],
  "concerns": ["list", "of", "concerns", "or", "gaps"]
}}

Guidelines:
- is_match: true if match_score >= 0.7, false otherwise
- match_score: 0.0-1.0 (0.9+ excellent, 0.7-0.9 good, 0.5-0.7 moderate, <0.5 poor)
- key_matches: specific skills, experience, or qualifications that align
- concerns: missing skills, experience gaps, or misalignments (empty list if none)

CRITICAL: Output ONLY the JSON. No markdown, no explanations.
"""
    
    llm = ChatAnthropic(model=settings.llm_model.split("/")[1] if "/" in settings.llm_model else "claude-sonnet-4-6")
    
    try:
        response = await llm.ainvoke([{"role": "user", "content": prompt}])
        result_text = response.content if hasattr(response, "content") else str(response)
        
        return _parse_validation_result(result_text)
    
    except Exception as e:
        logger.exception("Failed to validate job match")
        # Return a default "match" to avoid blocking applications
        return ValidationResult(
            is_match=True,
            match_score=0.5,
            reasoning=f"Validation failed: {e}",
            key_matches=[],
            concerns=["Validation error occurred"],
        )


def _parse_validation_result(text: str) -> ValidationResult:
    """Parse validation result JSON from LLM output."""
    # Try direct parse first
    try:
        data = json.loads(text.strip())
        if "is_match" in data:
            return ValidationResult(
                is_match=data.get("is_match", True),
                match_score=float(data.get("match_score", 0.5)),
                reasoning=data.get("reasoning", ""),
                key_matches=data.get("key_matches", []),
                concerns=data.get("concerns", []),
            )
    except (json.JSONDecodeError, AttributeError, ValueError):
        pass
    
    # Scan for balanced JSON objects containing is_match
    for match in re.finditer(r"\{", text):
        start = match.start()
        depth, i = 0, start
        while i < len(text):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
            if depth == 0:
                try:
                    data = json.loads(text[start : i + 1])
                    if "is_match" in data:
                        return ValidationResult(
                            is_match=data.get("is_match", True),
                            match_score=float(data.get("match_score", 0.5)),
                            reasoning=data.get("reasoning", ""),
                            key_matches=data.get("key_matches", []),
                            concerns=data.get("concerns", []),
                        )
                except (json.JSONDecodeError, ValueError):
                    pass
                break
            i += 1
    
    logger.error("Could not parse validation result JSON. Raw output:\n%s", text)
    # Return a default "match" to avoid blocking applications
    return ValidationResult(
        is_match=True,
        match_score=0.5,
        reasoning="Could not parse validation result",
        key_matches=[],
        concerns=["Parsing failed"],
    )

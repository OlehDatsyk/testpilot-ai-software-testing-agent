"""Structured-output schemas the AI provider must satisfy."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

TestCategory = Literal["unit", "edge-case", "input-validation", "error-handling", "boundary", "regression", "integration", "api"]


class AIGeneratedTest(BaseModel):
    name: str = Field(description="Test function name, snake_case for Python or a short sentence for Vitest")
    description: str
    target: str = Field(description="Function or class under test")
    category: TestCategory
    expected_behaviour: str = Field(description="Behaviour the test asserts, derived only from the provided source")
    rationale: str
    code: str = Field(description="Complete, self-contained test code including imports")


class AITestSuggestions(BaseModel):
    tests: list[AIGeneratedTest] = Field(max_length=8)


class AIFailureAnalysis(BaseModel):
    summary: str = Field(description="What failed, in one or two sentences")
    location: str = Field(description="Where it failed, quoting a file/line from the traceback, or 'unknown'")
    error_meaning: str
    likely_causes: list[str] = Field(max_length=5)
    suggested_fixes: list[str] = Field(max_length=5)
    additional_tests: list[str] = Field(max_length=5)
    confidence: Literal["low", "medium", "high"]


class AIAssistantAnswer(BaseModel):
    answer: str = Field(description="Markdown answer grounded only in the provided context")
    used_sources: list[str] = Field(description="Context section names the answer relied on")
    information_missing: bool = Field(description="True if the context did not contain what was needed")

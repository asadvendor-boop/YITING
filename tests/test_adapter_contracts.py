"""Local-runtime contract tests.

The Qwen/Alibaba edition uses Gateway-owned incident rooms instead of external
agent adapters. These tests prove the callable boundaries that the local runtime
depends on: typed handlers, local callbacks, and Qwen advisory bypass in tests.
"""
from __future__ import annotations

import asyncio
import inspect

from pydantic import BaseModel


class TestCommanderLocalRuntimeContract:
    def test_submit_response_plan_is_async_and_typed(self):
        from agents.commander import SubmitResponsePlan, submit_response_plan

        assert asyncio.iscoroutinefunction(submit_response_plan)
        sig = inspect.signature(submit_response_plan)
        params = set(sig.parameters.keys())
        assert set(SubmitResponsePlan.model_fields.keys()).issubset(params)
        for name, param in sig.parameters.items():
            if name == "ctx":
                continue
            assert param.annotation != inspect.Parameter.empty

    def test_local_commander_callback_exists(self):
        from agents.commander import run_local_commander

        assert asyncio.iscoroutinefunction(run_local_commander)


class TestSafetyReviewerLocalRuntimeContract:
    def test_submit_verdict_model_and_handler_are_typed(self):
        from agents.safety_reviewer import SubmitVerdict, handle_submit_verdict

        assert issubclass(SubmitVerdict, BaseModel)
        assert asyncio.iscoroutinefunction(handle_submit_verdict)
        first = list(inspect.signature(handle_submit_verdict).parameters.values())[0]
        assert first.annotation is SubmitVerdict or str(first.annotation) == "SubmitVerdict"

    def test_local_safety_callback_exists(self):
        from agents.safety_reviewer import run_local_safety_review

        assert asyncio.iscoroutinefunction(run_local_safety_review)


class TestDiagnosisLocalRuntimeContract:
    def test_submit_assessment_model_and_handler_are_typed(self):
        from agents.diagnosis import SubmitAssessment, handle_submit_assessment

        assert issubclass(SubmitAssessment, BaseModel)
        assert asyncio.iscoroutinefunction(handle_submit_assessment)
        first = list(inspect.signature(handle_submit_assessment).parameters.values())[0]
        assert first.annotation is SubmitAssessment or str(first.annotation) == "SubmitAssessment"

    def test_local_diagnosis_callback_exists(self):
        from agents.diagnosis import run_local_diagnosis

        assert asyncio.iscoroutinefunction(run_local_diagnosis)


class TestOperatorLocalRuntimeContract:
    def test_execute_remediation_is_async_and_typed(self):
        from agents.operator import execute_remediation

        assert asyncio.iscoroutinefunction(execute_remediation)
        sig = inspect.signature(execute_remediation)
        expected = {"incident_id", "action_id", "target", "parameters"}
        assert expected.issubset(sig.parameters.keys())
        for name in expected:
            assert sig.parameters[name].annotation != inspect.Parameter.empty

    def test_submit_action_receipt_is_async_and_typed(self):
        from agents.operator import submit_action_receipt

        assert asyncio.iscoroutinefunction(submit_action_receipt)
        sig = inspect.signature(submit_action_receipt)
        expected = {"incident_id", "resolution_summary"}
        assert expected.issubset(sig.parameters.keys())
        for name in expected:
            assert sig.parameters[name].annotation != inspect.Parameter.empty

    def test_local_operator_callback_exists(self):
        from agents.operator import run_local_operator

        assert asyncio.iscoroutinefunction(run_local_operator)

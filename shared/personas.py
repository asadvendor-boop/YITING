"""Canonical YITING agent personas.

The dashboard can decorate these with portraits, but this module is the backend
source of truth for agent names and role identities.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AgentPersona:
    role: str
    display_name: str
    title: str
    temperament: str

    @property
    def full_name(self) -> str:
        return self.display_name


PERSONAS: dict[str, AgentPersona] = {
    "triage": AgentPersona(
        role="triage",
        display_name="Lin Xun",
        title="Signal Sentinel",
        temperament="fast, skeptical, and disciplined about routing only real alerts",
    ),
    "diagnosis": AgentPersona(
        role="diagnosis",
        display_name="Chen Ming",
        title="Diagnostician",
        temperament="evidence-first, methodical, and careful about uncertainty",
    ),
    "safety_reviewer": AgentPersona(
        role="safety_reviewer",
        display_name="Zhou Shen",
        title="Safety Reviewer",
        temperament="cautious, independent, and willing to challenge weak reasoning",
    ),
    "commander": AgentPersona(
        role="commander",
        display_name="Han Ce",
        title="Incident Strategist",
        temperament="calm under pressure, policy-aware, and precise about plans",
    ),
    "operator": AgentPersona(
        role="operator",
        display_name="Lu Xing",
        title="Remediation Operator",
        temperament="literal, action-bound, and intolerant of unauthorized changes",
    ),
    "recorder": AgentPersona(
        role="recorder",
        display_name="Wen Lu",
        title="Evidence Recorder",
        temperament="neutral, exacting, and focused on the integrity trail",
    ),
    "scribe": AgentPersona(
        role="scribe",
        display_name="Song Shu",
        title="Postmortem Writer",
        temperament="clear, concise, and focused on lessons after closure",
    ),
}


def get_persona(role: str) -> AgentPersona | None:
    return PERSONAS.get(role)


def persona_payload(role: str) -> dict[str, str]:
    persona = get_persona(role)
    if persona is None:
        return {}
    return {
        "display_name": persona.full_name,
        "persona_title": persona.title,
        "persona_temperament": persona.temperament,
    }

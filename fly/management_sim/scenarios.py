"""Server-selected starting scenarios for management simulation."""

from __future__ import annotations

import random
from typing import Any


HEADCOUNT_BUDGET_CENTS = 1_250_000_00

SCENARIOS: list[dict[str, Any]] = [
    {
        "id": "workflow-platform",
        "title": "Workflow Platform",
        "mission": "Build a reliable workflow platform for mid-market teams.",
        "brief": "The company wants a workflow platform that replaces a patchwork of spreadsheets, scripts, and manual approvals. Sales has promised enterprise integrations before the team has agreed on the core model.",
    },
    {
        "id": "compliance-evidence",
        "title": "Compliance Evidence",
        "mission": "Build a compliance evidence product for regulated software teams.",
        "brief": "The company wants to turn audits from a quarterly scramble into a continuous product. Customers want proof, integrations, and dashboards; nobody agrees which evidence actually changes an audit outcome.",
    },
    {
        "id": "field-operations",
        "title": "Field Operations",
        "mission": "Build a field-service scheduling product for regional operators.",
        "brief": "The company wants to replace dispatch calls and handwritten schedules with software. The roadmap mixes routing, mobile workflows, billing, and customer communication into one quarter.",
    },
    {
        "id": "identity-migration",
        "title": "Identity Migration",
        "mission": "Build an identity migration product for enterprise customers.",
        "brief": "The company wants to help customers consolidate fragmented identity systems without downtime. The team is being asked to ship migration tooling, admin workflows, and security controls at once.",
    },
    {
        "id": "support-automation",
        "title": "Support Automation",
        "mission": "Build a support automation product for growing SaaS companies.",
        "brief": "The company wants to reduce support load with AI-assisted triage and workflow automation. The roadmap mixes customer trust, model quality, integrations, and internal tooling into one release.",
    },
    {
        "id": "usage-analytics",
        "title": "Usage Analytics",
        "mission": "Build a usage analytics product for enterprise product teams.",
        "brief": "The company wants customers to understand adoption and churn before revenue slips. The team is asked to build ingestion, dashboards, alerts, exports, and billing hooks before the event model is stable.",
    },
]


def choose_scenario() -> dict[str, Any]:
    return dict(random.choice(SCENARIOS))

"""YITING Scribe — incident room Platform Agent (no local code).

The Scribe agent is now implemented as a **incident room Platform Agent** and runs
entirely on the incident room server side.  It is recruited into incident rooms by
the Operator agent via the local incident-room runtime ``recruit_agent()`` API.

See:
    - Operator recruitment code: agents/operator/graph.py → _recruit_scribe()
    - incident room Platform Agent config: deployed via incident room admin console

This module is intentionally empty.  The previous local implementation
(deterministic postmortem generator using RECORDER_SUBMISSION_KEY) has
been removed because:

    1. It used RECORDER_SUBMISSION_KEY with the wrong ACL scope.
    2. It posted messages with empty mentions lists.
    3. It had no runtime entrypoint (never actually started).
    4. It contradicted the authoritative incident room Platform Scribe.

All postmortem generation is now handled by the YITING-native Scribe agent.
"""

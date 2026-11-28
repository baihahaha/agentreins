"""Testing helpers.

- ``FakeModel``: a scripted model, so agents can be tested offline.
- ``no_governance()`` (M7, REQUIREMENTS D7): lifts the three governance control points
  for tests. Never the default; runs record ``governance_lifted=true``.
"""

from agentreins.adapters.models.fake import FakeModel

__all__ = ["FakeModel"]

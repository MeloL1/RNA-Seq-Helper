"""Test adapter for fixtures whose intended replicate structure is known."""

from rnaseq_helper.analysis.planning import PlanningService as _PlanningService


class PlanningService(_PlanningService):
    """Computational fixtures explicitly confirm independent or paired designs."""

    def build(self, *args, **kwargs):
        if "replicate_structure" not in kwargs:
            kwargs["replicate_structure"] = (
                "paired" if kwargs.get("paired_subjects") else "independent"
            )
        return super().build(*args, **kwargs)

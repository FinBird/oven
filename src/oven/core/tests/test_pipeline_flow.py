from oven.core.pipeline import Pipeline, Transform


class AddOneTransform(Transform[int, int]):
    """Add one to the provided integer."""

    def transform(self, value: int) -> int:
        return value + 1


class MultiplyByTwoTransform(Transform[int, int]):
    def transform(self, value: int) -> int:
        return value * 2


def test_pipeline_stage_metadata_preserves_order() -> None:
    pipeline = AddOneTransform() | MultiplyByTwoTransform()
    info = pipeline.stage_info

    assert isinstance(info, tuple)
    assert len(info) == len(pipeline.stages)
    assert [stage.name for stage in info] == [
        "AddOneTransform",
        "MultiplyByTwoTransform",
    ]
    assert info[0].description == "Add one to the provided integer."
    assert info[1].description is None
    assert info[0].transform is pipeline.stages[0]

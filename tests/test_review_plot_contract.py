from copy import deepcopy

import pytest

from rnaseq_helper.analysis.service import AnalysisService


def test_plot_contract_rejects_missing_matrix_and_sample_reordering():
    valid = {"feature_ids": ["g2"], "sample_ids": ["a", "b"], "values": [[1.0, 2.0]], "transform": "VST(blind=FALSE)"}
    AnalysisService._validate_plot_matrix(valid, ["g1", "g2"], ["a", "b"])
    for field, value in [("feature_ids", ["unknown"]), ("sample_ids", ["b", "a"]), ("values", [[float("nan"), 2]]), ("transform", "")]:
        broken = deepcopy(valid)
        broken[field] = value
        with pytest.raises(ValueError):
            AnalysisService._validate_plot_matrix(broken, ["g1", "g2"], ["a", "b"])
    with pytest.raises(ValueError):
        AnalysisService._validate_plot_matrix(None, ["g1", "g2"], ["a", "b"])

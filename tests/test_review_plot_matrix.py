from types import SimpleNamespace

import numpy as np
import pytest

from rnaseq_helper.services.plot_service import PlotService


def _plan() -> SimpleNamespace:
    return SimpleNamespace(
        design={"assignments": {"c1": "control", "c2": "control", "t1": "test", "t2": "test"}},
        preprocessing={"transform": "none"},
        config=SimpleNamespace(fdr_threshold=0.05, lfc_threshold=1.0, top_heatmap_features=30),
    )


def test_plot_matrix_requires_runner_values_and_keeps_runner_feature_order() -> None:
    result = {
        "plot_matrix": {
            "feature_ids": ["g3", "g1"],
            "sample_ids": ["c1", "c2", "t1", "t2"],
            "values": [[8.0, 9.0, 18.0, 20.0], [100.0, 101.0, 110.0, 111.0]],
            "transform": "VST(blind=FALSE)",
        }
    }
    feature_ids, sample_ids, values, transform = PlotService._plot_matrix(result)
    assert feature_ids == ["g3", "g1"]
    assert sample_ids == ["c1", "c2", "t1", "t2"]
    assert np.array_equal(values, np.asarray(result["plot_matrix"]["values"]))
    assert transform == "VST(blind=FALSE)"

    with pytest.raises(ValueError, match="已变换的绘图矩阵"):
        PlotService._plot_matrix({})


def test_display_labels_prefer_gene_symbol_and_fall_back_to_feature_id() -> None:
    result = {
        "table": [
            {"feature_key": "g1", "gene_symbol": "G1"},
            {"feature_key": "g2", "gene_symbol": "None"},
            {"feature_key": "g3", "gene_symbol": "G1"},
            {"feature_key": "g4", "gene_symbol": None},
        ]
    }

    labels = PlotService._display_labels(result, ["g1", "g2", "g3", "g4"])

    assert labels == {
        "g1": "G1 (g1)",
        "g2": "g2",
        "g3": "G1 (g3)",
        "g4": "g4",
    }


def test_build_does_not_read_original_matrix_for_figures(tmp_path) -> None:
    matrix = SimpleNamespace(values=SimpleNamespace(path=tmp_path / "project" / "prepared" / "matrix.tsv"))
    result = {
        "plot_matrix": {
            "feature_ids": ["g2", "g1"],
            "sample_ids": ["c1", "c2", "t1", "t2"],
            "values": [[8.0, 9.0, 18.0, 20.0], [100.0, 101.0, 110.0, 111.0]],
            "transform": "VST(blind=FALSE)",
        },
        "table": [],
    }
    figures = PlotService().build(matrix, _plan(), result)
    assert set(figures) == {"pca", "sample_correlation", "pvalue_histogram", "volcano", "top_heatmap"}
    assert all(path.exists() for path in figures.values())


def test_sample_correlation_masks_zero_variance_instead_of_filling_zero() -> None:
    values = np.asarray([[5.0, 1.0, 3.0], [5.0, 2.0, 4.0]])
    correlation = PlotService._sample_correlation(values)
    assert np.ma.isMaskedArray(correlation)
    assert correlation.mask[1, 0]
    assert correlation.mask[0, 1]
    assert correlation.mask[0, 0]
    assert not correlation.mask[1, 1]
    assert correlation[1, 1] == pytest.approx(1.0)


def test_heatmap_handles_only_zero_variance_selected_features(tmp_path) -> None:
    path = tmp_path / "empty-heatmap.png"
    result = {
        "table": [{"feature_key": "constant", "padj": 0.001, "log2FoldChange": 2.0}],
    }
    output = PlotService._heatmap(
        path,
        np.asarray([[7.0, 7.0, 7.0, 7.0]]),
        ["constant"],
        ["c1", "c2", "t1", "t2"],
        ["control", "control", "test", "test"],
        result,
        _plan(),
        "log2(filtered TPM + 1)",
    )
    assert output == path
    assert path.exists()
    assert path.stat().st_size > 0


def test_pca_handles_single_feature_plot_matrix(tmp_path) -> None:
    path = tmp_path / "single-feature-pca.png"
    output = PlotService._pca(
        path,
        np.asarray([[1.0, 2.0, 3.0, 4.0]]),
        ["c1", "c2", "t1", "t2"],
        ["control", "control", "test", "test"],
        _plan(),
        "VST(blind=FALSE)",
    )
    assert output == path
    assert path.exists()
    assert path.stat().st_size > 0


def test_pvalue_histogram_does_not_label_expression_transform_as_pvalue_transform(tmp_path, monkeypatch) -> None:
    from matplotlib.axes import Axes

    labels = []
    original_text = Axes.text

    def capture_text(self, x, y, text, *args, **kwargs):
        labels.append(str(text))
        return original_text(self, x, y, text, *args, **kwargs)

    monkeypatch.setattr(Axes, "text", capture_text)
    path = tmp_path / "p-values.png"

    PlotService._pvalue_histogram(
        path,
        {"table": [{"pvalue": 0.01}, {"pvalue": 0.5}, {"pvalue": None}, {"pvalue": 1.5}]},
    )

    assert "2 finite p-values" in labels
    assert not any("log2(x+1)" in label for label in labels)
    assert path.exists()
    assert path.stat().st_size > 0

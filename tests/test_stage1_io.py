import hashlib
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from openpyxl import Workbook
import xlwt

from rnaseq_helper.preparation.service import PreparationBlocked, PreparationService
from rnaseq_helper.recognition.scanner import AssetScanner
from rnaseq_helper.domain.models import MeasurementType, ValueScale
from rnaseq_helper.readers.geo_reader import GeoSeriesMatrixReader
from rnaseq_helper.readers.table_reader import TableReader


FIXTURE = Path(__file__).parent / "fixtures" / "company_counts.tsv"


class Stage1IoTests(unittest.TestCase):
    def test_scan_finds_table_and_hints_shape(self):
        result = AssetScanner().scan((FIXTURE,))
        self.assertEqual(len(result.assets), 1)
        self.assertEqual(result.assets[0].kind, "TABLE")
        self.assertEqual(result.assets[0].shape_hint, (7, 8))

    def test_prepare_requires_unit_and_scale_confirmation(self):
        asset = AssetScanner().scan((FIXTURE,)).assets[0]
        with tempfile.TemporaryDirectory() as temp:
            service = PreparationService()
            session = service.start(asset, Path(temp))
            self.assertEqual(session.recipe.header_row, 2)
            self.assertEqual(session.recipe.sample_columns, (2, 3, 4, 5, 6, 7))
            self.assertFalse(service.validate(session).passed)
            session = service.apply(session, {"measurement_type": MeasurementType.RAW_COUNT, "value_scale": ValueScale.LINEAR})
            summary = service.validate(session)
            self.assertTrue(summary.passed)
            matrix = service.finish(session)
            self.assertEqual(matrix.values.shape, (4, 6))
            self.assertTrue((Path(temp) / "prepared" / "expression_matrix.tsv").exists())
            self.assertTrue((Path(temp) / "preparation-recipe.json").exists())
            feature_metadata = (Path(temp) / "prepared" / "feature_metadata.tsv").read_text(encoding="utf-8")
            self.assertIn("gene_symbol", feature_metadata.splitlines()[0])

    def test_original_file_is_unchanged_and_duplicate_ids_block(self):
        before = hashlib.sha256(FIXTURE.read_bytes()).hexdigest()
        asset = AssetScanner().scan((FIXTURE,)).assets[0]
        with tempfile.TemporaryDirectory() as temp:
            service = PreparationService()
            session = service.start(asset, Path(temp))
            rows = list(session.raw_table.rows)
            rows[4] = (rows[3][0], *rows[4][1:])
            session = replace(session, raw_table=replace(session.raw_table, rows=tuple(rows)))
            session = service.apply(session, {"measurement_type": "RAW_COUNT", "value_scale": "LINEAR"})
            with self.assertRaises(PreparationBlocked):
                service.finish(session)
        self.assertEqual(hashlib.sha256(FIXTURE.read_bytes()).hexdigest(), before)

    def test_local_reference_is_recorded_without_changing_matrix_rows(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "counts.tsv"
            source.write_text(
                "gene_id\tCtrl_1\tCtrl_2\tTreat_1\tTreat_2\n"
                "g1\t100\t110\t220\t230\n"
                "g2\t50\t52\t55\t53\n"
                "g3\t80\t82\t160\t165\n"
                "g4\t10\t12\t20\t22\n",
                encoding="utf-8",
            )
            asset = AssetScanner().scan((source,)).assets[0]
            reference = Path(temp) / "reference.tsv"
            reference.write_text(
                "feature_key\tgene_symbol\n"
                "g1\tGENE1\n"
                "g2\tGENE2\n"
                "g2\tGENE2_ALT\n",
                encoding="utf-8",
            )
            service = PreparationService()
            session = service.start(asset, Path(temp) / "project")
            session = replace(session, reference_path=reference)
            session = service.apply(session, {"measurement_type": MeasurementType.RAW_COUNT, "value_scale": ValueScale.LINEAR})
            matrix = service.finish(session)
            feature_rows = (Path(temp) / "project" / "prepared" / "feature_metadata.tsv").read_text(encoding="utf-8").splitlines()
            assert feature_rows[0].endswith("\tgene_symbol")
            assert feature_rows[1].endswith("\tGENE1")
            assert feature_rows[2].endswith("\tGENE2;GENE2_ALT")
            assert len((Path(temp) / "project" / "prepared" / "expression_matrix.tsv").read_text(encoding="utf-8").splitlines()) == 5
            assert (Path(temp) / "project" / "references" / "reference-result.json").exists()
            assert matrix.feature_metadata.shape == (4, 3)

    def test_excel_sheet_and_formula_cache_are_read_without_execution(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "input.xlsx"
            workbook = Workbook()
            sheet = workbook.active
            sheet.title = "说明"
            sheet.append(["note", "not expression"])
            data = workbook.create_sheet("表达")
            data.append(["gene_id", "C1", "C2"])
            data.append(["g1", 1, 2])
            data["C3"] = "=1+1"
            workbook.save(path)
            reader = TableReader()
            self.assertEqual(reader.list_sheets(path), ("说明", "表达"))
            table = reader.read(path, "表达")
            self.assertEqual(table.rows[1], ("g1", "1", "2"))
            self.assertIn("C3", table.formula_cells)
            asset = AssetScanner().scan((path,)).assets[0]
            service = PreparationService()
            session = service.start(asset, Path(temp), "表达")
            session = service.apply(session, {"measurement_type": "RAW_COUNT", "value_scale": "LINEAR"})
            summary = service.validate(session)
            self.assertTrue(any(issue.code == "FORMULA_WITHOUT_CACHE" for issue in summary.issues))
            self.assertFalse(summary.passed)

    def test_legacy_xls_is_read_and_scanned(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "legacy.xls"
            workbook = xlwt.Workbook()
            notes = workbook.add_sheet("说明")
            notes.write(0, 0, "这是说明表")
            data = workbook.add_sheet("表达")
            for column, value in enumerate(("gene_id", "C1", "C2")):
                data.write(0, column, value)
            data.write(1, 0, "g1")
            data.write(1, 1, 1)
            data.write(1, 2, 2)
            data.write(2, 0, "g2")
            data.write(2, 1, 3)
            data.write(2, 2, xlwt.Formula("1+1"))
            workbook.save(str(path))

            reader = TableReader()
            self.assertEqual(reader.list_sheets(path), ("说明", "表达"))
            table = reader.read(path, "表达")
            self.assertEqual(table.rows[1], ("g1", "1.0", "2.0"))
            asset = AssetScanner().scan((path,)).assets[0]
            self.assertEqual(asset.kind, "TABLE")
            self.assertFalse(GeoSeriesMatrixReader.looks_like(path))

    def test_vendor_text_matrix_named_xls_ignores_unit_in_filename(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "gene.TPM.matrix.annotation.xls"
            path.write_text(
                "Gene id\tGene name\tBio_type\tDZ_1\tCA_1\tYDW_1\n"
                "ENSMUSG0001\tGeneA\tprotein_coding\t1.0\t2.0\t3.0\n"
                "ENSMUSG0002\tGeneB\tprotein_coding\t4.0\t5.0\t6.0\n",
                encoding="utf-8",
            )
            reader = TableReader()
            self.assertEqual(reader.list_sheets(path), (None,))
            table = reader.read(path)
            self.assertEqual(table.delimiter, "\t")
            self.assertEqual(table.rows[0][:4], ("Gene id", "Gene name", "Bio_type", "DZ_1"))
            self.assertEqual(table.rows[1][4], "2.0")
            asset = AssetScanner().scan((path,)).assets[0]
            self.assertEqual(asset.kind, "TABLE")
            self.assertEqual(asset.measurement_hint, MeasurementType.UNKNOWN)
            self.assertEqual(asset.scale_hint, ValueScale.UNKNOWN)


if __name__ == "__main__":
    unittest.main()

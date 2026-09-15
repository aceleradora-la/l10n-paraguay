# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
from datetime import timedelta
from unittest import mock

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import L10nPyEdiCommon


@tagged("post_install", "-at_install", "l10n_py")
class TestEdiResultContract(L10nPyEdiCommon):
    """Contrato de resultado normalizado y máquina de estados, sin conector."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Connector = cls.env["l10n_py.edi.connector"]
        cls.Move = cls.env["account.move"]

    def _accepted(self, cdc="01800094017001001000000112023010112345678901", **extra):
        doc = {
            "cdc": cdc,
            "qr": "https://ekuatia.set.gov.py/consultas-test/qr?nVersion=150",
            "xml": "<rDE/>",
            "protocol": "1234567890",
            "approval_date": "2026-09-15T10:00:00-03:00",
            "digest": "abc",
            "code": "0260",
            "message": "Autorizado el DE",
        }
        doc.update(extra)
        return self.Connector._make_result("accepted", documents=[doc])

    # ---------- _make_result / normalización ----------

    def test_make_result_shape(self):
        res = self.Connector._make_result(
            "rejected", errors=[("0160", "Firma inválida", "sifen"), {"message": "x"}]
        )
        self.assertFalse(res["success"])
        self.assertEqual(res["status"], "rejected")
        self.assertEqual(res["result"], {"deList": [], "loteId": None})
        self.assertEqual(
            res["errors"][0],
            {"code": "0160", "message": "Firma inválida", "source": "sifen"},
        )
        self.assertEqual(res["errors"][1]["source"], "provider")
        self.assertIn("0160: Firma inválida", res["error"])
        with self.assertRaises(ValueError):
            self.Connector._make_result("bogus")

    def test_normalize_legacy_results(self):
        legacy_ok = {
            "success": True,
            "result": {"deList": [{"cdc": "X"}], "loteId": "L1"},
        }
        res = self.Move._l10n_py_normalize_result(legacy_ok)
        self.assertEqual(res["status"], "accepted")
        self.assertEqual(res["result"]["loteId"], "L1")

        legacy_batch = {"success": True, "result": {"loteId": "L2"}}
        self.assertEqual(
            self.Move._l10n_py_normalize_result(legacy_batch)["status"], "processing"
        )

        legacy_fail = {"success": False, "error": "Timbrado vencido"}
        res = self.Move._l10n_py_normalize_result(legacy_fail)
        self.assertEqual(res["status"], "rejected")
        self.assertEqual(res["errors"][0]["message"], "Timbrado vencido")

        self.assertEqual(
            self.Move._l10n_py_normalize_result("garbage")["status"], "error"
        )

    # ---------- aplicación de resultados ----------

    def test_post_sets_to_send_only_for_electronic_docs(self):
        move = self._create_invoice()
        self.assertEqual(move.l10n_py_edi_status, "to_send")
        self.assertTrue(move.l10n_py_full_invoice_number)

    def test_apply_accepted(self):
        move = self._create_invoice()
        with mock.patch.object(type(move), "_generate_kude", return_value=None):
            move._l10n_py_edi_apply_result(self._accepted())
        self.assertEqual(move.l10n_py_edi_status, "accepted")
        self.assertEqual(
            move.l10n_py_cdc, "01800094017001001000000112023010112345678901"
        )
        self.assertEqual(move.l10n_py_edi_protocol, "1234567890")
        self.assertEqual(move.l10n_py_edi_response_code, "0260")
        self.assertEqual(move.l10n_py_edi_digest, "abc")
        # 10:00 -03:00 → 13:00 UTC
        self.assertEqual(
            fields.Datetime.to_string(move.l10n_py_edi_approval_date),
            "2026-09-15 13:00:00",
        )
        self.assertTrue(move.l10n_py_edi_xml)
        self.assertEqual(move.l10n_py_edi_xml_filename, f"{move.l10n_py_cdc}.xml")
        self.assertTrue(move.l10n_py_qr_code)
        self.assertFalse(move.l10n_py_edi_errors)

    def test_apply_accepted_obs_and_processing(self):
        move = self._create_invoice()
        move._l10n_py_edi_apply_result(
            self.Connector._make_result("processing", batch_id="LOTE-1")
        )
        self.assertEqual(move.l10n_py_edi_status, "processing")
        self.assertEqual(move.l10n_py_edi_batch_id, "LOTE-1")
        with mock.patch.object(type(move), "_generate_kude", return_value=None):
            move._l10n_py_edi_apply_result(
                self.Connector._make_result(
                    "accepted_obs",
                    documents=[
                        {"cdc": "C" * 44, "message": "Aprobado con observación"}
                    ],
                )
            )
        self.assertEqual(move.l10n_py_edi_status, "accepted_obs")
        self.assertEqual(move.l10n_py_edi_message, "Aprobado con observación")
        self.assertTrue(move.l10n_py_edi_approval_date)

    def test_apply_rejected_and_error_keep_readable_errors(self):
        move = self._create_invoice()
        move._l10n_py_edi_apply_result(
            self.Connector._make_result(
                "rejected",
                errors=[
                    ("0160", "Firma inválida", "sifen"),
                    ("FS-500", "Caída", "provider"),
                ],
            )
        )
        self.assertEqual(move.l10n_py_edi_status, "rejected")
        self.assertIn("[SIFEN] 0160: Firma inválida", move.l10n_py_edi_errors)
        self.assertIn("FS-500", move.l10n_py_edi_errors)
        self.assertFalse(move.l10n_py_edi_retryable)

        move._l10n_py_edi_apply_result(
            self.Connector._error_result("timeout", code="DIR-TIMEOUT")
        )
        self.assertEqual(move.l10n_py_edi_status, "error")
        self.assertTrue(move.l10n_py_edi_retryable)

    # ---------- guardas y plazos ----------

    def test_approved_document_cannot_be_reset(self):
        move = self._create_invoice()
        with mock.patch.object(type(move), "_generate_kude", return_value=None):
            move._l10n_py_edi_apply_result(self._accepted())
        with self.assertRaises(UserError):
            move.button_draft()
        with self.assertRaises(UserError):
            move.button_cancel()

    def test_cancel_deadline_from_approval_date(self):
        move = self._create_invoice()
        self.assertFalse(move._l10n_py_cancel_deadline())
        with mock.patch.object(type(move), "_generate_kude", return_value=None):
            move._l10n_py_edi_apply_result(self._accepted())
        self.assertEqual(
            move._l10n_py_cancel_deadline(),
            move.l10n_py_edi_approval_date + timedelta(hours=48),
        )
        move._validate_cancel_deadline()  # dentro del plazo: no levanta
        move.l10n_py_edi_approval_date = fields.Datetime.now() - timedelta(hours=49)
        with self.assertRaisesRegex(UserError, "plazo de cancelación"):
            move._validate_cancel_deadline()

        nce = self._create_invoice(doc_type=self.doc_type_nce, move_type="out_refund")
        nce.l10n_py_edi_approval_date = fields.Datetime.now() - timedelta(hours=100)
        nce._validate_cancel_deadline()  # NCE: 168 h

    def test_apply_cancel_result(self):
        move = self._create_invoice()
        with mock.patch.object(type(move), "_generate_kude", return_value=None):
            move._l10n_py_edi_apply_result(self._accepted())
        move._l10n_py_edi_apply_cancel_result(self.Connector._make_result("processing"))
        self.assertEqual(move.l10n_py_edi_status, "to_cancel")
        move._l10n_py_edi_apply_cancel_result(
            self.Connector._make_result(
                "rejected", errors=[("0501", "Fuera de plazo", "sifen")]
            )
        )
        self.assertEqual(move.l10n_py_edi_status, "accepted")
        self.assertIn("0501", move.l10n_py_edi_errors)
        move._l10n_py_edi_apply_cancel_result(self.Connector._make_result("accepted"))
        self.assertEqual(move.l10n_py_edi_status, "cancelled")

    def test_constraints_accumulate_and_check_connector(self):
        move = self._create_invoice(partner=self.partner_no_contribuyente)
        move.partner_id.write({"street": False, "l10n_py_doc_number": False})
        errors = move._l10n_py_check_edi_constraints()
        self.assertTrue(any("conector" in e for e in errors))
        self.assertTrue(any("documento" in e for e in errors))
        self.assertTrue(any("dirección" in e for e in errors))
        with self.assertRaises(UserError) as cm:
            move._validate_edi_data()
        self.assertGreaterEqual(str(cm.exception).count("\n"), 2)

    def test_transmission_deadline_uses_param(self):
        self.env["ir.config_parameter"].sudo().set_param(
            "l10n_py.transmission_hours", "24"
        )
        move = self._create_invoice()
        move._compute_transmission_deadline()
        expected = fields.Datetime.from_string(
            f"{move.invoice_date} 00:00:00"
        ) + timedelta(hours=24)
        self.assertEqual(move.l10n_py_transmission_deadline, expected)
        self.assertEqual(self.Move._l10n_py_get_param("l10n_py.mt_version", "0"), "150")

# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
from odoo.tests import tagged

from .common import L10nPyEdiCommon


@tagged("post_install", "-at_install", "l10n_py")
class TestEdiLinesTotals(L10nPyEdiCommon):
    """Ítems y totales SIFEN: afectación desde account.tax, descuentos y
    redondeo en guaraníes."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.tax_exo = cls._create_tax("Exonerado", 0.0)
        cls.tax_exo.l10n_py_iva_affectation = "2"
        cls.tax_partial = cls._create_tax("IVA 10% parcial", 10.0)
        cls.tax_partial.write(
            {"l10n_py_iva_affectation": "4", "l10n_py_taxable_proportion": 50.0}
        )

    def test_items_and_totals_pyg(self):
        move = self._create_invoice(
            lines=[
                (self.product, 2, 110000, self.tax_10),  # 220.000 c/IVA
                (self.product, 1, 105000, self.tax_5),  # 105.000 c/IVA
                (self.service, 1, 50000, self.tax_exempt),
                (self.service, 1, 30000, self.tax_exo),
            ]
        )
        self.assertEqual(move.currency_id.name, "PYG")
        self.assertEqual(move.l10n_py_amount_subtotal_10, 220000)
        self.assertEqual(move.l10n_py_base_10, 200000)
        self.assertEqual(move.l10n_py_amount_iva_10, 20000)
        self.assertEqual(move.l10n_py_amount_subtotal_5, 105000)
        self.assertEqual(move.l10n_py_base_5, 100000)
        self.assertEqual(move.l10n_py_amount_iva_5, 5000)
        self.assertEqual(move.l10n_py_amount_exempt, 50000)
        self.assertEqual(move.l10n_py_amount_exonerated, 30000)
        self.assertEqual(move.l10n_py_amount_iva_total, 25000)
        self.assertEqual(move.l10n_py_base_total, 300000)
        self.assertEqual(move.l10n_py_total_operation, 405000)
        self.assertEqual(move.l10n_py_amount_rounding, 0)
        for value in (
            move.l10n_py_amount_iva_10,
            move.l10n_py_base_5,
            move.l10n_py_total_operation,
        ):
            self.assertEqual(value, int(value))

        data = move._prepare_edi_document_data()
        items = data["items"]
        self.assertEqual([i["ivaTipo"] for i in items], [1, 1, 3, 2])
        self.assertEqual([i["iva"] for i in items], [10, 5, 0, 0])
        self.assertEqual(items[0]["baseGravada"], 200000)
        self.assertEqual(items[0]["liquidacionIva"], 20000)
        self.assertEqual(items[2]["baseExenta"], 50000)
        self.assertEqual(items[0]["unidadMedida"], 77)
        self.assertEqual(data["totales"]["totalExonerado"], 30000)
        self.assertEqual(data["totales"]["totalOperacion"], 405000)

    def test_discount_and_partial(self):
        move = self._create_invoice(
            lines=[(self.product, 1, 110000, self.tax_10)],
        )
        move.button_draft()
        move.invoice_line_ids.discount = 10.0  # 110.000 - 10% = 99.000 c/IVA
        move.action_post()
        self.assertEqual(move.l10n_py_amount_discount, 11000)
        self.assertEqual(move.l10n_py_amount_subtotal_10, 99000)
        self.assertEqual(move.l10n_py_base_10, 90000)
        self.assertEqual(move.l10n_py_amount_iva_10, 9000)
        item = move._prepare_edi_document_data()["items"][0]
        self.assertEqual(item["descuento"], 11000)
        self.assertEqual(item["porcentajeDescuento"], 10.0)
        self.assertEqual(data_total := move.l10n_py_total_operation, 99000)
        self.assertEqual(data_total, move.amount_total)

        partial = self._create_invoice(
            lines=[(self.product, 1, 110000, self.tax_partial)]
        )
        # 50 % gravado: base = 55.000 / 1.1 = 50.000; IVA 5.000; exento 55.000
        self.assertEqual(partial.l10n_py_base_10, 50000)
        self.assertEqual(partial.l10n_py_amount_iva_10, 5000)
        self.assertEqual(partial.l10n_py_amount_exempt, 55000)
        item = partial._prepare_edi_document_data()["items"][0]
        self.assertEqual(item["ivaTipo"], 4)
        self.assertEqual(item["ivaBase"], 50.0)

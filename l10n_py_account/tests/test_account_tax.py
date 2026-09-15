# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install", "l10n_py")
class TestAccountTaxSifen(TransactionCase):
    def _tax(self, amount, **vals):
        return self.env["account.tax"].create(
            {
                "name": f"IVA {amount}",
                "amount": amount,
                "amount_type": "percent",
                "type_tax_use": "sale",
                **vals,
            }
        )

    def test_defaults_from_amount(self):
        self.assertEqual(self._tax(10)._l10n_py_get_iva_params(), (10, "1", 100.0))
        self.assertEqual(self._tax(5)._l10n_py_get_iva_params(), (5, "1", 100.0))
        self.assertEqual(self._tax(0)._l10n_py_get_iva_params(), (0, "3", 100.0))
        self.assertEqual(
            self.env["account.tax"]._l10n_py_get_iva_params(), (0, "3", 100.0)
        )

    def test_override_exonerated_and_partial(self):
        exo = self._tax(0, l10n_py_iva_affectation="2")
        self.assertEqual(exo._l10n_py_get_iva_params(), (0, "2", 100.0))
        partial = self._tax(
            10, l10n_py_iva_affectation="4", l10n_py_taxable_proportion=30.0
        )
        self.assertEqual(partial._l10n_py_get_iva_params(), (10, "4", 30.0))
        # cambiar el porcentaje no pisa una afectación ya definida
        partial.amount = 5
        self.assertEqual(partial.l10n_py_iva_affectation, "4")

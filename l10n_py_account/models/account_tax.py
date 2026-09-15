# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
from odoo import api, fields, models


class AccountTax(models.Model):
    _inherit = "account.tax"

    # Campos SIFEN del grupo E7 (gCamIVA). El builder del DE los lee de aquí y
    # nunca del importe calculado: un impuesto "IVA 10%" con amount=10 es el
    # caso común, pero exonerado, exento y gravado parcial no se distinguen
    # por el porcentaje.
    l10n_py_iva_affectation = fields.Selection(
        [
            ("1", "Gravado IVA"),
            ("2", "Exonerado (Art. 83 - Ley 125/91)"),
            ("3", "Exento"),
            ("4", "Gravado parcial (gravado - exento)"),
        ],
        string="Afectación tributaria IVA (E731)",
        compute="_compute_l10n_py_iva_affectation",
        store=True,
        readonly=False,
    )
    l10n_py_iva_rate = fields.Selection(
        [("10", "10%"), ("5", "5%"), ("0", "0%")],
        string="Tasa IVA (E734)",
        compute="_compute_l10n_py_iva_rate",
        store=True,
        readonly=False,
    )
    l10n_py_taxable_proportion = fields.Float(
        string="Proporción gravada (E733)",
        default=100.0,
        digits=(5, 2),
        help="dPropIVA: porcentaje de la base que está gravada. 100 salvo para "
        "'gravado parcial'.",
    )

    def _l10n_py_iva_defaults(self):
        """``(afectación, tasa)`` por defecto según el porcentaje del impuesto."""
        self.ensure_one()
        amount = self.amount if self.amount_type == "percent" else 0
        if amount == 10:
            return "1", "10"
        if amount == 5:
            return "1", "5"
        return "3", "0"

    # Computes separados: si uno de los campos viene en create/write, Odoo no
    # recalcula los demás campos del mismo método, y el otro quedaría vacío.
    @api.depends("amount", "amount_type")
    def _compute_l10n_py_iva_affectation(self):
        for tax in self:
            tax.l10n_py_iva_affectation = (
                tax.l10n_py_iva_affectation or tax._l10n_py_iva_defaults()[0]
            )

    @api.depends("amount", "amount_type")
    def _compute_l10n_py_iva_rate(self):
        for tax in self:
            tax.l10n_py_iva_rate = (
                tax.l10n_py_iva_rate or tax._l10n_py_iva_defaults()[1]
            )

    def _l10n_py_get_iva_params(self):
        """``(tasa:int, afectación:str, proporción:float)`` del primer impuesto
        con datos SIFEN; sin impuesto → exento."""
        for tax in self:
            if tax.l10n_py_iva_affectation:
                rate = int(tax.l10n_py_iva_rate or "0")
                affectation = tax.l10n_py_iva_affectation
                if affectation in ("2", "3"):
                    rate = 0
                proportion = (
                    tax.l10n_py_taxable_proportion
                    if affectation == "4" and tax.l10n_py_taxable_proportion
                    else 100.0
                )
                return rate, affectation, proportion
        return 0, "3", 100.0

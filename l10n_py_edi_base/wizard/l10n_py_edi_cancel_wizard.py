# l10n_py_edi_base/wizard/l10n_py_edi_cancel_wizard.py

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class EDICancelWizard(models.TransientModel):
    _name = "l10n_py.edi.cancel.wizard"
    _description = "Wizard para cancelar documento EDI"

    invoice_id = fields.Many2one("account.move", string="Factura", required=True)
    motive = fields.Text(string="Motivo de Cancelación", required=True)
    cancel_deadline = fields.Datetime(
        string="Plazo de cancelación",
        compute="_compute_cancel_deadline",
        help="Límite según el tipo de documento (48 h FE/AFE, 168 h NCE/NDE/NRE) "
        "contado desde la aprobación de SIFEN.",
    )

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        if self.env.context.get("active_id"):
            res["invoice_id"] = self.env.context["active_id"]
        return res

    @api.depends("invoice_id")
    def _compute_cancel_deadline(self):
        for wizard in self:
            wizard.cancel_deadline = (
                wizard.invoice_id._l10n_py_cancel_deadline()
                if wizard.invoice_id
                else False
            )

    def action_cancel(self):
        """Cancelar documento EDI con verificación de plazos."""
        self.ensure_one()
        if not self.invoice_id:
            raise UserError(_("No se seleccionó una factura"))
        if not self.invoice_id.l10n_py_cdc:
            raise UserError(_("La factura no tiene CDC, no se puede cancelar"))
        self.invoice_id.action_cancel_edi(reason=self.motive)
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Cancelación"),
                "message": self.invoice_id.l10n_py_edi_message,
                "type": "success",
                "sticky": False,
            },
        }

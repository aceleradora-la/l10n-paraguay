# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
from odoo import _, api, fields, models
from odoo.exceptions import UserError

from ..models.l10n_py_edi_event import EVENT_TYPES, RECEIVER_EVENTS


class L10nPyEdiEventWizard(models.TransientModel):
    _name = "l10n_py.edi.event.wizard"
    _description = "Enviar evento SIFEN"

    move_id = fields.Many2one("account.move", string="Documento", required=True)
    event_type = fields.Selection(
        [t for t in EVENT_TYPES if t[0] != "cancel"],
        required=True,
    )
    partner_id = fields.Many2one("res.partner", string="Receptor a nominar")
    reason = fields.Text(string="Motivo")
    conformity_type = fields.Selection([("1", "Total"), ("2", "Parcial")], default="1")
    issue_date = fields.Datetime(string="Fecha de emisión del DE")
    receipt_date = fields.Datetime(
        string="Fecha de recepción", default=fields.Datetime.now
    )
    total_pyg = fields.Float(string="Total en guaraníes", digits=(23, 8))
    is_receiver = fields.Boolean(compute="_compute_is_receiver")

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        move = self.env["account.move"].browse(self.env.context.get("active_id"))
        if move:
            res["move_id"] = move.id
            receiver = move.move_type in ("in_invoice", "in_refund")
            res.setdefault(
                "event_type", "receipt_notification" if receiver else "nomination"
            )
            res.setdefault(
                "issue_date",
                fields.Datetime.to_datetime(move.invoice_date)
                if move.invoice_date
                else False,
            )
            res.setdefault("total_pyg", move.amount_total)
        return res

    @api.depends("move_id")
    def _compute_is_receiver(self):
        for wizard in self:
            wizard.is_receiver = wizard.move_id.move_type in ("in_invoice", "in_refund")

    def action_send(self):
        self.ensure_one()
        if self.event_type in RECEIVER_EVENTS and not self.is_receiver:
            raise UserError(
                _("Los eventos del receptor se registran sobre documentos recibidos.")
            )
        if self.event_type == "nomination" and self.is_receiver:
            raise UserError(_("La nominación aplica a documentos emitidos."))
        event = self.env["l10n_py.edi.event"].create(
            {
                "move_id": self.move_id.id,
                "company_id": self.move_id.company_id.id,
                "cdc": self.move_id.l10n_py_cdc,
                "event_type": self.event_type,
                "partner_id": self.partner_id.id,
                "reason": self.reason,
                "conformity_type": self.conformity_type,
                "issue_date": self.issue_date,
                "receipt_date": self.receipt_date,
                "total_pyg": self.total_pyg,
            }
        )
        event.action_send()
        if event.state in ("rejected", "error"):
            raise UserError(
                _("El evento no fue aceptado (%(state)s):\n%(errors)s")
                % {
                    "state": event.state,
                    "errors": event.errors or event.response_message,
                }
            )
        return {
            "type": "ir.actions.act_window",
            "res_model": "l10n_py.edi.event",
            "res_id": event.id,
            "view_mode": "form",
            "target": "current",
        }


class L10nPyEdiContingencyWizard(models.TransientModel):
    _name = "l10n_py.edi.contingency.wizard"
    _description = "Emitir en contingencia"

    move_ids = fields.Many2many("account.move", string="Documentos", required=True)
    motive = fields.Char(string="Motivo de la contingencia", required=True)

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        ids = self.env.context.get("active_ids") or []
        if ids:
            res["move_ids"] = [(6, 0, ids)]
        return res

    def action_confirm(self):
        self.ensure_one()
        self.move_ids._l10n_py_switch_to_contingency(self.motive)
        return {"type": "ir.actions.act_window_close"}

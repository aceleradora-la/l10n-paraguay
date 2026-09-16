# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
"""Eventos SIFEN (MT v150 §6): registro por operación con su estado, el
payload canónico enviado al conector y la respuesta de la DNIT.

Eventos del emisor: cancelación y nominación (el receptor innominado se
identifica después). Eventos del receptor (sobre un DE recibido de un
proveedor): notificación de recepción, conformidad, disconformidad y
desconocimiento. La inutilización de numeración tiene su propio modelo
(``l10n_py.number.inutilization``).
"""

import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

EVENT_TYPES = [
    ("cancel", "Cancelación"),
    ("nomination", "Nominación del receptor"),
    ("receipt_notification", "Notificación de recepción"),
    ("receipt_conformity", "Conformidad"),
    ("receipt_disconformity", "Disconformidad"),
    ("receipt_unknown", "Desconocimiento"),
]
EMITTER_EVENTS = ("cancel", "nomination")
RECEIVER_EVENTS = (
    "receipt_notification",
    "receipt_conformity",
    "receipt_disconformity",
    "receipt_unknown",
)
# Eventos que exigen motivo (mOtEve: 5..500 caracteres)
EVENTS_WITH_REASON = (
    "cancel",
    "nomination",
    "receipt_disconformity",
    "receipt_unknown",
)


class L10nPyEdiEvent(models.Model):
    _name = "l10n_py.edi.event"
    _description = "Evento SIFEN"
    _inherit = ["mail.thread"]
    _order = "id desc"

    name = fields.Char(compute="_compute_name", store=True)
    company_id = fields.Many2one(
        "res.company",
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )
    move_id = fields.Many2one(
        "account.move",
        string="Documento",
        index=True,
        ondelete="cascade",
        help="Documento electrónico emitido o recibido al que se refiere el evento.",
    )
    cdc = fields.Char(
        string="CDC",
        size=44,
        help="CDC del DE afectado. Se toma del documento si está vacío.",
    )
    event_type = fields.Selection(EVENT_TYPES, required=True, index=True)
    state = fields.Selection(
        [
            ("draft", "Borrador"),
            ("sent", "Enviado"),
            ("accepted", "Aprobado"),
            ("rejected", "Rechazado"),
            ("error", "Error"),
        ],
        default="draft",
        required=True,
        index=True,
        tracking=True,
        copy=False,
    )
    reason = fields.Text(
        string="Motivo",
        help="Motivo del evento (mOtEve): entre 5 y 500 caracteres.",
    )
    # nominación
    partner_id = fields.Many2one(
        "res.partner",
        string="Receptor nominado",
        help="Receptor real del DE emitido como innominado.",
    )
    # eventos del receptor
    conformity_type = fields.Selection(
        [("1", "Total"), ("2", "Parcial")],
        string="Tipo de conformidad",
        default="1",
    )
    issue_date = fields.Datetime(
        string="Fecha de emisión del DE",
        help="dFecEmi del documento recibido (notificación y desconocimiento).",
    )
    receipt_date = fields.Datetime(
        string="Fecha de recepción",
        help="dFecRecep: cuándo se recibió el DE "
        "(notificación, conformidad, desconocimiento).",
    )
    total_pyg = fields.Float(
        string="Total en guaraníes",
        digits=(23, 8),
        help="dTotalGs del DE recibido (notificación de recepción).",
    )
    # resultado
    payload_json = fields.Json(string="Payload enviado", readonly=True, copy=False)
    event_number = fields.Char(
        string="Id del evento",
        readonly=True,
        copy=False,
        help="Identificador devuelto por el conector (rEve/@Id o id del proveedor).",
    )
    protocol = fields.Char(string="Protocolo SIFEN", readonly=True, copy=False)
    response_code = fields.Char(string="Código de respuesta", readonly=True, copy=False)
    response_message = fields.Char(string="Mensaje", readonly=True, copy=False)
    errors = fields.Text(readonly=True, copy=False)
    sent_date = fields.Datetime(readonly=True, copy=False)
    user_id = fields.Many2one(
        "res.users",
        string="Usuario",
        default=lambda self: self.env.user,
        readonly=True,
    )

    @api.depends("event_type", "cdc", "move_id")
    def _compute_name(self):
        labels = dict(EVENT_TYPES)
        for event in self:
            ref = event.move_id.display_name if event.move_id else (event.cdc or "")
            event.name = f"{labels.get(event.event_type, event.event_type)} - {ref}"

    @api.onchange("move_id")
    def _onchange_move_id(self):
        for event in self:
            if event.move_id:
                event.cdc = event.move_id.l10n_py_cdc
                event.company_id = event.move_id.company_id
                if event.move_id.invoice_date and not event.issue_date:
                    event.issue_date = fields.Datetime.to_datetime(
                        event.move_id.invoice_date
                    )
                if event.move_id.amount_total and not event.total_pyg:
                    event.total_pyg = event.move_id.amount_total

    # ------------------------------------------------------------ helpers
    def _get_cdc(self):
        self.ensure_one()
        cdc = (self.cdc or self.move_id.l10n_py_cdc or "").strip()
        if len(cdc) != 44 or not cdc.isdigit():
            raise UserError(_("El evento necesita el CDC (44 dígitos) del documento."))
        return cdc

    def _get_connector(self):
        self.ensure_one()
        connector = (
            self.env["l10n_py.edi.connector"]
            .sudo()
            .search([("company_id", "=", self.company_id.id)], limit=1)
        )
        if not connector:
            raise UserError(_("No hay un conector EDI configurado para esta empresa"))
        return connector

    def _receiver_company_data(self):
        """Datos del receptor cuando el receptor es la propia compañía."""
        company = self.company_id
        return {
            "tipoReceptor": 1 if company.l10n_py_ruc else 2,
            "nombre": company.name,
            "ruc": company.l10n_py_ruc or "",
            "dv": company.l10n_py_dv or "",
            "documentoTipo": 1,
            "documentoNumero": company.partner_id.vat or "",
        }

    @staticmethod
    def _iso(value):
        return fields.Datetime.to_string(value).replace(" ", "T") if value else ""

    def _prepare_payload(self):
        """Dict canónico del evento (claves compartidas por todos los conectores)."""
        self.ensure_one()
        cdc = self._get_cdc()
        reason = (self.reason or "").strip()
        if self.event_type in EVENTS_WITH_REASON and len(reason) < 5:
            raise UserError(_("El motivo debe tener al menos 5 caracteres."))
        if self.event_type == "cancel":
            return {"cdc": cdc, "motivo": reason}
        if self.event_type == "nomination":
            if not self.partner_id:
                raise UserError(_("Seleccione el receptor a nominar."))
            move = self.move_id or self.env["account.move"].with_company(
                self.company_id
            )
            data = move._prepare_customer_data(partner=self.partner_id)
            data.update(
                {
                    "cdc": cdc,
                    "motivo": reason,
                    "codigo": self.partner_id.ref or str(self.partner_id.id),
                }
            )
            return data
        base = {
            "cdc": cdc,
            "fechaRecepcion": self._iso(self.receipt_date or fields.Datetime.now()),
        }
        if self.event_type == "receipt_conformity":
            base["tipoConformidad"] = int(self.conformity_type or "1")
            return base
        if self.event_type == "receipt_disconformity":
            return {"cdc": cdc, "motivo": reason}
        base.update(self._receiver_company_data())
        base["fechaEmision"] = self._iso(
            self.issue_date or self.move_id.invoice_date or fields.Datetime.now()
        )
        if self.event_type == "receipt_notification":
            base["totalPYG"] = self.total_pyg or (
                self.move_id.amount_total if self.move_id else 0
            )
        else:  # receipt_unknown
            base["motivo"] = reason
        return base

    # ------------------------------------------------------------- envío
    def action_send(self):
        for event in self:
            if event.state not in ("draft", "error", "rejected"):
                raise UserError(
                    _("El evento '%s' ya fue enviado.") % event.display_name
                )
            connector = event._get_connector()
            if not connector.supports(event.event_type):
                raise UserError(
                    _("El proveedor '%(provider)s' no soporta el evento '%(event)s'.")
                    % {
                        "provider": connector.provider_type,
                        "event": dict(EVENT_TYPES)[event.event_type],
                    }
                )
            payload = event._prepare_payload()
            event.write({"payload_json": payload, "sent_date": fields.Datetime.now()})
            try:
                if event.event_type == "cancel":
                    raw = connector.cancel_document(payload["cdc"], payload["motivo"])
                else:
                    raw = connector.send_event(event.event_type, payload)
            except UserError:
                raise
            except Exception as e:
                _logger.exception("Error enviando evento %s", event.display_name)
                raw = connector._error_result(str(e), code="", source="provider")
            result = self.env["account.move"]._l10n_py_normalize_result(raw)
            event._apply_result(result)
        return True

    def _apply_result(self, result):
        self.ensure_one()
        status = result["status"]
        docs = result["result"].get("deList") or []
        doc = docs[0] if docs else {}
        vals = {
            "protocol": doc.get("protocol") or "",
            "response_code": doc.get("code") or "",
            "response_message": doc.get("message") or result.get("error") or "",
            "event_number": doc.get("event_id") or doc.get("id") or self.event_number,
            "errors": self.env["account.move"]._l10n_py_format_errors(
                result.get("errors")
            )
            or False,
        }
        if status in ("accepted", "accepted_obs"):
            vals["state"] = "accepted"
        elif status == "processing":
            vals["state"] = "sent"
        elif status == "rejected":
            vals["state"] = "rejected"
        else:
            vals["state"] = "error"
        self.write(vals)
        if self.move_id:
            self.move_id._l10n_py_on_event_result(self, result)
        return vals["state"]

    def action_draft(self):
        self.filtered(lambda e: e.state in ("error", "rejected")).write(
            {"state": "draft"}
        )

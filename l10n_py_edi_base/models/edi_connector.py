# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

import logging

from odoo import _, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# Estados normalizados que puede devolver un conector (contrato de resultado).
RESULT_STATUSES = ("accepted", "accepted_obs", "processing", "rejected", "error")


class EDIConnector(models.Model):
    """Interfaz de transporte hacia SIFEN.

    Cada proveedor (directo, FacturaSend, ...) agrega su valor a ``provider_type``
    con ``selection_add`` e implementa los métodos públicos. Todos devuelven el
    **contrato de resultado normalizado** (ver ``_make_result``)::

        {
            "success": bool,
            "status": "accepted" | "accepted_obs" | "processing" | "rejected" | "error",
            "result": {
                "deList": [{"cdc", "qr", "xml", "pdf", "protocol", "approval_date",
                            "digest", "code", "message"}],
                "loteId": str | None,
            },
            "errors": [{"code": str, "message": str, "source": "sifen" | "provider"}],
            "retryable": bool,
            "raw": str | dict | None,
        }

    ``success``/``result``/``error`` se mantienen por compatibilidad con los
    conectores que solo devuelven ``{"success", "result", "error"}``;
    ``account.move._l10n_py_normalize_result`` los completa.
    """

    _name = "l10n_py.edi.connector"
    _description = "Conector EDI Paraguay"

    name = fields.Char(required=True)
    company_id = fields.Many2one(
        "res.company",
        required=True,
        default=lambda self: self.env.company,
    )
    provider_type = fields.Selection(
        selection=[],
        string="Proveedor",
        required=True,
    )
    environment = fields.Selection(
        [("test", "Pruebas"), ("prod", "Producción")],
        default="test",
        required=True,
    )
    active = fields.Boolean(default=True)
    timeout = fields.Integer(default=30)

    _sql_constraints = [
        (
            "company_unique",
            "unique(company_id)",
            "Solo un conector EDI por empresa",
        ),
    ]

    # === Capacidades ===

    def _get_capabilities(self):
        """Capacidades del proveedor. Los conectores sobreescriben y actualizan.

        Claves: ``batch`` (envío por lote), ``async`` (respuesta diferida que
        requiere ``check_status``), ``events`` (set de eventos soportados:
        ``cancel``, ``inutilization``, ``nomination``, ``receipt_*``),
        ``pdf`` (el proveedor genera el KuDE), ``ruc_query``, ``contingency``,
        ``preview`` (puede generar XML/QR sin transmitir).
        """
        self.ensure_one()
        return {
            "batch": False,
            "async": False,
            "events": set(),
            "pdf": False,
            "ruc_query": False,
            "contingency": False,
            "preview": False,
        }

    def supports(self, capability):
        """``True`` si el proveedor soporta la capacidad (o el evento) dado."""
        caps = self._get_capabilities()
        if capability in caps:
            return bool(caps[capability])
        return capability in caps.get("events", set())

    # === Helpers del contrato de resultado ===

    @staticmethod
    def _make_result(
        status, documents=None, batch_id=None, errors=None, raw=None, retryable=False
    ):
        """Construye un resultado normalizado.

        :param status: uno de ``RESULT_STATUSES``.
        :param documents: lista de dicts con ``cdc``, ``qr``, ``xml``, ``pdf``,
            ``protocol``, ``approval_date``, ``digest``, ``code``, ``message``.
        :param errors: lista de ``(code, message)``, ``(code, message, source)``
            o dicts ``{"code", "message", "source"}``.
        """
        if status not in RESULT_STATUSES:
            raise ValueError(f"Estado de resultado inválido: {status}")
        norm_errors = []
        for err in errors or []:
            if isinstance(err, dict):
                code = err.get("code")
                message = err.get("message")
                source = err.get("source") or "provider"
            else:
                code, message = err[0], err[1]
                source = err[2] if len(err) > 2 else "provider"
            norm_errors.append(
                {
                    "code": str(code or ""),
                    "message": str(message or ""),
                    "source": source,
                }
            )
        error_text = "; ".join(
            f"{e['code']}: {e['message']}" if e["code"] else e["message"]
            for e in norm_errors
        )
        return {
            "success": status in ("accepted", "accepted_obs", "processing"),
            "status": status,
            "result": {"deList": list(documents or []), "loteId": batch_id},
            "errors": norm_errors,
            "error": error_text or None,
            "retryable": retryable,
            "raw": raw,
        }

    def _error_result(
        self, message, code="", source="provider", retryable=True, raw=None
    ):
        """Resultado de error (transporte/proveedor), reintentable por defecto."""
        return self._make_result(
            "error", errors=[(code, message, source)], raw=raw, retryable=retryable
        )

    # === Interfaz pública (cada proveedor implementa) ===

    def send_document(self, invoice_data):
        """Envía un DE. Devuelve el resultado normalizado."""
        self.ensure_one()
        raise UserError(
            _("El proveedor '%s' no implementa el envío de documentos")
            % self.provider_type
        )

    def send_documents(self, documents_data):
        """Envía varios DE. Devuelve una lista de resultados, uno por documento
        y en el mismo orden. Por defecto itera ``send_document``; los
        proveedores con lote sobreescriben."""
        self.ensure_one()
        return [self.send_document(data) for data in documents_data]

    def check_status(self, document_ref):
        """Consulta el estado de un DE o lote ya enviado (``document_ref`` es
        el CDC o el id de lote, según lo que haya devuelto el envío).
        Devuelve el resultado normalizado."""
        self.ensure_one()
        raise UserError(
            _("El proveedor '%s' no implementa la consulta de estado")
            % self.provider_type
        )

    def cancel_document(self, document_id, reason=""):
        """Evento de cancelación de un DE aprobado. Resultado normalizado
        (``status`` ``accepted`` = cancelado, ``processing`` = en proceso)."""
        self.ensure_one()
        raise UserError(
            _("El proveedor '%s' no implementa la cancelación") % self.provider_type
        )

    def send_event(self, event_type, payload):
        """Envía un evento genérico (``nomination``, ``receipt_conformity``...).
        Resultado normalizado."""
        self.ensure_one()
        raise UserError(
            _("El proveedor '%(provider)s' no implementa el evento '%(event)s'")
            % {"provider": self.provider_type, "event": event_type}
        )

    def inutilize_range(self, data):
        """Inutiliza un rango de numeración. Resultado normalizado."""
        self.ensure_one()
        raise UserError(
            _("El proveedor '%s' no implementa la inutilización") % self.provider_type
        )

    def get_document_pdf(self, cdc):
        """KuDE en PDF generado por el proveedor (bytes) o ``None`` si no lo
        genera: en ese caso lo produce el reporte QWeb de este módulo."""
        self.ensure_one()

    def query_ruc(self, ruc):
        """Consulta de RUC en SIFEN. Devuelve dict con ``ruc``, ``name``,
        ``status`` o levanta UserError si no está soportado."""
        self.ensure_one()
        raise UserError(
            _("El proveedor '%s' no implementa la consulta de RUC") % self.provider_type
        )

    def preview_document(self, invoice_data):
        """XML sin firmar ni enviar, o ``None`` si el proveedor no puede
        generarlo localmente (proveedores REST)."""
        self.ensure_one()

    def preview_qr(self, invoice_data):
        """``{"cdc", "qr"}`` sin transmitir, o ``None`` si no está soportado."""
        self.ensure_one()

    def test_connection(self):
        """Prueba de conectividad. Devuelve una acción de notificación."""
        self.ensure_one()
        raise UserError(
            _("El proveedor '%s' no implementa la prueba de conexión")
            % self.provider_type
        )

    def _notify(self, title, message, notif_type="success"):
        """Acción de notificación para ``test_connection`` y similares."""
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": title,
                "message": message,
                "type": notif_type,
                "sticky": notif_type != "success",
            },
        }

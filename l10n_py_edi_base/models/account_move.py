# l10n_py_edi_base/models/account_move.py

import logging
import re
import secrets
import string
from datetime import datetime, timezone

from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


class AccountMove(models.Model):
    _inherit = "account.move"

    # ============== CAMPOS EDI PARAGUAY ==============

    l10n_py_emission_type = fields.Selection(
        [("1", "Normal"), ("2", "Contingencia")],
        string="Tipo de Emisión",
        default="1",
        required=True,
    )

    l10n_py_transaction_type = fields.Selection(
        [
            ("1", "Venta de mercadería"),
            ("2", "Prestación de servicios"),
            ("3", "Mixto (Venta de mercadería y servicios)"),
            ("4", "Venta de activo fijo"),
            ("5", "Venta de divisas"),
            ("6", "Compra de divisas"),
            ("7", "Promoción o entrega de muestras"),
            ("8", "Donación"),
            ("9", "Anticipo"),
            ("10", "Compra de productos"),
            ("11", "Compra de servicios"),
            ("12", "Venta de crédito fiscal"),
            ("13", "Compra de crédito fiscal"),
        ],
        string="Tipo de Transacción",
        required=True,
        default="1",
    )

    l10n_py_presence_type = fields.Selection(
        [
            ("1", "Operación presencial"),
            ("2", "Operación electrónica"),
            ("3", "Operación telemarketing"),
            ("4", "Venta a domicilio"),
            ("5", "Operación bancaria"),
        ],
        string="Tipo de Presencia",
        default="1",
    )

    # Campos de respuesta EDI
    l10n_py_cdc = fields.Char(
        "CDC",
        readonly=True,
        copy=False,
        help="Código de Control del documento electrónico",
    )
    l10n_py_qr_code = fields.Binary("Código QR", readonly=True, copy=False)
    l10n_py_qr_string = fields.Char("String QR", readonly=True, copy=False)
    l10n_py_edi_xml = fields.Binary("XML Firmado", readonly=True, copy=False)
    l10n_py_edi_xml_filename = fields.Char("XML Filename", readonly=True, copy=False)
    l10n_py_kude_pdf = fields.Binary("KUDE (PDF)", readonly=True, copy=False)
    l10n_py_kude_filename = fields.Char("KUDE Filename", readonly=True, copy=False)
    # Registros ir.attachment que respaldan los Binary (res_field): son los
    # que se adjuntan al correo y los que se resguardan como comprobante.
    l10n_py_edi_xml_attachment_id = fields.Many2one(
        "ir.attachment",
        string="Adjunto XML",
        compute="_compute_l10n_py_edi_attachments",
    )
    l10n_py_kude_attachment_id = fields.Many2one(
        "ir.attachment",
        string="Adjunto KuDE",
        compute="_compute_l10n_py_edi_attachments",
    )

    l10n_py_edi_status = fields.Selection(
        [
            ("draft", "Borrador"),
            ("to_send", "Para Enviar"),
            ("sent", "Enviado"),
            ("processing", "Procesando"),
            ("accepted", "Aceptado"),
            ("accepted_obs", "Aceptado con observación"),
            ("rejected", "Rechazado"),
            ("to_cancel", "Cancelación en proceso"),
            ("cancelled", "Cancelado"),
            ("error", "Error"),
        ],
        string="Estado EDI",
        default="draft",
        readonly=True,
        copy=False,
        index=True,
    )

    l10n_py_edi_message = fields.Text("Mensaje EDI", readonly=True, copy=False)
    l10n_py_edi_errors = fields.Text(
        "Errores EDI",
        readonly=True,
        copy=False,
        help="Errores del último envío, un error por línea: código, mensaje y "
        "origen (sifen = rechazo de la DNIT; provider = error del intermediario "
        "o del transporte).",
    )
    l10n_py_edi_batch_id = fields.Char("ID de Lote", readonly=True, copy=False)
    l10n_py_edi_protocol = fields.Char(
        "Protocolo SIFEN",
        readonly=True,
        copy=False,
        help="Número de protocolo de autorización (dProtAut) devuelto por SIFEN",
    )
    l10n_py_edi_response_code = fields.Char(
        "Código de respuesta", readonly=True, copy=False, help="dCodRes de SIFEN"
    )
    l10n_py_edi_approval_date = fields.Datetime(
        "Fecha de aprobación",
        readonly=True,
        copy=False,
        help="Fecha/hora de aprobación por SIFEN (dFecProc). Desde aquí se "
        "cuentan los plazos de cancelación.",
    )
    l10n_py_edi_digest = fields.Char(
        "DigestValue", readonly=True, copy=False, help="DigestValue de la firma"
    )
    l10n_py_edi_retryable = fields.Boolean(
        "Reintentable", readonly=True, copy=False, default=False
    )
    l10n_py_security_code = fields.Char(
        "Código de Seguridad", size=9, readonly=True, copy=False
    )
    l10n_py_receipt_id = fields.Char("Receipt ID", help="ID único del sistema cliente")

    # Campos para contingencia
    l10n_py_contingency_motive = fields.Char("Motivo de Contingencia")

    # Documentos asociados (Grupo H SIFEN)
    l10n_py_associated_document_ids = fields.One2many(
        "l10n_py.associated.document",
        "move_id",
        string="Documentos Asociados",
        help="Documentos asociados al DTE (Grupo H del SIFEN)",
    )

    # Operación comercial (Grupo D — gOpeCom)
    l10n_py_exchange_rate_condition = fields.Selection(
        [("1", "Global"), ("2", "Por Ítem")],
        string="Condición Tipo de Cambio",
        default="1",
        help="Condición del tipo de cambio (D015)",
    )

    # Tipo de pago (Grupo E — gPaConEIni)
    l10n_py_payment_type = fields.Selection(
        [
            ("1", "Efectivo"),
            ("2", "Cheque"),
            ("3", "Tarjeta de crédito"),
            ("4", "Tarjeta de débito"),
            ("5", "Transferencia"),
            ("6", "Giro"),
            ("7", "Billetera electrónica"),
            ("8", "Tarjeta empresarial"),
            ("9", "Vale"),
            ("10", "Retención"),
            ("11", "Anticipo"),
            ("12", "Valor fiscal"),
            ("13", "Valor comercial"),
            ("14", "Compensación"),
            ("15", "Permuta"),
            ("16", "Pago bancario"),
        ],
        string="Tipo de Pago",
        default="1",
        help="Tipo de pago para condición contado (E606)",
    )

    # Campos AFE — Autofactura Electrónica (Grupo E — gCamAE)
    l10n_py_afe_constancia_type = fields.Selection(
        [("1", "No contribuyente"), ("2", "Microproductor")],
        string="Tipo de Constancia (EA002)",
    )
    l10n_py_afe_constancia_number = fields.Char(
        string="Número de Constancia (EA004)",
        size=20,
    )
    l10n_py_afe_constancia_control = fields.Char(
        string="Número de Control (EA005)",
        size=20,
    )
    l10n_py_afe_vendor_doc_type = fields.Selection(
        [
            ("1", "Cédula paraguaya"),
            ("2", "Pasaporte"),
            ("3", "Cédula extranjera"),
            ("4", "Carnet de residencia"),
        ],
        string="Tipo Doc. Vendedor (EA006)",
    )
    l10n_py_afe_vendor_doc_number = fields.Char(
        string="Nro. Doc. Vendedor (EA008)",
        size=20,
    )
    l10n_py_afe_vendor_name = fields.Char(
        string="Nombre Vendedor (EA009)",
    )
    l10n_py_afe_vendor_address = fields.Char(
        string="Dirección Vendedor (EA010)",
    )
    l10n_py_afe_vendor_house = fields.Integer(
        string="Nro. Casa Vendedor (EA011)",
    )
    l10n_py_afe_vendor_department = fields.Integer(
        string="Departamento Vendedor (EA012)",
    )
    l10n_py_afe_vendor_district = fields.Integer(
        string="Distrito Vendedor (EA014)",
    )
    l10n_py_afe_vendor_city = fields.Integer(
        string="Ciudad Vendedor (EA016)",
    )
    l10n_py_afe_provision_address = fields.Char(
        string="Dirección Provisión (EA018)",
    )
    l10n_py_afe_provision_department = fields.Integer(
        string="Departamento Provisión (EA019)",
    )
    l10n_py_afe_provision_district = fields.Integer(
        string="Distrito Provisión (EA021)",
    )
    l10n_py_afe_provision_city = fields.Integer(
        string="Ciudad Provisión (EA023)",
    )

    # Campo auxiliar para visibilidad en la vista
    l10n_py_doc_type_code = fields.Char(
        compute="_compute_l10n_py_doc_type_code",
    )

    # Campos NRE (Nota de Remisión Electrónica — tipo 7)
    l10n_py_nre_motive = fields.Selection(
        [
            ("1", "Traslado por venta"),
            ("2", "Traslado por consignación"),
            ("3", "Traslado por exportación"),
            ("4", "Traslado por importación"),
            ("5", "Traslado entre locales"),
            ("6", "Otros"),
        ],
        string="Motivo de Remisión (E501)",
    )

    l10n_py_nre_estimated_invoice_date = fields.Date(
        string="Fecha Estimada de Facturación (E506)",
        help="Fecha estimada de facturación para NRE sin factura asociada",
    )

    # Transporte (Grupo G SIFEN — NRE)
    l10n_py_transport_id = fields.Many2one(
        "l10n_py.transport",
        string="Datos de Transporte",
        help="Datos de transporte para Nota de Remisión (Grupo G SIFEN)",
    )

    # Campo prazo de transmissão
    l10n_py_transmission_deadline = fields.Datetime(
        string="Plazo de Transmisión",
        compute="_compute_transmission_deadline",
        store=True,
        help="Plazo máximo para transmitir el DTE (72 horas desde emisión)",
    )

    # ============== LIFECYCLE METHODS ==============

    def action_post(self):
        """Override para configurar estado EDI al confirmar factura."""
        res = super().action_post()
        for move in self:
            if move._l10n_py_edi_is_applicable() and move.l10n_py_edi_status in (
                "draft",
                False,
            ):
                move.l10n_py_edi_status = "to_send"
        return res

    def _l10n_py_edi_is_applicable(self):
        """¿Este asiento es un Documento Electrónico paraguayo?"""
        self.ensure_one()
        return (
            self.move_type in ("out_invoice", "out_refund")
            and self.company_id.country_id.code == "PY"
            and self.journal_id.l10n_latam_use_documents
        )

    def _l10n_py_edi_check_not_approved(self, action):
        for move in self:
            if move.l10n_py_edi_status in ("accepted", "accepted_obs", "to_cancel"):
                raise UserError(
                    _(
                        "El documento %(name)s fue aprobado por SIFEN (CDC "
                        "%(cdc)s): no se puede %(action)s. Use el evento de "
                        "cancelación.",
                        name=move.display_name,
                        cdc=move.l10n_py_cdc,
                        action=action,
                    )
                )

    def button_draft(self):
        self._l10n_py_edi_check_not_approved(_("volver a borrador"))
        return super().button_draft()

    def button_cancel(self):
        self._l10n_py_edi_check_not_approved(_("cancelar por el flujo estándar"))
        return super().button_cancel()

    @api.model
    def _l10n_py_get_param(self, key, default):
        """Parámetro de configuración con valor por defecto
        (ver data/ir_config_parameter_data.xml)."""
        value = self.env["ir.config_parameter"].sudo().get_param(key)
        return value if value not in (None, "", False) else default

    @api.depends("invoice_date")
    def _compute_transmission_deadline(self):
        """Plazo máximo de transmisión: ``l10n_py.transmission_hours`` (72 h
        según MT v150 §6.2) desde el inicio del día de emisión."""
        hours = int(self._l10n_py_get_param("l10n_py.transmission_hours", 72))
        for move in self:
            if move.invoice_date:
                move.l10n_py_transmission_deadline = fields.Datetime.from_string(
                    str(move.invoice_date) + " 00:00:00"
                ) + relativedelta(hours=hours)
            else:
                move.l10n_py_transmission_deadline = False

    @api.depends("l10n_py_edi_xml", "l10n_py_kude_pdf")
    def _compute_l10n_py_edi_attachments(self):
        Attachment = self.env["ir.attachment"].sudo()
        for move in self:
            move.l10n_py_edi_xml_attachment_id = False
            move.l10n_py_kude_attachment_id = False
            if not move.id:
                continue
            attachments = Attachment.search(
                [
                    ("res_model", "=", "account.move"),
                    ("res_id", "=", move.id),
                    ("res_field", "in", ("l10n_py_edi_xml", "l10n_py_kude_pdf")),
                ]
            )
            for att in attachments:
                if att.res_field == "l10n_py_edi_xml":
                    move.l10n_py_edi_xml_attachment_id = att
                else:
                    move.l10n_py_kude_attachment_id = att

    def _l10n_py_get_edi_attachments(self):
        """Adjuntos fiscales del DE (XML firmado y KuDE) con nombre y mimetype
        correctos, para el correo y las descargas."""
        self.ensure_one()
        self._l10n_py_sync_attachment_names()
        return self.l10n_py_edi_xml_attachment_id | self.l10n_py_kude_attachment_id

    def _l10n_py_sync_attachment_names(self):
        """Los Binary con res_field se crean sin nombre útil: se alinean con
        los campos *_filename y el mimetype."""
        for move in self:
            for att, name, mimetype in (
                (
                    move.l10n_py_edi_xml_attachment_id,
                    move.l10n_py_edi_xml_filename,
                    "application/xml",
                ),
                (
                    move.l10n_py_kude_attachment_id,
                    move.l10n_py_kude_filename,
                    "application/pdf",
                ),
            ):
                if att and name and (att.name != name or att.mimetype != mimetype):
                    att.sudo().write({"name": name, "mimetype": mimetype})

    def write(self, vals):
        # Un XML aprobado por SIFEN es un comprobante: no se reemplaza.
        if vals.get("l10n_py_edi_xml") and not self.env.context.get(
            "l10n_py_edi_replace_xml"
        ):
            for move in self:
                if (
                    move.l10n_py_edi_status in ("accepted", "accepted_obs", "cancelled")
                    and move.l10n_py_edi_xml
                    and move.l10n_py_edi_xml != vals["l10n_py_edi_xml"]
                    and vals.get("l10n_py_edi_status")
                    not in ("accepted", "accepted_obs")
                ):
                    raise UserError(
                        _(
                            "El XML de %s ya fue aprobado por SIFEN y no puede "
                            "reemplazarse."
                        )
                        % move.display_name
                    )
        return super().write(vals)

    @api.depends("l10n_latam_document_type_id")
    def _compute_l10n_py_doc_type_code(self):
        for move in self:
            move.l10n_py_doc_type_code = (
                move.l10n_latam_document_type_id.code
                if move.l10n_latam_document_type_id
                else ""
            )

    # ============== ONCHANGE METHODS ==============

    @api.onchange("invoice_line_ids")
    def _onchange_invoice_lines_transaction_type(self):
        """Auto-detectar tipo de transacción basado en los productos"""
        if self.invoice_line_ids:
            has_products = False
            has_services = False

            for line in self.invoice_line_ids.filtered(
                lambda line: line.display_type not in ("line_section", "line_note")
            ):
                if line.product_id:
                    if line.product_id.type in ["consu", "product"]:
                        has_products = True
                    elif line.product_id.type == "service":
                        has_services = True

            if has_products and has_services:
                self.l10n_py_transaction_type = "3"  # Mixto
            elif has_services:
                self.l10n_py_transaction_type = "2"  # Servicios
            else:
                self.l10n_py_transaction_type = "1"  # Mercadería

    # ============== CONSTRAINT METHODS ==============

    @api.constrains("l10n_py_security_code")
    def _check_security_code(self):
        for record in self:
            if record.l10n_py_security_code and len(record.l10n_py_security_code) != 9:
                raise ValidationError(
                    _("El código de seguridad debe tener exactamente 9 caracteres")
                )

    # ============== PRIVATE METHODS ==============

    def _generate_security_code(self):
        """Generar código de seguridad aleatorio de 9 dígitos"""
        return "".join(secrets.choice(string.digits) for _ in range(9))

    @staticmethod
    def _get_country_alpha3(country):
        """Convert res.country (ISO alpha-2) to ISO alpha-3 for SIFEN PaisType."""
        if not country or not country.code:
            return "PRY"
        # Common countries for Paraguay trade; full table at ISO 3166-1
        _ALPHA2_TO_3 = {
            "PY": "PRY",
            "AR": "ARG",
            "BR": "BRA",
            "UY": "URY",
            "BO": "BOL",
            "CL": "CHL",
            "PE": "PER",
            "US": "USA",
            "CO": "COL",
            "EC": "ECU",
            "VE": "VEN",
            "MX": "MEX",
            "ES": "ESP",
            "DE": "DEU",
            "CN": "CHN",
            "JP": "JPN",
            "KR": "KOR",
            "TW": "TWN",
            "IN": "IND",
            "GB": "GBR",
            "FR": "FRA",
            "IT": "ITA",
            "PT": "PRT",
            "CA": "CAN",
        }
        return _ALPHA2_TO_3.get(country.code, country.code)

    def _prepare_edi_document_data(self):
        """Preparar datos del documento electrónico en formato JSON"""
        self.ensure_one()

        if not self.l10n_py_security_code:
            self.l10n_py_security_code = self._generate_security_code()

        # Obtener código de tipo de documento desde l10n_latam
        doc_type_code = "1"
        if self.l10n_latam_document_type_id:
            doc_type_code = self.l10n_latam_document_type_id.code or "1"

        # Datos del timbrado (Grupo B)
        auth = self.journal_id.l10n_py_authorization_id
        timbrado_data = {}
        if auth:
            timbrado_data = {
                "timbrado": auth.name or "",
                "timbradoFechaInicio": (
                    auth.date_from.strftime("%Y-%m-%d") if auth.date_from else ""
                ),
                "timbradoFechaFin": (
                    auth.date_to.strftime("%Y-%m-%d") if auth.date_to else ""
                ),
            }

        # Construir estructura de datos según formato requerido
        document_data = {
            "tipoDocumento": int(doc_type_code),
            "establecimiento": (self.journal_id.l10n_py_establishment or "001"),
            "punto": self.journal_id.l10n_py_point or "001",
            "numero": self._get_edi_sequence_number(),
            **timbrado_data,
            "descripcion": self.name or "",
            "observacion": self.narration or "",
            "fecha": (
                self.invoice_date.strftime("%Y-%m-%dT%H:%M:%S")
                if self.invoice_date
                else fields.Datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
            ),
            "tipoEmision": int(self.l10n_py_emission_type),
            "tipoTransaccion": int(self.l10n_py_transaction_type),
            "tipoImpuesto": 1,  # IVA
            "moneda": self.currency_id.name,
            "condicionTipoCambio": int(self.l10n_py_exchange_rate_condition or "1"),
            "tipoCambio": self.l10n_py_exchange_rate or 0,
            "receiptId": (self.l10n_py_receipt_id or f"{self.company_id.id}-{self.id}"),
            "codigoSeguridadAleatorio": self.l10n_py_security_code,
            "cliente": self._prepare_customer_data(),
            "factura": {"presencia": int(self.l10n_py_presence_type)},
            "condicion": self._prepare_payment_condition(),
            "items": self._prepare_invoice_lines(),
        }

        # Agregar datos de usuario emisor si existe
        if self.user_id:
            document_data["usuario"] = {
                "documentoTipo": 1,  # Cédula
                "documentoNumero": self.user_id.partner_id.vat or "",
                "nombre": self.user_id.name,
                "cargo": self.user_id.function or "Vendedor",
            }

        # Documentos asociados (Grupo H)
        if self.l10n_py_associated_document_ids:
            document_data["documentosAsociados"] = self._prepare_associated_documents()

        # Campos NRE (tipo=7)
        doc_type_code = "1"
        if self.l10n_latam_document_type_id:
            doc_type_code = self.l10n_latam_document_type_id.code or "1"
        if doc_type_code == "7":
            document_data["remision"] = {
                "motivo": int(self.l10n_py_nre_motive or "1"),
            }
            if self.l10n_py_nre_estimated_invoice_date:
                document_data["remision"]["fechaEstimada"] = (
                    self.l10n_py_nre_estimated_invoice_date.strftime("%Y-%m-%d")
                )

        # Campos AFE (tipo=4) — Autofactura Electrónica
        if doc_type_code == "4":
            document_data["autofactura"] = self._prepare_autofactura_data()

        # Transporte (tipo=7 — NRE)
        if doc_type_code == "7" and self.l10n_py_transport_id:
            document_data["transporte"] = self._prepare_transport_data()

        # Totales SIFEN
        document_data["totales"] = {
            "totalExento": self.l10n_py_amount_exempt,  # F002
            "totalExonerado": self.l10n_py_amount_exonerated,  # F003
            "totalDescuento": self.l10n_py_amount_discount,  # dTotDesc
            "redondeo": self.l10n_py_amount_rounding,  # dRedon
            "totalGravado5": self.l10n_py_amount_subtotal_5,  # F004
            "totalGravado10": self.l10n_py_amount_subtotal_10,  # F005
            "totalOperacion": self.l10n_py_total_operation,  # F008
            "totalIva": self.l10n_py_amount_iva_total,  # F014
            "liquidacionIva5": self.l10n_py_amount_iva_5,  # F015
            "liquidacionIva10": self.l10n_py_amount_iva_10,  # F016
            "baseGravada5": self.l10n_py_base_5,  # F018
            "baseGravada10": self.l10n_py_base_10,  # F019
            "totalBaseGravada": self.l10n_py_base_total,  # F020
        }
        if self.l10n_py_amount_total_pyg is not None:
            document_data["totales"]["totalPYG"] = self.l10n_py_amount_total_pyg  # F023
        else:
            # Fallback: use totalOperacion when currency is PYG
            document_data["totales"]["totalPYG"] = document_data["totales"][
                "totalOperacion"
            ]

        return document_data

    def _prepare_associated_documents(self):
        """Preparar datos de documentos asociados para JSON EDI."""
        docs = []
        for ad in self.l10n_py_associated_document_ids:
            doc_data = {
                "tipoAsociacion": int(ad.association_type),
            }
            if ad.association_type == "1":
                doc_data["cdc"] = ad.cdc
            elif ad.association_type == "2":
                doc_data.update(
                    {
                        "timbrado": ad.timbrado,
                        "establecimiento": ad.establishment,
                        "punto": ad.expedition_point,
                        "numero": ad.doc_number,
                        "tipoDocumentoImpreso": int(ad.doc_type_code),
                        "fecha": (
                            ad.doc_date.strftime("%Y-%m-%d") if ad.doc_date else ""
                        ),
                    }
                )
            elif ad.association_type == "3":
                doc_data.update(
                    {
                        "constanciaTipo": int(ad.constancia_type),
                        "constanciaNumero": ad.constancia_number,
                        "constanciaControl": self.l10n_py_afe_constancia_control or "",
                    }
                )
            docs.append(doc_data)
        return docs

    def _prepare_customer_data(self, partner=None):
        """Preparar datos del cliente (Grupo D receptor).

        ``partner`` permite armar los datos de otro receptor (nominación)."""
        partner = partner or self.partner_id

        # iNatRec: 1=Contribuyente, 2=No Contribuyente
        nat_rec = partner.l10n_py_taxpayer_type or "1"

        # iTiOpe: 1=B2B, 2=B2C, 3=B2G, 4=B2F (extranjero)
        if partner.country_id and partner.country_id.code != "PY":
            ti_ope = "4"  # Extranjero
        elif nat_rec == "2":
            ti_ope = "2"  # B2C
        else:
            ti_ope = "1"  # B2B

        customer_data = {
            "naturalezaReceptor": nat_rec,
            "tipoOperacion": ti_ope,
            "contribuyente": nat_rec == "1",
            "ruc": partner.l10n_py_ruc or "",
            "dvReceptor": partner.l10n_py_ruc_dv or "",
            "tipoContribuyente": "2" if partner.is_company else "1",
            "razonSocial": partner.name,
            "nombreFantasia": partner.l10n_py_fantasy_name or partner.name,
            "direccion": partner.street or "N/A",
            "numeroCasa": (
                partner.street_number if hasattr(partner, "street_number") else "0"
            )
            or "0",
            "pais": self._get_country_alpha3(partner.country_id) or "PRY",
            "paisDescripcion": partner.country_id.name or "Paraguay",
        }

        # Agregar datos de ubicación si están disponibles
        if partner.l10n_py_department_code:
            customer_data.update(
                {
                    "departamento": partner.l10n_py_department_code,
                    "departamentoDescripcion": (
                        partner.state_id.name if partner.state_id else ""
                    ),
                    "ciudad": partner.l10n_py_city_code or "",
                    "ciudadDescripcion": partner.city or "",
                }
            )

        # Agregar contacto
        if partner.phone or partner.mobile:
            customer_data["telefono"] = partner.phone or ""
            customer_data["celular"] = partner.mobile or ""

        if partner.email:
            customer_data["email"] = partner.email

        # No-contribuyente: incluir documento de identidad (D024/D025)
        if nat_rec == "2":
            if partner.l10n_py_doc_type:
                customer_data["documentoTipo"] = int(partner.l10n_py_doc_type)
            if partner.l10n_py_doc_number:
                customer_data["documentoNumero"] = partner.l10n_py_doc_number

        return customer_data

    def _prepare_payment_condition(self):
        """Preparar condición de pago"""
        payment_condition = {
            "tipo": (
                2 if self.invoice_payment_term_id else 1
            ),  # 1: Contado, 2: Crédito
        }

        if self.invoice_payment_term_id:
            # Es crédito
            payment_condition["credito"] = {
                "tipo": 1,  # 1: Plazo, 2: Cuotas
                "plazo": (
                    f"{self.invoice_payment_term_id.line_ids[0].nb_days} días"
                    if self.invoice_payment_term_id.line_ids
                    else "0 días"
                ),
                "cuotas": len(self.invoice_payment_term_id.line_ids),
            }

            # Preparar información de cuotas
            cuotas = []
            if self.invoice_date and self.invoice_payment_term_id.line_ids:
                for line in self.invoice_payment_term_id.line_ids:
                    due_date = self.invoice_date + relativedelta(days=line.nb_days)
                    cuotas.append(
                        {
                            "moneda": self.currency_id.name,
                            "monto": (
                                self.amount_total
                                / len(self.invoice_payment_term_id.line_ids)
                            ),
                            "vencimiento": due_date.strftime("%Y-%m-%d"),
                        }
                    )

            payment_condition["credito"]["infoCuotas"] = cuotas
        else:
            # Es contado
            payment_condition["entregas"] = [
                {
                    "tipo": int(self.l10n_py_payment_type or "1"),
                    "monto": str(self.amount_total),
                    "moneda": self.currency_id.name,
                    "cambio": 0,
                }
            ]

        return payment_condition

    def _prepare_invoice_lines(self):
        """Preparar líneas de la factura"""
        items = []

        for line in self.invoice_line_ids.filtered(
            lambda line: line.display_type not in ("line_section", "line_note")
        ):
            # Afectación y tasa desde account.tax (E731/E734), importes E7/E8
            amounts = self._l10n_py_line_amounts(line)
            iva_rate = amounts["rate"]
            iva_type = int(amounts["affectation"])
            base_gravada = amounts["base"]
            liquidacion_iva = amounts["iva"]
            unit_discount = line.price_unit * (line.discount or 0.0) / 100.0

            item = {
                "codigo": (
                    line.product_id.default_code or f"PROD-{line.product_id.id}"
                ),
                # Odoo antepone "[CÓDIGO] " al nombre de línea y permite saltos
                # de línea; el SET valida un patrón en dDesProSer, así que se
                # quita el prefijo y se colapsan los espacios/saltos.
                "descripcion": re.sub(
                    r"\s+",
                    " ",
                    re.sub(
                        r"^\[[^\]]*\]\s*",
                        "",
                        (line.name or line.product_id.name or ""),
                    ),
                ).strip(),
                "observacion": "",
                "ncm": (
                    line.product_id.l10n_py_ncm_code
                    if hasattr(line.product_id, "l10n_py_ncm_code")
                    else ""
                )
                or "",
                "unidadMedida": int(
                    getattr(line.product_id, "l10n_py_unit_code", 0) or 77
                ),  # 77 = UNI
                "cantidad": line.quantity,
                "precioUnitario": line.price_unit,
                "descuento": self._l10n_py_round(unit_discount),  # dDescItem
                "porcentajeDescuento": line.discount or 0.0,  # dPorcDesIt
                "cambio": 0,
                "ivaTipo": iva_type,
                "ivaBase": amounts["proportion"],  # dPropIVA
                "iva": iva_rate,
                "baseGravada": self._l10n_py_round(base_gravada),  # dBasGravIVA
                "liquidacionIva": self._l10n_py_round(liquidacion_iva),  # dLiqIVAItem
                "baseExenta": self._l10n_py_round(amounts["exempt_base"]),  # dBasExe
                "lote": "",
                "vencimiento": "",
            }

            items.append(item)

        return items

    def _prepare_transport_data(self):
        """Preparar datos de transporte (Grupo G SIFEN)."""
        t = self.l10n_py_transport_id
        data = {
            "modalidad": int(t.transport_mode),
        }
        if t.transport_type:
            data["tipo"] = int(t.transport_type)
        if t.freight_responsibility:
            data["responsableFlete"] = int(t.freight_responsibility)
        if t.incoterm:
            data["condicionNegociacion"] = t.incoterm
        if t.manifest_number:
            data["numeroManifiesto"] = t.manifest_number
        if t.transport_start_date:
            data["fechaInicio"] = t.transport_start_date.strftime("%Y-%m-%d")
        if t.transport_end_date:
            data["fechaFin"] = t.transport_end_date.strftime("%Y-%m-%d")

        # Departure point
        if t.departure_address:
            data["salida"] = {
                "direccion": t.departure_address,
                "numeroCasa": t.departure_house or 0,
                "departamento": t.departure_department or 0,
                "distrito": t.departure_district or 0,
                "ciudad": t.departure_city or 0,
            }

        # Transporter
        if t.transporter_name:
            data["transportista"] = {
                "naturaleza": t.transporter_nature or "1",
                "nombre": t.transporter_name,
                "ruc": t.transporter_ruc or "",
                "dv": t.transporter_dv or "",
                "choferDocumento": t.driver_doc_number or "",
                "choferNombre": t.driver_name or "",
            }

        # Vehicles
        if t.vehicle_ids:
            data["vehiculos"] = [
                {
                    "tipo": v.vehicle_type,
                    "marca": v.brand,
                    "numero": v.plate_number,
                }
                for v in t.vehicle_ids
            ]

        # Deliveries
        if t.delivery_ids:
            data["entregas"] = [
                {
                    "direccion": d.address,
                    "numeroCasa": d.house_number or 0,
                    "departamento": d.department,
                    "distrito": d.district or 0,
                    "ciudad": d.city,
                }
                for d in t.delivery_ids
            ]

        return data

    def _prepare_autofactura_data(self):
        """Preparar datos de Autofactura Electrónica (Grupo E — gCamAE)."""
        return {
            "tipoConstancia": int(self.l10n_py_afe_constancia_type or "1"),
            "numeroConstancia": self.l10n_py_afe_constancia_number or "",
            "numeroControl": self.l10n_py_afe_constancia_control or "",
            "tipoDocumentoVendedor": int(self.l10n_py_afe_vendor_doc_type or "1"),
            "numeroDocumentoVendedor": self.l10n_py_afe_vendor_doc_number or "",
            "nombreVendedor": self.l10n_py_afe_vendor_name or "",
            "direccionVendedor": self.l10n_py_afe_vendor_address or "",
            "numeroCasaVendedor": self.l10n_py_afe_vendor_house or 0,
            "departamentoVendedor": self.l10n_py_afe_vendor_department or 0,
            "distritoVendedor": self.l10n_py_afe_vendor_district or 0,
            "ciudadVendedor": self.l10n_py_afe_vendor_city or 0,
            "direccionProvision": self.l10n_py_afe_provision_address or "",
            "departamentoProvision": self.l10n_py_afe_provision_department or 0,
            "distritoProvision": self.l10n_py_afe_provision_district or 0,
            "ciudadProvision": self.l10n_py_afe_provision_city or 0,
        }

    def _get_edi_sequence_number(self):
        """Obtener número de secuencia para EDI"""
        if self.l10n_py_invoice_number:
            return str(self.l10n_py_invoice_number).zfill(7)
        if self.name:
            number = "".join(filter(str.isdigit, self.name.split("/")[-1]))
            return number.zfill(7)[-7:]
        return "0000001"

    def _validate_afe_data(self, docs):
        """Validar datos específicos de Autofactura Electrónica (código 4)."""
        errors = []
        if len(docs) != 1:
            errors.append(
                _("Autofactura: debe tener exactamente 1 documento asociado.")
            )
        elif docs[0].association_type != "3":
            errors.append(
                _(
                    "Autofactura: el documento asociado debe "
                    "ser una constancia electrónica."
                )
            )
        required_fields = [
            ("l10n_py_afe_constancia_type", "el tipo de constancia"),
            ("l10n_py_afe_constancia_number", "el número de constancia"),
            ("l10n_py_afe_constancia_control", "el número de control"),
            ("l10n_py_afe_vendor_doc_number", "el número de documento del vendedor"),
            ("l10n_py_afe_vendor_name", "el nombre del vendedor"),
            ("l10n_py_afe_vendor_address", "la dirección del vendedor"),
        ]
        for field_name, desc in required_fields:
            if not getattr(self, field_name):
                errors.append(_("Autofactura: %s es obligatorio.") % desc)
        return errors

    def _validate_edi_document_type(self):
        """Validar requisitos específicos por tipo de DTE.

        Llamado antes del envío EDI. Retorna lista de errores.
        """
        errors = []
        code = (
            self.l10n_latam_document_type_id.code
            if self.l10n_latam_document_type_id
            else ""
        )
        docs = self.l10n_py_associated_document_ids

        # AFE (code=4): exatamente 1 constância + datos vendedor
        if code == "4":
            errors.extend(self._validate_afe_data(docs))

        # NCE (code=5): exatamente 1 doc associado
        elif code == "5":
            if len(docs) != 1:
                errors.append(
                    _(
                        "Nota de Crédito Electrónica: debe tener "
                        "exactamente 1 documento asociado."
                    )
                )

        # NDE (code=6): exatamente 1 doc associado
        elif code == "6":
            if len(docs) != 1:
                errors.append(
                    _(
                        "Nota de Débito Electrónica: debe tener "
                        "exactamente 1 documento asociado."
                    )
                )

        # NRE (code=7): validações NRE
        elif code == "7":
            if not self.l10n_py_nre_motive:
                errors.append(_("Nota de Remisión: el motivo es obligatorio."))
            # Motivo "1" (traslado por venta) sin doc asociado → requer data estimada
            if self.l10n_py_nre_motive == "1" and not docs:
                if not self.l10n_py_nre_estimated_invoice_date:
                    errors.append(
                        _(
                            "NRE traslado por venta sin documento "
                            "asociado: debe indicar fecha estimada "
                            "de facturación."
                        )
                    )
            # Data estimada no puede exceder el mes de emisión
            if self.l10n_py_nre_estimated_invoice_date and self.invoice_date:
                est_date = self.l10n_py_nre_estimated_invoice_date
                inv_date = self.invoice_date
                # La fecha estimada no debe superar el mes siguiente
                if est_date.month > inv_date.month + 1 or (
                    est_date.year > inv_date.year
                    and not (inv_date.month == 12 and est_date.month == 1)
                ):
                    errors.append(
                        _(
                            "La fecha estimada de facturación no puede "
                            "exceder el mes siguiente al de emisión."
                        )
                    )
            # Motivo "5" (entre locales) → RUC receptor = RUC emissor
            if self.l10n_py_nre_motive == "5":
                partner_ruc = self.partner_id.l10n_py_ruc or ""
                company_ruc = self.company_id.l10n_py_ruc or ""
                if partner_ruc != company_ruc:
                    errors.append(
                        _(
                            "Traslado entre locales: el RUC del "
                            "receptor debe coincidir con el del emisor."
                        )
                    )

        return errors

    def _l10n_py_check_edi_constraints(self):
        """Lista de errores que impiden emitir el DE (vacía si está todo bien).

        Acumula todos los problemas en lugar de cortar en el primero, para que
        el usuario los corrija de una vez.
        """
        self.ensure_one()
        errors = []

        # Validar datos de la empresa
        company = self.company_id
        if not company.l10n_py_ruc:
            errors.append(_("Configure el RUC de la empresa"))
        if (
            not self.env["l10n_py.edi.connector"]
            .sudo()
            .search_count([("company_id", "=", company.id)])
        ):
            errors.append(
                _("No hay un conector EDI configurado para la empresa %s")
                % company.name
            )

        # Validar datos del cliente (F15)
        partner = self.partner_id
        if partner.l10n_py_taxpayer_type == "1" and not partner.l10n_py_ruc:
            errors.append(_("El cliente contribuyente debe tener RUC"))
        if partner.l10n_py_taxpayer_type == "2" and not partner.l10n_py_doc_number:
            errors.append(
                _(
                    "El cliente no contribuyente debe tener número "
                    "de documento de identidad"
                )
            )

        if not partner.street:
            errors.append(_("La dirección del cliente es obligatoria"))

        # Validar datos del diario
        journal = self.journal_id
        if not journal.l10n_py_authorization_id:
            errors.append(_("Configure el timbrado en el diario"))

        if (
            journal.l10n_py_authorization_validity
            and journal.l10n_py_authorization_validity < fields.Date.today()
        ):
            errors.append(_("El timbrado está vencido"))

        # Validar productos
        for line in self.invoice_line_ids.filtered(
            lambda line: line.display_type not in ("line_section", "line_note")
        ):
            if hasattr(line.product_id, "l10n_py_ncm_code"):
                if not line.product_id.l10n_py_ncm_code:
                    errors.append(
                        _("El producto %s no tiene código NCM") % line.product_id.name
                    )

        # Validar requisitos por tipo de documento (F03-F07)
        errors.extend(self._validate_edi_document_type())

        # Validar nominación obligatoria (> Gs. 7.000.000)
        _NOMINACION_THRESHOLD = 7000000
        if self.currency_id.name == "PYG" and self.amount_total > _NOMINACION_THRESHOLD:
            if partner.l10n_py_taxpayer_type == "2" and not partner.l10n_py_doc_number:
                errors.append(
                    _(
                        "Facturas superiores a Gs. 7.000.000 no pueden "
                        "ser innominadas. Debe identificar al receptor."
                    )
                )

        return errors

    def _validate_edi_data(self):
        """Validar datos antes de enviar a EDI: un único UserError con todos
        los errores."""
        errors = self._l10n_py_check_edi_constraints()
        if errors:
            raise UserError("\n".join(errors))
        return True

    # ============== PUBLIC METHODS ==============

    def _get_edi_connector(self):
        """Buscar conector EDI de la empresa."""
        connector = (
            self.env["l10n_py.edi.connector"]
            .sudo()
            .search([("company_id", "=", self.company_id.id)], limit=1)
        )
        if not connector:
            raise UserError(_("No hay un conector EDI configurado para esta empresa"))
        return connector

    def _target_new_tab(self, attachment_id):
        """Open an ir.attachment inline in a new browser tab."""
        if attachment_id:
            return {
                "type": "ir.actions.act_url",
                "url": f"/web/content/{attachment_id.id}/{attachment_id.name}",
                "target": "new",
            }

    def action_preview_xml(self):
        """Generar y mostrar XML sin firmar ni enviar (preview)."""
        self.ensure_one()
        self._validate_edi_data()
        document_data = self._prepare_edi_document_data()
        connector = self._get_edi_connector()
        xml_string = connector.preview_document(document_data)
        if not xml_string:
            raise UserError(
                _("El proveedor '%s' no genera el XML localmente.")
                % connector.provider_type
            )

        import base64 as b64

        xml_b64 = b64.b64encode(xml_string.encode("utf-8"))
        self.l10n_py_edi_xml = xml_b64
        self.l10n_py_edi_xml_filename = "preview.xml"

        attachment = self.env["ir.attachment"].create(
            {
                "name": f"preview_{self.name or self.id}.xml",
                "datas": xml_b64,
                "mimetype": "text/xml",
                "res_model": self._name,
                "res_id": self.id,
            }
        )
        return self._target_new_tab(attachment)

    def _l10n_py_kude_engine(self):
        """``qweb`` (reporte de este módulo, por defecto) o ``pykude``
        (librería externa que dibuja el KuDE desde el XML firmado)."""
        return self._l10n_py_get_param("l10n_py.kude_engine", "qweb")

    def _l10n_py_render_kude_pykude(self):
        """Bytes del PDF generado por ``pykude`` desde el XML firmado."""
        import base64

        self.ensure_one()
        try:
            from pykude import auto_kude
            from pykude.kude_fe.config import KudeFeConfig
        except ImportError as e:
            raise UserError(
                _(
                    "El motor de KuDE 'pykude' no está instalado. Instale la "
                    "librería o use el motor 'qweb' (parámetro l10n_py.kude_engine)."
                )
            ) from e
        if not self.l10n_py_edi_xml:
            raise UserError(_("No hay XML disponible para generar el KuDE"))
        xml_content = base64.b64decode(self.l10n_py_edi_xml).decode("utf-8")
        config = KudeFeConfig()
        if self.company_id.logo:
            config.logo = base64.b64decode(self.company_id.logo)
        return auto_kude(xml=xml_content, config=config).output()

    def _l10n_py_render_kude_qweb(self):
        """Bytes del PDF del reporte QWeb ``action_kude_report`` (en modo test
        Odoo devuelve el HTML)."""
        self.ensure_one()
        content, _type = self.env["ir.actions.report"]._render_qweb_pdf(
            "l10n_py_edi_base.action_kude_report", res_ids=self.ids
        )
        return content

    def _l10n_py_render_kude(self):
        if self._l10n_py_kude_engine() == "pykude":
            return self._l10n_py_render_kude_pykude()
        return self._l10n_py_render_kude_qweb()

    def action_preview_kude(self):
        """KuDE de previsualización: el reporte QWeb directo, o el PDF de
        pykude a partir del XML preview."""
        import base64

        self.ensure_one()
        if self._l10n_py_kude_engine() != "pykude":
            return (
                self.env.ref("l10n_py_edi_base.action_kude_report")
                .with_context(discard_logo_check=True)
                .report_action(self, config=False)
            )
        if not self.l10n_py_edi_xml:
            # Generate XML first
            self.action_preview_xml()
        pdf_bytes = self._l10n_py_render_kude_pykude()

        attachment = self.env["ir.attachment"].create(
            {
                "name": f"KUDE_preview_{self.name or self.id}.pdf",
                "datas": base64.b64encode(pdf_bytes),
                "mimetype": "application/pdf",
                "res_model": self._name,
                "res_id": self.id,
            }
        )
        return self._target_new_tab(attachment)

    # ============== ENVÍO Y PROCESAMIENTO DE RESULTADOS ==============

    def action_send_edi(self):
        """Botón: enviar a SIFEN los documentos seleccionados."""
        moves = self.filtered(
            lambda m: m.l10n_py_edi_status in ("draft", "to_send", "error", "rejected")
        )
        if not moves:
            raise UserError(_("No hay documentos pendientes de envío."))
        moves._l10n_py_edi_send(raise_on_error=len(moves) == 1)

    def _l10n_py_edi_send(self, raise_on_error=False):
        """Envía uno o más DE a través del conector de cada compañía.

        - Valida cada documento (todos los errores juntos).
        - Usa ``send_documents`` (lote) cuando el proveedor lo soporta.
        - Nunca deja un documento en ``sent`` sin resultado: cualquier
          excepción de transporte se traduce a ``error`` (reintentable).

        :return: dict ``{move: result}`` con los resultados normalizados.
        """
        results = {}
        for company_moves in self.grouped("company_id").values():
            connector = company_moves[:1]._get_edi_connector()
            valid_moves = self.env["account.move"]
            payloads = []
            for move in company_moves:
                errors = move._l10n_py_check_edi_constraints()
                if errors:
                    move._l10n_py_edi_apply_result(
                        connector._make_result(
                            "error",
                            errors=[("", e, "provider") for e in errors],
                            retryable=True,
                        )
                    )
                    results[move] = None
                    if raise_on_error:
                        raise UserError("\n".join(errors))
                    continue
                payloads.append(move._prepare_edi_document_data())
                valid_moves |= move
            if not valid_moves:
                continue
            valid_moves.write(
                {"l10n_py_edi_status": "sent", "l10n_py_edi_errors": False}
            )
            try:
                if len(valid_moves) > 1 and connector.supports("batch"):
                    raw_results = connector.send_documents(payloads)
                else:
                    raw_results = [connector.send_document(d) for d in payloads]
            except UserError:
                raise
            except Exception as e:
                _logger.exception("Error enviando DE a %s", connector.provider_type)
                err = connector._error_result(str(e), code="", source="provider")
                for move in valid_moves:
                    move._l10n_py_edi_apply_result(err)
                    move._l10n_py_maybe_auto_contingency(connector)
                    results[move] = err
                if raise_on_error:
                    raise UserError(_("Error enviando documento: %s") % e) from e
                continue
            for move, raw in zip(valid_moves, raw_results, strict=True):
                result = self._l10n_py_normalize_result(raw)
                move._l10n_py_edi_apply_result(result)
                move._l10n_py_maybe_auto_contingency(connector)
                results[move] = result
                if raise_on_error and result["status"] in ("rejected", "error"):
                    # el estado y los errores deben sobrevivir al rollback del
                    # UserError que ve el usuario
                    self._l10n_py_commit_if_possible()
                    raise UserError(
                        _("SIFEN/%(provider)s rechazó el documento:\n%(errors)s")
                        % {
                            "provider": connector.provider_type,
                            "errors": move.l10n_py_edi_errors or result.get("error"),
                        }
                    )
        return results

    def _l10n_py_external_number_vals(self, number):
        """Proveedores que asignan la numeración (Sifende): alinea el número
        del documento con el que quedó en el CDC. Devuelve vals para write."""
        self.ensure_one()
        digits = "".join(filter(str.isdigit, str(number)))[-7:]
        if not digits:
            return {}
        new_number = int(digits)
        if new_number == (self.l10n_py_invoice_number or 0):
            return {}
        vals = {"l10n_py_invoice_number": new_number}
        old = str(self.l10n_py_invoice_number or "").zfill(7)
        if self.name and self.l10n_py_invoice_number and old in self.name:
            vals["name"] = self.name.replace(old, digits.zfill(7))
        self.message_post(
            body=_(
                "Numeración asignada por el proveedor: %(new)s (Odoo tenía %(old)s)."
            )
            % {"new": digits.zfill(7), "old": old}
        )
        return vals

    @api.model
    def _l10n_py_commit_if_possible(self):
        """Commit fuera de los tests (mismo criterio que
        ``account.move.send._can_commit``)."""
        from odoo import modules, tools

        if not tools.config["test_enable"] and not modules.module.current_test:
            # el rechazo debe persistir aunque el usuario vea un UserError
            self.env.cr.commit()  # pylint: disable=invalid-commit

    @api.model
    def _l10n_py_normalize_result(self, raw):
        """Completa un resultado de conector al contrato normalizado.

        Acepta el formato legado ``{"success", "result", "error"}`` y deriva
        ``status``: éxito con documentos → ``accepted``; éxito solo con
        ``loteId`` → ``processing``; fracaso → ``rejected`` (o ``error`` si
        el conector lo marca reintentable).
        """
        if not isinstance(raw, dict):
            return self.env["l10n_py.edi.connector"]._make_result(
                "error", errors=[("", _("Respuesta inválida del conector"), "provider")]
            )
        if raw.get("status") in (
            "accepted",
            "accepted_obs",
            "processing",
            "rejected",
            "error",
        ):
            raw.setdefault("errors", [])
            raw.setdefault("result", {})
            raw["result"].setdefault("deList", [])
            raw["result"].setdefault("loteId", None)
            raw.setdefault("retryable", raw["status"] == "error")
            raw.setdefault("raw", None)
            raw.setdefault("error", None)
            raw.setdefault(
                "success", raw["status"] in ("accepted", "accepted_obs", "processing")
            )
            return raw
        result = raw.get("result") or {}
        de_list = result.get("deList") or []
        if raw.get("success") and de_list:
            status = "accepted"
        elif raw.get("success") and result.get("loteId"):
            status = "processing"
        elif raw.get("retryable"):
            status = "error"
        else:
            status = "rejected"
        errors = []
        if raw.get("error"):
            errors.append(("", raw["error"], "provider"))
        return self.env["l10n_py.edi.connector"]._make_result(
            status,
            documents=de_list,
            batch_id=result.get("loteId"),
            errors=errors,
            raw=raw.get("raw", raw),
            retryable=bool(raw.get("retryable")),
        )

    @api.model
    def _l10n_py_format_errors(self, errors):
        lines = []
        for err in errors or []:
            code = err.get("code") or ""
            src = "SIFEN" if err.get("source") == "sifen" else _("Proveedor")
            text = err.get("message") or ""
            lines.append(f"[{src}] {code + ': ' if code else ''}{text}")
        return "\n".join(lines)

    def _l10n_py_edi_apply_result(self, result):
        """Aplica un resultado normalizado al documento (estado, CDC, XML, QR...).

        Es el único punto que muta el estado EDI a partir de una respuesta,
        tanto en el envío síncrono como en el polling del cron.
        """
        self.ensure_one()
        status = result["status"]
        docs = result["result"].get("deList") or []
        de_data = docs[0] if docs else {}
        vals = {
            "l10n_py_edi_errors": self._l10n_py_format_errors(result.get("errors")),
            "l10n_py_edi_retryable": bool(result.get("retryable")),
        }
        if result["result"].get("loteId"):
            vals["l10n_py_edi_batch_id"] = result["result"]["loteId"]
        if de_data.get("cdc"):
            vals["l10n_py_cdc"] = de_data["cdc"]
        if de_data.get("code"):
            vals["l10n_py_edi_response_code"] = str(de_data["code"])
        if de_data.get("number"):
            vals.update(self._l10n_py_external_number_vals(de_data["number"]))

        if status in ("accepted", "accepted_obs"):
            vals.update(
                {
                    "l10n_py_edi_status": status,
                    "l10n_py_edi_protocol": de_data.get("protocol")
                    or self.l10n_py_edi_protocol,
                    "l10n_py_edi_digest": de_data.get("digest")
                    or self.l10n_py_edi_digest,
                    "l10n_py_edi_approval_date": self._l10n_py_parse_datetime(
                        de_data.get("approval_date")
                    )
                    or fields.Datetime.now(),
                    "l10n_py_edi_message": de_data.get("message")
                    or (
                        _("Documento aceptado con observaciones")
                        if status == "accepted_obs"
                        else _("Documento aceptado exitosamente")
                    ),
                }
            )
            if de_data.get("qr"):
                vals["l10n_py_qr_string"] = de_data["qr"]
            if de_data.get("xml"):
                vals.update(
                    self._l10n_py_prepare_xml_vals(
                        de_data["xml"], cdc=vals.get("l10n_py_cdc")
                    )
                )
            self.write(vals)
            self._l10n_py_generate_qr_image()
            self._l10n_py_store_kude(de_data.get("pdf"))
            self.invalidate_recordset(
                ["l10n_py_edi_xml_attachment_id", "l10n_py_kude_attachment_id"]
            )
            self._l10n_py_sync_attachment_names()
        elif status == "processing":
            vals.update(
                {
                    "l10n_py_edi_status": "processing",
                    "l10n_py_edi_message": de_data.get("message")
                    or _("Enviado; esperando respuesta de SIFEN"),
                }
            )
            # Conectores directos: el XML firmado y el QR ya son definitivos
            # aunque SIFEN todavía no haya respondido.
            if de_data.get("qr"):
                vals["l10n_py_qr_string"] = de_data["qr"]
            if de_data.get("xml") and not self.l10n_py_edi_xml:
                vals.update(
                    self._l10n_py_prepare_xml_vals(
                        de_data["xml"], cdc=vals.get("l10n_py_cdc")
                    )
                )
            self.write(vals)
            if de_data.get("qr"):
                self._l10n_py_generate_qr_image()
                self.invalidate_recordset(["l10n_py_edi_xml_attachment_id"])
                self._l10n_py_sync_attachment_names()
        elif status == "rejected":
            vals.update(
                {
                    "l10n_py_edi_status": "rejected",
                    "l10n_py_edi_message": de_data.get("message")
                    or result.get("error")
                    or _("Documento rechazado"),
                }
            )
            self.write(vals)
        else:  # error
            vals.update(
                {
                    "l10n_py_edi_status": "error",
                    "l10n_py_edi_message": result.get("error")
                    or _("Error de transporte"),
                }
            )
            self.write(vals)

    @api.model
    def _l10n_py_parse_datetime(self, value):
        """Convierte la fecha del proveedor (ISO 8601, con o sin zona) a Datetime."""
        if not value:
            return False
        if isinstance(value, datetime):
            dt = value
        else:
            try:
                dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            except ValueError:
                return False
        if dt.tzinfo is not None:
            dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
        return dt

    def _l10n_py_prepare_xml_vals(self, xml, cdc=None):
        """Valores para persistir el XML firmado devuelto por el proveedor."""
        import base64 as b64

        if isinstance(xml, str):
            xml = xml.encode("utf-8")
        return {
            "l10n_py_edi_xml": b64.b64encode(xml),
            "l10n_py_edi_xml_filename": f"{cdc or self.l10n_py_cdc or self.name}.xml",
        }

    def _l10n_py_store_kude(self, pdf_bytes):
        """Guarda el KuDE que devuelve el proveedor; si no lo hay, intenta
        generarlo localmente (nunca bloquea la aceptación)."""
        import base64 as b64

        self.ensure_one()
        if pdf_bytes:
            self.write(
                {
                    "l10n_py_kude_pdf": b64.b64encode(pdf_bytes),
                    "l10n_py_kude_filename": f"KUDE_{self.l10n_py_cdc}.pdf",
                }
            )
            return
        try:
            self._generate_kude()
        except Exception as e:
            _logger.warning("Error generando KuDE de %s: %s", self.display_name, e)

    def _process_edi_response(self, response):
        """Compatibilidad: procesar una respuesta cruda del conector."""
        self.ensure_one()
        self._l10n_py_edi_apply_result(self._l10n_py_normalize_result(response))

    def action_check_edi_status(self):
        """Botón/cron: consultar el estado de documentos enviados o en proceso."""
        for move in self.filtered(
            lambda m: m.l10n_py_edi_status in ("sent", "processing", "to_cancel")
        ):
            connector = move._get_edi_connector()
            ref = move.l10n_py_edi_batch_id or move.l10n_py_cdc
            if not ref:
                continue
            try:
                raw = connector.check_status(ref)
            except Exception as e:
                _logger.warning(
                    "Error consultando estado de %s: %s", move.display_name, e
                )
                continue
            result = move._l10n_py_select_document_result(
                self._l10n_py_normalize_result(raw)
            )
            if move.l10n_py_edi_status == "to_cancel":
                move._l10n_py_edi_apply_cancel_result(result)
            elif result["status"] != "processing" or result["result"].get("deList"):
                move._l10n_py_edi_apply_result(result)

    def _l10n_py_select_document_result(self, result):
        """Reduce el resultado de un lote al documento de este asiento.

        Los conectores con lote devuelven en ``deList`` un elemento por DE,
        cada uno con su propio ``status``; se conserva solo el que coincide
        con el CDC del asiento y su estado pasa a ser el del resultado. Si no
        hay coincidencia (lote aún en proceso) se devuelve tal cual.
        """
        self.ensure_one()
        docs = result.get("result", {}).get("deList") or []
        if len(docs) <= 1 or not self.l10n_py_cdc:
            return result
        match = [d for d in docs if d.get("cdc") == self.l10n_py_cdc]
        if not match:
            return result
        doc = match[0]
        status = doc.get("status") or result["status"]
        errors = [
            e
            for e in result.get("errors") or []
            if not e.get("message", "").startswith("[")
            or e["message"].startswith(f"[{self.l10n_py_cdc}]")
        ]
        selected = dict(result, status=status, errors=errors)
        selected["result"] = dict(result["result"], deList=[doc])
        selected["success"] = status in ("accepted", "accepted_obs", "processing")
        selected["error"] = (
            "; ".join(
                f"{e['code']}: {e['message']}" if e.get("code") else e["message"]
                for e in errors
            )
            or None
        )
        return selected

    def _l10n_py_generate_qr_image(self):
        """Genera la imagen PNG del QR (l10n_py_qr_code) desde el enlace."""
        from ..services.qr_generator import QRGenerator

        for move in self:
            if move.l10n_py_qr_string:
                move.l10n_py_qr_code = QRGenerator.generate_image(
                    move.l10n_py_qr_string
                )

    def action_l10n_py_preview_qr(self):
        """Genera CDC + QR (firma local) SIN transmitir, para previsualizar.

        Útil para verificar el QR/KuDE en pruebas. El CDC generado es de
        previsualización; la emisión real lo regenera al transmitir.
        """
        self.ensure_one()
        self._validate_edi_data()
        document_data = self._prepare_edi_document_data()
        connector = self._get_edi_connector()
        result = connector.preview_qr(document_data)
        if not result or not result.get("qr"):
            raise UserError(
                _(
                    "No se pudo generar el QR. Verifique el certificado y el "
                    "CSC/IdCSC configurados en el conector EDI."
                )
            )
        self.write(
            {
                "l10n_py_cdc": result.get("cdc"),
                "l10n_py_qr_string": result["qr"],
            }
        )
        self._l10n_py_generate_qr_image()
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "type": "success",
                "title": _("QR generado"),
                "message": _("CDC y código QR de previsualización generados."),
                "sticky": False,
            },
        }

    # Plazos de cancelación por tipo de DE (MT v150 §6.2.1), en horas desde
    # la aprobación de SIFEN.
    CANCEL_LIMIT_HOURS = {"1": 48, "4": 48, "5": 168, "6": 168, "7": 168}

    def _l10n_py_cancel_deadline(self):
        """Fecha/hora límite para el evento de cancelación, o False."""
        self.ensure_one()
        if not self.l10n_py_edi_approval_date:
            return False
        code = self.l10n_latam_document_type_id.code or "1"
        hours = self.CANCEL_LIMIT_HOURS.get(code, 48)
        return self.l10n_py_edi_approval_date + relativedelta(hours=hours)

    def _validate_cancel_deadline(self):
        """Levanta UserError si el plazo de cancelación expiró."""
        self.ensure_one()
        deadline = self._l10n_py_cancel_deadline()
        if deadline and fields.Datetime.now() > deadline:
            raise UserError(
                _(
                    "El plazo de cancelación expiró el %(deadline)s "
                    "(%(hours)s horas desde la aprobación).",
                    deadline=fields.Datetime.to_string(deadline),
                    hours=self.CANCEL_LIMIT_HOURS.get(
                        self.l10n_latam_document_type_id.code or "1", 48
                    ),
                )
            )

    def action_cancel_edi(self, reason=""):
        """Evento de cancelación del DE aprobado."""
        self.ensure_one()
        if not self.l10n_py_cdc:
            raise UserError(_("No se puede cancelar un documento sin CDC"))
        if self.l10n_py_edi_status not in ("accepted", "accepted_obs"):
            raise UserError(
                _("Solo se pueden cancelar documentos aprobados por SIFEN.")
            )
        self._validate_cancel_deadline()
        self._get_edi_connector()
        event = self.env["l10n_py.edi.event"].create(
            {
                "move_id": self.id,
                "company_id": self.company_id.id,
                "cdc": self.l10n_py_cdc,
                "event_type": "cancel",
                "reason": reason or _("Cancelación"),
            }
        )
        event.action_send()
        if event.state in ("rejected", "error"):
            raise UserError(
                _("Error cancelando documento:\n%s")
                % (event.errors or event.response_message)
            )
        return event

    def _l10n_py_on_event_result(self, event, result):
        """Aplica al documento el resultado de un evento (``l10n_py.edi.event``)."""
        self.ensure_one()
        if event.event_type == "cancel":
            self._l10n_py_edi_apply_cancel_result(result)
            return
        if event.state != "accepted":
            return
        if event.event_type == "nomination":
            self.message_post(
                body=_(
                    "Receptor nominado ante SIFEN: %(partner)s "
                    "(protocolo %(protocol)s)."
                )
                % {
                    "partner": event.partner_id.display_name,
                    "protocol": event.protocol or "-",
                }
            )
        else:
            self.message_post(
                body=_(
                    "Evento '%(event)s' aprobado por SIFEN (protocolo %(protocol)s)."
                )
                % {
                    "event": dict(event._fields["event_type"].selection)[
                        event.event_type
                    ],
                    "protocol": event.protocol or "-",
                }
            )

    # ============== CONTINGENCIA ==============

    def _l10n_py_switch_to_contingency(self, motive):
        """Pasa documentos no aprobados a emisión en contingencia (iTipEmi=2):
        el CDC cambia (dígito 34), por eso se regenera al transmitir."""
        for move in self:
            if move.l10n_py_edi_status not in ("draft", "to_send", "error", "rejected"):
                raise UserError(
                    _("%s ya fue transmitido: no puede pasar a contingencia.")
                    % move.display_name
                )
            move.write(
                {
                    "l10n_py_emission_type": "2",
                    "l10n_py_contingency_motive": motive,
                    "l10n_py_edi_status": "to_send"
                    if move.state == "posted"
                    else "draft",
                    "l10n_py_cdc": False,
                    "l10n_py_qr_string": False,
                    "l10n_py_qr_code": False,
                    "l10n_py_edi_errors": False,
                    "l10n_py_edi_message": _("Emisión en contingencia: %s") % motive,
                }
            )
            move.message_post(body=_("Documento pasado a contingencia: %s") % motive)
        return True

    def _l10n_py_maybe_auto_contingency(self, connector):
        """Tras un error de transporte, pasa a contingencia si la compañía lo
        tiene activado y el proveedor lo soporta."""
        for move in self:
            if (
                move.company_id.l10n_py_edi_auto_contingency
                and move.l10n_py_edi_status == "error"
                and move.l10n_py_edi_retryable
                and move.l10n_py_emission_type == "1"
                and connector.supports("contingency")
            ):
                move._l10n_py_switch_to_contingency(
                    _("SIFEN no disponible: %s") % (move.l10n_py_edi_message or "")
                )

    def _l10n_py_edi_apply_cancel_result(self, result, raise_on_error=False):
        self.ensure_one()
        status = result["status"]
        errors = self._l10n_py_format_errors(result.get("errors"))
        if status in ("accepted", "accepted_obs"):
            self.write(
                {
                    "l10n_py_edi_status": "cancelled",
                    "l10n_py_edi_message": _("Cancelado el %s")
                    % fields.Datetime.to_string(fields.Datetime.now()),
                    "l10n_py_edi_errors": False,
                }
            )
        elif status == "processing":
            self.write(
                {
                    "l10n_py_edi_status": "to_cancel",
                    "l10n_py_edi_message": _(
                        "Cancelación enviada; esperando respuesta"
                    ),
                }
            )
        else:
            # El evento fue rechazado o falló el transporte: el DE sigue aprobado.
            if self.l10n_py_edi_status == "to_cancel":
                self.l10n_py_edi_status = "accepted"
            self.l10n_py_edi_errors = errors
            if raise_on_error:
                raise UserError(
                    _("Error cancelando documento:\n%s")
                    % (errors or result.get("error"))
                )

    def action_retry_edi(self):
        """Reintentar envío de documento"""
        self.ensure_one()

        if self.l10n_py_edi_status not in ["error", "rejected"]:
            raise UserError(
                _("Solo se pueden reintentar documentos con error o rechazados")
            )

        return self.action_send_edi()

    def action_download_xml(self):
        """Descargar XML del documento"""
        self.ensure_one()

        if not self.l10n_py_edi_xml:
            raise UserError(_("No hay XML disponible para este documento"))

        return {
            "type": "ir.actions.act_url",
            "url": (
                f"/web/content/{self._name}/{self.id}/l10n_py_edi_xml/"
                f"{self.l10n_py_edi_xml_filename}?download=true"
            ),
            "target": "self",
        }

    def action_download_kude(self):
        """Descargar KUDE (PDF)"""
        self.ensure_one()

        if not self.l10n_py_kude_pdf:
            # Intentar generar KUDE
            self._generate_kude()

        if not self.l10n_py_kude_pdf:
            raise UserError(_("No hay KUDE disponible para este documento"))

        return {
            "type": "ir.actions.act_url",
            "url": (
                f"/web/content/{self._name}/{self.id}/l10n_py_kude_pdf/"
                f"{self.l10n_py_kude_filename}?download=true"
            ),
            "target": "self",
        }

    def _generate_kude(self):
        """Generar y guardar el KuDE (representación gráfica del DE) con el
        motor configurado (``l10n_py.kude_engine``)."""
        import base64

        self.ensure_one()
        if self._l10n_py_kude_engine() == "pykude" and not self.l10n_py_edi_xml:
            return
        if not self.l10n_py_cdc:
            return
        pdf_bytes = self._l10n_py_render_kude()
        self.l10n_py_kude_pdf = base64.b64encode(pdf_bytes)
        self.l10n_py_kude_filename = f"KUDE_{self.l10n_py_cdc}.pdf"

    # ============== CRON METHODS ==============

    @api.model
    def _cron_check_edi_status(self, limit=None):
        """Reenvía contingencias pendientes y aplica el estado de los documentos
        enviados/en proceso (``check_status`` del conector).

        Prioriza los documentos más cercanos al plazo de transmisión. El
        tamaño de cada corrida se controla con ``l10n_py.cron_batch_size``.
        """
        limit = limit or int(self._l10n_py_get_param("l10n_py.cron_batch_size", 50))
        contingency_docs = self.search(
            [
                ("l10n_py_edi_status", "=", "to_send"),
                ("l10n_py_emission_type", "=", "2"),
                ("state", "=", "posted"),
            ],
            order="l10n_py_transmission_deadline asc",
            limit=limit,
        )
        for doc in contingency_docs:
            try:
                # savepoint: un fallo no arrastra a los demás documentos
                with self.env.cr.savepoint():
                    doc._l10n_py_edi_send()
            except Exception:
                _logger.exception("Error reenviando contingencia %s", doc.display_name)

        pending_docs = self.search(
            [("l10n_py_edi_status", "in", ["sent", "processing", "to_cancel"])],
            order="l10n_py_transmission_deadline asc",
            limit=limit,
        )
        for doc in pending_docs:
            try:
                with self.env.cr.savepoint():
                    doc.action_check_edi_status()
            except Exception:
                _logger.exception(
                    "Error verificando estado EDI de %s", doc.display_name
                )

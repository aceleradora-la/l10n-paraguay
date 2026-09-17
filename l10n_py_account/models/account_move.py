# l10n_py_account/models/account_move.py

from num2words import num2words

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class AccountMove(models.Model):
    _inherit = "account.move"

    @api.constrains("state", "l10n_latam_document_type_id")
    def _check_l10n_latam_documents(self):
        """Pular validação de documento LATAM durante instalação de módulos.

        As invoices demo do account padrão são postadas pelo try_loading sem
        document number, causando ValidationError. Isso é comportamento
        esperado em todas as localizações LATAM — pulamos durante instalação.
        """
        if not self.env.registry.ready:
            return
        return super()._check_l10n_latam_documents()

    # ============== CAMPOS CONTABILIDAD PARAGUAY ==============

    l10n_py_authorization_id = fields.Many2one(
        "account.authorization",
        string="Timbrado",
        domain=(
            "[('company_id', '=', company_id), "
            "('active', '=', True), "
            "('state', '!=', 'expired')]"
        ),
        help="Timbrado utilizado para esta factura",
    )

    l10n_py_invoice_number = fields.Integer(
        string="Número de Factura",
        help="Número de factura según timbrado autorizado",
    )

    l10n_py_full_invoice_number = fields.Char(
        string="Número Completo",
        compute="_compute_l10n_py_full_invoice_number",
        store=True,
        help="Número completo de factura (formato: 001-001-0000001)",
    )

    # ============== CAMPOS IVA BREAKDOWN (SIFEN) ==============

    l10n_py_amount_subtotal_10 = fields.Monetary(
        string="Total Gravado 10% (F005)",
        compute="_compute_l10n_py_iva",
        store=True,
        currency_field="currency_id",
        help="Subtotal gravado 10% — valor con impuesto incluido (SIFEN F005)",
    )

    l10n_py_amount_iva_10 = fields.Monetary(
        string="Liquidación IVA 10% (F016)",
        compute="_compute_l10n_py_iva",
        store=True,
        currency_field="currency_id",
        help="Liquidación IVA 10% (SIFEN F016)",
    )

    l10n_py_amount_subtotal_5 = fields.Monetary(
        string="Total Gravado 5% (F004)",
        compute="_compute_l10n_py_iva",
        store=True,
        currency_field="currency_id",
        help="Subtotal gravado 5% — valor con impuesto incluido (SIFEN F004)",
    )

    l10n_py_amount_iva_5 = fields.Monetary(
        string="Liquidación IVA 5% (F015)",
        compute="_compute_l10n_py_iva",
        store=True,
        currency_field="currency_id",
        help="Liquidación IVA 5% (SIFEN F015)",
    )

    l10n_py_amount_exempt = fields.Monetary(
        string="Total Exento (F002)",
        compute="_compute_l10n_py_iva",
        store=True,
        currency_field="currency_id",
        help="Subtotal exento/no gravado (SIFEN F002 dSubExe)",
    )

    l10n_py_amount_exonerated = fields.Monetary(
        string="Total Exonerado (F003)",
        compute="_compute_l10n_py_iva",
        store=True,
        currency_field="currency_id",
        help="Subtotal exonerado, Art. 83 Ley 125/91 (SIFEN F003 dSubExo)",
    )

    l10n_py_amount_discount = fields.Monetary(
        string="Total Descuento (F033)",
        compute="_compute_l10n_py_iva",
        store=True,
        currency_field="currency_id",
        help="Suma de descuentos por ítem (SIFEN dTotDesc)",
    )

    l10n_py_amount_rounding = fields.Monetary(
        string="Redondeo (F034)",
        compute="_compute_l10n_py_iva",
        store=True,
        currency_field="currency_id",
        help="Diferencia por redondeo de la moneda (SIFEN dRedon). En guaraníes "
        "todos los importes son enteros, por lo que normalmente es 0.",
    )

    l10n_py_amount_iva_total = fields.Monetary(
        string="Total IVA (F014)",
        compute="_compute_l10n_py_iva",
        store=True,
        currency_field="currency_id",
        help="Total liquidación IVA (SIFEN F014)",
    )

    l10n_py_base_10 = fields.Monetary(
        string="Base Gravada 10% (F019)",
        compute="_compute_l10n_py_iva",
        store=True,
        currency_field="currency_id",
        help="Base gravada neta 10% sin IVA (SIFEN F019)",
    )

    l10n_py_base_5 = fields.Monetary(
        string="Base Gravada 5% (F018)",
        compute="_compute_l10n_py_iva",
        store=True,
        currency_field="currency_id",
        help="Base gravada neta 5% sin IVA (SIFEN F018)",
    )

    l10n_py_base_total = fields.Monetary(
        string="Total Base Gravada (F020)",
        compute="_compute_l10n_py_iva",
        store=True,
        currency_field="currency_id",
        help="Total base gravada (SIFEN F020 = F018 + F019)",
    )

    l10n_py_total_operation = fields.Monetary(
        string="Total Operación (F008)",
        compute="_compute_l10n_py_iva",
        store=True,
        currency_field="currency_id",
        help="Total de la operación (SIFEN F008 = F003 + F004 + F005)",
    )

    # ============== CAMPOS TIPO DE CAMBIO PYG ==============

    l10n_py_exchange_rate = fields.Float(
        string="Tipo de Cambio",
        digits=(16, 4),
        help="Tipo de cambio a guaraníes (PYG) para facturación en moneda extranjera",
    )

    l10n_py_amount_total_pyg = fields.Monetary(
        string="Total en Guaraníes (F023)",
        compute="_compute_l10n_py_total_pyg",
        store=True,
        currency_field="currency_id",
        help="Total de la operación en guaraníes (SIFEN F023)",
    )

    l10n_py_amount_total_words = fields.Char(
        string="Total en Letras",
        compute="_compute_l10n_py_amount_total_words",
    )

    _sql_constraints = [
        (
            "l10n_py_invoice_unique",
            "unique(l10n_py_authorization_id, l10n_py_invoice_number)",
            "El número de factura debe ser único por timbrado.",
        ),
    ]

    # ============== ACTION METHODS ==============

    def _post(self, soft=True):
        """Numeración secuencial al confirmar. Se engancha en ``_post`` (no en
        ``action_post``) para cubrir también las facturas generadas por código,
        p. ej. las del Punto de Venta."""
        for move in self:
            if (
                move.move_type in ("out_invoice", "out_refund")
                and move.company_id.country_id.code == "PY"
                and move.journal_id.l10n_latam_use_documents
                and move.l10n_latam_document_type_id
            ):
                if not move.l10n_py_authorization_id:
                    if not self.env.registry.ready:
                        # Pular durante instalação/demo (invoices genéricas
                        # criadas pelo account.chart.template.try_loading)
                        continue
                    raise UserError(
                        _(
                            "Debe seleccionar un timbrado para confirmar "
                            "una factura de venta."
                        )
                    )
                if not move.l10n_py_invoice_number:
                    auth = move.l10n_py_authorization_id
                    auth.check_validity()
                    # Flush pending writes so the SQL query sees all data
                    self.env["account.move"].flush_model(["l10n_py_invoice_number"])
                    # Bloquear el timbrado: dos transacciones concurrentes no
                    # pueden obtener el mismo número (se serializan aquí).
                    self.env.cr.execute(
                        "SELECT id FROM account_authorization WHERE id = %s FOR UPDATE",
                        (auth.id,),
                    )
                    # Query next number directly to avoid ORM cache issues
                    self.env.cr.execute(
                        """
                        SELECT COALESCE(MAX(l10n_py_invoice_number), 0)
                        FROM account_move
                        WHERE l10n_py_authorization_id = %s
                          AND l10n_py_invoice_number > 0
                          AND move_type IN ('out_invoice', 'out_refund')
                        """,
                        (auth.id,),
                    )
                    max_num = self.env.cr.fetchone()[0]
                    next_num = max_num + 1 if max_num else auth.invoice_number_from
                    if next_num > auth.invoice_number_to:
                        raise UserError(
                            _(
                                "La faja de numeración está agotada "
                                "para el timbrado %(timbrado)s.",
                                timbrado=auth.name,
                            )
                        )
                    auth.check_number_available(next_num, exclude_move_id=move.id)
                    move.l10n_py_invoice_number = next_num
        return super()._post(soft=soft)

    # ============== COMPUTE METHODS ==============

    @api.depends(
        "l10n_py_authorization_id",
        "l10n_py_invoice_number",
    )
    def _compute_l10n_py_full_invoice_number(self):
        """Calcular número completo de factura (formato: 001-001-0000001)"""
        for move in self:
            if move.l10n_py_authorization_id and move.l10n_py_invoice_number:
                auth = move.l10n_py_authorization_id
                number_str = str(move.l10n_py_invoice_number).zfill(7)
                move.l10n_py_full_invoice_number = (
                    f"{auth.establishment}-{auth.expedition_point}-{number_str}"
                )
            else:
                move.l10n_py_full_invoice_number = False

    def _l10n_py_round(self, amount):
        """Único punto de redondeo de importes SIFEN: la precisión de la moneda
        del documento (guaraníes sin decimales; 2 decimales en el resto)."""
        self.ensure_one()
        currency = self.currency_id or self.company_id.currency_id
        return currency.round(amount) if currency else round(amount, 2)

    def _l10n_py_line_iva_params(self, line):
        """``(tasa, afectación, proporción)`` de una línea a partir de sus
        impuestos (ver ``account.tax._l10n_py_get_iva_params``)."""
        return line.tax_ids._l10n_py_get_iva_params()

    def _l10n_py_line_amounts(self, line):
        """Importes SIFEN de una línea (grupo E7/E8), sin redondear.

        Devuelve dict con ``total`` (dTotOpeItem: precio con IVA por cantidad,
        neto de descuento), ``discount`` (descuento total de la línea),
        ``base`` (dBasGravIVA), ``iva`` (dLiqIVAItem), ``exempt_base``
        (dBasExe), ``rate``, ``affectation``, ``proportion``.
        """
        rate, affectation, proportion = self._l10n_py_line_iva_params(line)
        total = line.price_total
        discount = line.quantity * line.price_unit * (line.discount or 0.0) / 100.0
        if affectation in ("1", "4") and rate:
            base = (total * proportion / 100.0) / (1 + rate / 100.0)
            iva = base * rate / 100.0
            exempt_base = (
                (total * (100.0 - proportion) / 100.0) if affectation == "4" else 0.0
            )
        else:
            base = iva = 0.0
            exempt_base = total
        return {
            "total": total,
            "discount": discount,
            "base": base,
            "iva": iva,
            "exempt_base": exempt_base,
            "rate": rate,
            "affectation": affectation,
            "proportion": proportion,
        }

    @api.depends(
        "invoice_line_ids.price_subtotal",
        "invoice_line_ids.price_total",
        "invoice_line_ids.discount",
        "invoice_line_ids.tax_ids",
        "invoice_line_ids.tax_ids.l10n_py_iva_affectation",
        "invoice_line_ids.tax_ids.l10n_py_iva_rate",
        "invoice_line_ids.tax_ids.l10n_py_taxable_proportion",
        "currency_id",
    )
    def _compute_l10n_py_iva(self):
        """Desglose de IVA según SIFEN (grupo F) a partir de la afectación de
        cada impuesto, nunca del porcentaje del importe calculado.

        base = (total * proporción/100) / (1 + tasa/100); iva = base * tasa/100.
        """
        for move in self:
            subtotal_10 = iva_10 = base_10 = 0.0
            subtotal_5 = iva_5 = base_5 = 0.0
            exempt = exonerated = discount = 0.0

            for line in move.invoice_line_ids.filtered(
                lambda line: line.display_type == "product"
            ):
                amounts = move._l10n_py_line_amounts(line)
                discount += amounts["discount"]
                if amounts["affectation"] in ("1", "4") and amounts["rate"] == 10:
                    subtotal_10 += amounts["total"]  # F005
                    iva_10 += amounts["iva"]  # F016
                    base_10 += amounts["base"]  # F019
                    exempt += amounts["exempt_base"]
                elif amounts["affectation"] in ("1", "4") and amounts["rate"] == 5:
                    subtotal_5 += amounts["total"]  # F004
                    iva_5 += amounts["iva"]  # F015
                    base_5 += amounts["base"]  # F018
                    exempt += amounts["exempt_base"]
                elif amounts["affectation"] == "2":
                    exonerated += amounts["total"]  # F003
                else:
                    exempt += amounts["total"]  # F002

            r = move._l10n_py_round
            move.l10n_py_amount_subtotal_10 = r(subtotal_10)
            move.l10n_py_amount_iva_10 = r(iva_10)
            move.l10n_py_base_10 = r(base_10)
            move.l10n_py_amount_subtotal_5 = r(subtotal_5)
            move.l10n_py_amount_iva_5 = r(iva_5)
            move.l10n_py_base_5 = r(base_5)
            move.l10n_py_amount_exempt = r(exempt)
            move.l10n_py_amount_exonerated = r(exonerated)
            move.l10n_py_amount_discount = r(discount)
            move.l10n_py_amount_iva_total = r(iva_10 + iva_5)  # F014
            move.l10n_py_base_total = r(base_10 + base_5)  # F020
            total_operation = r(exempt + exonerated + subtotal_5 + subtotal_10)  # F008
            move.l10n_py_total_operation = total_operation
            # dRedon: diferencia entre el total a pagar de Odoo y el total de
            # operación SIFEN (0 en guaraníes, donde todo es entero).
            move.l10n_py_amount_rounding = r(
                (move.amount_total or 0.0) - total_operation
            )

    @api.depends("amount_total", "l10n_py_exchange_rate")
    def _compute_l10n_py_total_pyg(self):
        """Calcular total en guaraníes (F023) para facturas en moneda extranjera"""
        for move in self:
            if move.l10n_py_exchange_rate and move.l10n_py_exchange_rate > 0:
                move.l10n_py_amount_total_pyg = (
                    move.amount_total * move.l10n_py_exchange_rate
                )
            else:
                move.l10n_py_amount_total_pyg = 0.0

    @api.depends("amount_total", "currency_id")
    def _compute_l10n_py_amount_total_words(self):
        """Convertir total a letras en español"""
        # Mapa de nombres en español para monedas comunes en Paraguay
        _CURRENCY_NAMES_ES = {
            "PYG": "guaraníes",
            "USD": "dólares americanos",
            "BRL": "reales",
            "EUR": "euros",
            "ARS": "pesos argentinos",
        }
        for move in self:
            if move.amount_total:
                currency_code = move.currency_id.name or ""
                currency_name = _CURRENCY_NAMES_ES.get(
                    currency_code,
                    move.currency_id.currency_unit_label or "guaraníes",
                )
                amount_words = num2words(int(move.amount_total), lang="es")
                move.l10n_py_amount_total_words = (
                    f"{amount_words} {currency_name}".capitalize()
                )
            else:
                move.l10n_py_amount_total_words = False

    # ============== CONSTRAINT METHODS ==============

    @api.constrains("l10n_py_authorization_id", "l10n_py_invoice_number")
    def _check_authorization_number(self):
        """Validar que el número de factura esté dentro del rango autorizado"""
        for move in self:
            if move.l10n_py_authorization_id and move.l10n_py_invoice_number:
                move.l10n_py_authorization_id.check_number_available(
                    move.l10n_py_invoice_number,
                    exclude_move_id=move.id,
                )

    @api.constrains("l10n_py_authorization_id")
    def _check_authorization_validity(self):
        """Validar que el timbrado esté vigente"""
        for move in self:
            if move.l10n_py_authorization_id:
                move.l10n_py_authorization_id.check_validity()

    # ============== ONCHANGE METHODS ==============

    @api.onchange("l10n_py_authorization_id")
    def _onchange_authorization_id(self):
        """Limpiar número al cambiar timbrado — se asigna en action_post"""
        if self.l10n_py_authorization_id:
            self.l10n_py_invoice_number = 0

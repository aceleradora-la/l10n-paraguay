# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
"""Base común para los tests de facturación electrónica paraguaya.

Crea una compañía PY con RUC, tipos de documento, timbrado, diario
electrónico, impuestos 10 % / 5 % / exento y partners contribuyente,
no contribuyente, innominado y extranjero. Los módulos que agregan
conectores heredan de ``L10nPyEdiCommon`` y crean su conector en
``setUpClass``.
"""

from datetime import date, timedelta

from odoo.tests.common import TransactionCase


class L10nPyEdiCommon(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True))
        cls.country_py = cls.env.ref("base.py")
        cls.currency_pyg = cls.env.ref("base.PYG")

        cls.company = cls.env["res.company"].create(
            {
                "name": "Empresa EDI Test SRL",
                "country_id": cls.country_py.id,
                "currency_id": cls.currency_pyg.id,
                "l10n_py_ruc": "80009401",
                "l10n_py_trade_name": "EDI Test",
                "l10n_py_economic_activity_code": "46510",
                "l10n_py_economic_activity": "Comercio al por mayor",
                "street": "Avda. Mariscal López 3456",
                "city": "Asunción",
            }
        )
        cls.company.partner_id.write({"country_id": cls.country_py.id})
        cls.env.user.company_ids |= cls.company
        cls.env.user.company_id = cls.company
        cls.env = cls.env(
            context=dict(cls.env.context, allowed_company_ids=cls.company.ids)
        )

        cls.doc_types = {}
        for code, xmlid, name, internal in (
            ("1", "l10n_py_account.dc_py_f", "Factura Electrónica", "invoice"),
            ("4", "l10n_py_account.dc_py_af", "Autofactura Electrónica", "invoice"),
            (
                "5",
                "l10n_py_account.dc_py_nc",
                "Nota de Crédito Electrónica",
                "credit_note",
            ),
            (
                "6",
                "l10n_py_account.dc_py_nd",
                "Nota de Débito Electrónica",
                "debit_note",
            ),
            (
                "7",
                "l10n_py_account.dc_py_nr",
                "Nota de Remisión Electrónica",
                "invoice",
            ),
        ):
            doc_type = cls.env.ref(xmlid, raise_if_not_found=False)
            if not doc_type:
                doc_type = cls.env["l10n_latam.document.type"].search(
                    [("country_id", "=", cls.country_py.id), ("code", "=", code)],
                    limit=1,
                ) or cls.env["l10n_latam.document.type"].create(
                    {
                        "name": name,
                        "code": code,
                        "country_id": cls.country_py.id,
                        "internal_type": internal,
                    }
                )
            cls.doc_types[code] = doc_type
        cls.doc_type_fe = cls.doc_types["1"]
        cls.doc_type_nce = cls.doc_types["5"]
        cls.doc_type_nde = cls.doc_types["6"]

        today = date.today()
        cls.authorization = cls.env["account.authorization"].create(
            {
                "name": "12345678",
                "date_from": today - timedelta(days=30),
                "date_to": today + timedelta(days=335),
                "invoice_number_from": 1,
                "invoice_number_to": 9999999,
                "establishment": "001",
                "expedition_point": "001",
                "l10n_latam_document_type_id": cls.doc_type_fe.id,
                "company_id": cls.company.id,
            }
        )

        cls.account_receivable = cls._get_or_create_account(
            "asset_receivable", "121001", "Deudores por ventas", reconcile=True
        )
        cls.account_income = cls._get_or_create_account(
            "income", "411001", "Ventas de mercaderías"
        )
        cls.account_tax = cls._get_or_create_account(
            "liability_current", "221001", "IVA débito fiscal"
        )

        cls.journal = cls.env["account.journal"].create(
            {
                "name": "Facturas Electrónicas",
                "type": "sale",
                "code": "FE",
                "company_id": cls.company.id,
                "l10n_latam_use_documents": True,
                "l10n_py_establishment": "001",
                "l10n_py_point": "001",
                "l10n_py_authorization_id": cls.authorization.id,
                "default_account_id": cls.account_income.id,
            }
        )

        cls.tax_group = cls.env["account.tax.group"].create(
            {
                "name": "IVA",
                "company_id": cls.company.id,
                "country_id": cls.country_py.id,
            }
        )
        cls.tax_10 = cls._create_tax("IVA 10%", 10.0)
        cls.tax_5 = cls._create_tax("IVA 5%", 5.0)
        cls.tax_exempt = cls._create_tax("Exento", 0.0)

        cls.partner_contribuyente = cls.env["res.partner"].create(
            {
                "name": "Cliente Contribuyente SA",
                "is_company": True,
                "country_id": cls.country_py.id,
                "l10n_py_ruc": "80028061",
                "l10n_py_taxpayer_type": "1",
                "street": "Calle Palma 123",
                "email": "cliente@test.com.py",
            }
        )
        cls.partner_no_contribuyente = cls.env["res.partner"].create(
            {
                "name": "Juan Pérez",
                "country_id": cls.country_py.id,
                "l10n_py_taxpayer_type": "2",
                "l10n_py_doc_type": "1",
                "l10n_py_doc_number": "1234567",
                "street": "Barrio Sajonia",
            }
        )
        cls.partner_innominado = cls.env["res.partner"].create(
            {
                "name": "Sin Nombre",
                "country_id": cls.country_py.id,
                "l10n_py_taxpayer_type": "2",
                "street": "N/A",
            }
        )
        cls.partner_extranjero = cls.env["res.partner"].create(
            {
                "name": "Foreign Customer Ltd",
                "is_company": True,
                "country_id": cls.env.ref("base.us").id,
                "l10n_py_taxpayer_type": "2",
                "l10n_py_doc_type": "2",
                "l10n_py_doc_number": "P1234567",
                "street": "5th Avenue 100",
            }
        )
        cls.partner = cls.partner_contribuyente

        cls.product = cls.env["product.product"].create(
            {
                "name": "Producto EDI",
                "type": "consu",
                "list_price": 100000,
                "l10n_py_ncm_code": "84713000",
                "l10n_py_unit_code": 77,
            }
        )
        cls.service = cls.env["product.product"].create(
            {
                "name": "Servicio EDI",
                "type": "service",
                "list_price": 50000,
                "l10n_py_ncm_code": "00000000",
            }
        )

    @classmethod
    def _get_or_create_account(cls, account_type, code, name, reconcile=False):
        account = cls.env["account.account"].search(
            [
                ("company_ids", "in", cls.company.id),
                ("account_type", "=", account_type),
            ],
            limit=1,
        )
        if account:
            return account
        return cls.env["account.account"].create(
            {
                "name": name,
                "code": code,
                "account_type": account_type,
                "reconcile": reconcile,
                "company_ids": [(6, 0, [cls.company.id])],
            }
        )

    @classmethod
    def _create_tax(cls, name, amount):
        return cls.env["account.tax"].create(
            {
                "name": name,
                "amount": amount,
                "amount_type": "percent",
                "type_tax_use": "sale",
                "company_id": cls.company.id,
                "tax_group_id": cls.tax_group.id,
                "price_include_override": "tax_included",
            }
        )

    @classmethod
    def _create_invoice(
        cls, partner=None, lines=None, doc_type=None, post=True, **vals
    ):
        """Factura de venta electrónica con líneas ``[(product, qty, price, tax)]``."""
        partner = partner or cls.partner_contribuyente
        lines = lines or [(cls.product, 1, 110000, cls.tax_10)]
        move_vals = {
            "move_type": "out_invoice",
            "partner_id": partner.id,
            "journal_id": cls.journal.id,
            "company_id": cls.company.id,
            "invoice_date": date.today(),
            "l10n_latam_document_type_id": (doc_type or cls.doc_type_fe).id,
            "l10n_py_authorization_id": cls.authorization.id,
            "invoice_line_ids": [
                (
                    0,
                    0,
                    {
                        "product_id": product.id,
                        "quantity": qty,
                        "price_unit": price,
                        "tax_ids": [(6, 0, tax.ids)] if tax else False,
                        "account_id": cls.account_income.id,
                    },
                )
                for product, qty, price, tax in lines
            ],
        }
        move_vals.update(vals)
        move = cls.env["account.move"].create(move_vals)
        if post:
            move.action_post()
        return move

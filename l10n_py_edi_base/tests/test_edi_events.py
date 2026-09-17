# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
"""Eventos SIFEN (``l10n_py.edi.event``), contingencia y KuDE QWeb con un
conector simulado (``mock.patch`` sobre la interfaz pública)."""

import base64
import io
from unittest import mock

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import tagged

from ..services.qr_generator import QRGenerator
from .common import L10nPyEdiCommon

CDC = "01800094017001001000000112026091512345678901"


@tagged("post_install", "-at_install", "l10n_py")
class TestEdiEvents(L10nPyEdiCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Connector = cls.env["l10n_py.edi.connector"]
        # proveedor de prueba: el base no define ninguno (selection_add en los
        # módulos conectores); se agrega al campo solo durante estos tests
        field = cls.Connector._fields["provider_type"]
        original = field.selection
        field.selection = list(original) + [("mock", "Mock")]
        cls.addClassCleanup(setattr, field, "selection", original)
        if hasattr(field, "_selection"):  # caché de valores usada al validar
            cached = field._selection
            field._selection = list(cached or []) + ["mock"]
            cls.addClassCleanup(setattr, field, "_selection", cached)
        cls.connector = cls.Connector.create(
            {
                "name": "Mock",
                "company_id": cls.company.id,
                "environment": "test",
                "provider_type": "mock",
            }
        )
        cls._kude_patcher = mock.patch.object(
            type(cls.env["account.move"]), "_generate_kude", return_value=None
        )
        cls._kude_patcher.start()
        cls.addClassCleanup(cls._kude_patcher.stop)

    def _patch_connector(self, **overrides):
        caps = {
            "batch": False,
            "async": False,
            "events": {
                "cancel",
                "nomination",
                "receipt_notification",
                "receipt_conformity",
                "receipt_disconformity",
                "receipt_unknown",
            },
            "pdf": False,
            "ruc_query": False,
            "contingency": True,
            "preview": False,
        }
        caps.update(overrides.pop("caps", {}))
        patchers = [
            mock.patch.object(
                type(self.connector), "_get_capabilities", return_value=caps
            )
        ]
        for name, value in overrides.items():
            patchers.append(mock.patch.object(type(self.connector), name, value))
        for p in patchers:
            p.start()
            self.addCleanup(p.stop)

    def _create_bill(self):
        """Factura de proveedor (documento recibido) sin numeración latam."""
        journal = self.env["account.journal"].search(
            [("company_id", "=", self.company.id), ("type", "=", "purchase")], limit=1
        ) or self.env["account.journal"].create(
            {
                "name": "Compras",
                "type": "purchase",
                "code": "FC",
                "company_id": self.company.id,
            }
        )
        payable = self._get_or_create_account(
            "liability_payable", "211001", "Proveedores", reconcile=True
        )
        self.partner_contribuyente.with_company(
            self.company
        ).property_account_payable_id = payable
        return self._create_invoice(
            move_type="in_invoice",
            partner=self.partner_contribuyente,
            post=False,
            journal_id=journal.id,
            l10n_latam_document_type_id=False,
            l10n_py_authorization_id=False,
        )

    def _accepted_move(self, partner=None):
        move = self._create_invoice(partner=partner)
        move.write(
            {
                "l10n_py_edi_status": "accepted",
                "l10n_py_cdc": CDC,
                "l10n_py_edi_approval_date": fields.Datetime.now(),
            }
        )
        return move

    def _event_ok(self, event_type, payload):
        return self.Connector._make_result(
            "accepted",
            documents=[
                {
                    "cdc": payload.get("cdc"),
                    "protocol": "555",
                    "code": "0600",
                    "message": "ok",
                }
            ],
        )

    # ------------------------------------------------------------ eventos
    def test_nomination_payload_and_result(self):
        sent = []

        def send_event(connector, event_type, payload):
            sent.append((event_type, payload))
            return self._event_ok(event_type, payload)

        self._patch_connector(send_event=send_event)
        move = self._accepted_move(partner=self.partner_innominado)
        wizard = (
            self.env["l10n_py.edi.event.wizard"]
            .with_context(active_id=move.id)
            .create(
                {
                    "partner_id": self.partner_contribuyente.id,
                    "reason": "Se identifica al receptor",
                }
            )
        )
        self.assertEqual(wizard.event_type, "nomination")
        action = wizard.action_send()
        event = self.env["l10n_py.edi.event"].browse(action["res_id"])
        self.assertEqual(event.state, "accepted")
        self.assertEqual(event.protocol, "555")
        self.assertEqual(event.response_code, "0600")
        event_type, payload = sent[0]
        self.assertEqual(event_type, "nomination")
        self.assertEqual(payload["cdc"], CDC)
        self.assertEqual(payload["motivo"], "Se identifica al receptor")
        self.assertEqual(payload["ruc"], "80028061")
        self.assertTrue(payload["contribuyente"])
        self.assertEqual(payload["razonSocial"], "Cliente Contribuyente SA")
        self.assertEqual(payload["codigo"], str(self.partner_contribuyente.id))
        self.assertEqual(event.payload_json["cdc"], CDC)
        self.assertIn("nominado", move.message_ids[0].body)

    def test_receiver_events_payloads(self):
        sent = []
        self._patch_connector(
            send_event=lambda c, t, p: sent.append((t, p)) or self._event_ok(t, p)
        )
        bill = self._create_bill()
        bill.write({"l10n_py_cdc": CDC})
        Event = self.env["l10n_py.edi.event"]
        notif = Event.create(
            {
                "move_id": bill.id,
                "event_type": "receipt_notification",
                "receipt_date": "2026-09-16 09:00:00",
                "issue_date": "2026-09-15 08:00:00",
                "total_pyg": 110000,
            }
        )
        notif.action_send()
        self.assertEqual(notif.state, "accepted")
        payload = sent[-1][1]
        self.assertEqual(payload["cdc"], CDC)
        self.assertEqual(payload["fechaRecepcion"], "2026-09-16T09:00:00")
        self.assertEqual(payload["fechaEmision"], "2026-09-15T08:00:00")
        self.assertEqual(payload["tipoReceptor"], 1)
        self.assertEqual(payload["ruc"], "80009401")
        self.assertEqual(payload["nombre"], self.company.name)
        self.assertEqual(payload["totalPYG"], 110000)

        conf = Event.create(
            {
                "move_id": bill.id,
                "event_type": "receipt_conformity",
                "conformity_type": "2",
            }
        )
        conf.action_send()
        self.assertEqual(sent[-1][1]["tipoConformidad"], 2)
        self.assertIn("fechaRecepcion", sent[-1][1])

        disc = Event.create(
            {
                "move_id": bill.id,
                "event_type": "receipt_disconformity",
                "reason": "Importe incorrecto",
            }
        )
        disc.action_send()
        self.assertEqual(sent[-1][1], {"cdc": CDC, "motivo": "Importe incorrecto"})

        unk = Event.create(
            {
                "move_id": bill.id,
                "event_type": "receipt_unknown",
                "reason": "No corresponde a esta empresa",
            }
        )
        unk.action_send()
        self.assertEqual(sent[-1][1]["motivo"], "No corresponde a esta empresa")
        self.assertEqual(sent[-1][1]["nombre"], self.company.name)
        self.assertEqual(
            len(bill.message_ids.filtered(lambda m: "aprobado" in (m.body or ""))), 4
        )

    def test_event_validation_and_errors(self):
        self._patch_connector()
        bill = self._create_bill()
        Event = self.env["l10n_py.edi.event"]
        # sin CDC
        ev = Event.create({"move_id": bill.id, "event_type": "receipt_conformity"})
        with self.assertRaisesRegex(UserError, "CDC"):
            ev.action_send()
        bill.l10n_py_cdc = CDC
        # motivo corto
        ev = Event.create(
            {"move_id": bill.id, "event_type": "receipt_disconformity", "reason": "mal"}
        )
        with self.assertRaisesRegex(UserError, "5 caracteres"):
            ev.action_send()
        # proveedor sin soporte del evento
        self._patch_connector(caps={"events": {"cancel"}})
        ev = Event.create(
            {
                "move_id": bill.id,
                "event_type": "receipt_disconformity",
                "reason": "Importe mal",
            }
        )
        with self.assertRaisesRegex(UserError, "no soporta"):
            ev.action_send()
        self.assertEqual(ev.state, "draft")
        # rechazo de SIFEN y reintento
        self._patch_connector(
            send_event=lambda c, t, p: self.Connector._make_result(
                "rejected", errors=[("4004", "Evento ya registrado", "sifen")]
            )
        )
        ev.action_send()
        self.assertEqual(ev.state, "rejected")
        self.assertIn("[SIFEN] 4004: Evento ya registrado", ev.errors)
        ev.action_draft()
        self.assertEqual(ev.state, "draft")

        # excepción de transporte → error reintentable
        def boom(connector, event_type, payload):
            raise ConnectionError("down")

        self._patch_connector(send_event=boom)
        ev.action_send()
        self.assertEqual(ev.state, "error")
        self.assertIn("down", ev.errors)

    def test_cancel_creates_event(self):
        def cancel_document(connector, cdc, reason=""):
            self.assertEqual((cdc, reason), (CDC, "Datos erróneos"))
            return self.Connector._make_result(
                "accepted", documents=[{"cdc": cdc, "protocol": "777"}]
            )

        self._patch_connector(cancel_document=cancel_document)
        move = self._accepted_move()
        event = move.action_cancel_edi("Datos erróneos")
        self.assertEqual(move.l10n_py_edi_status, "cancelled")
        self.assertEqual(
            (event.event_type, event.state, event.protocol),
            ("cancel", "accepted", "777"),
        )
        # rechazo: el documento sigue aprobado y se levanta el error
        self._patch_connector(
            cancel_document=lambda c, cdc, reason="": self.Connector._make_result(
                "rejected", errors=[("4003", "Plazo vencido", "sifen")]
            )
        )
        move2 = self._accepted_move()
        with self.assertRaisesRegex(UserError, "4003"):
            move2.action_cancel_edi("Otro motivo")
        self.assertEqual(move2.l10n_py_edi_status, "accepted")
        self.assertEqual(
            self.env["l10n_py.edi.event"].search([("move_id", "=", move2.id)]).state,
            "rejected",
        )

    # -------------------------------------------------------- contingencia
    def test_manual_contingency(self):
        self._patch_connector()
        move = self._create_invoice()
        move.write(
            {
                "l10n_py_cdc": CDC,
                "l10n_py_edi_status": "error",
                "l10n_py_edi_retryable": True,
            }
        )
        wizard = (
            self.env["l10n_py.edi.contingency.wizard"]
            .with_context(active_ids=move.ids)
            .create({"motive": "Caída de SIFEN"})
        )
        wizard.action_confirm()
        self.assertEqual(move.l10n_py_emission_type, "2")
        self.assertEqual(move.l10n_py_contingency_motive, "Caída de SIFEN")
        self.assertEqual(move.l10n_py_edi_status, "to_send")
        self.assertFalse(move.l10n_py_cdc)
        self.assertEqual(move._prepare_edi_document_data()["tipoEmision"], 2)
        approved = self._accepted_move()
        with self.assertRaisesRegex(UserError, "transmitido"):
            approved._l10n_py_switch_to_contingency("x")

    def test_auto_contingency_on_transport_error(self):
        self._patch_connector(
            send_document=lambda c, data: c._error_result(
                "DIR-TIMEOUT: sin respuesta", code="DIR-TIMEOUT", retryable=True
            )
        )
        self.company.l10n_py_edi_auto_contingency = False
        move = self._create_invoice()
        move._l10n_py_edi_send()
        self.assertEqual(
            (move.l10n_py_edi_status, move.l10n_py_emission_type), ("error", "1")
        )
        self.company.l10n_py_edi_auto_contingency = True
        move2 = self._create_invoice()
        move2._l10n_py_edi_send()
        self.assertEqual(
            (move2.l10n_py_edi_status, move2.l10n_py_emission_type), ("to_send", "2")
        )
        self.assertIn("SIFEN no disponible", move2.l10n_py_contingency_motive)
        # rechazo de SIFEN (no reintentable) no dispara contingencia
        self._patch_connector(
            send_document=lambda c, data: c._make_result(
                "rejected", errors=[("0160", "XML mal formado", "sifen")]
            )
        )
        move3 = self._create_invoice()
        move3._l10n_py_edi_send()
        self.assertEqual(
            (move3.l10n_py_edi_status, move3.l10n_py_emission_type), ("rejected", "1")
        )


@tagged("post_install", "-at_install", "l10n_py")
class TestKudeQweb(L10nPyEdiCommon):
    def test_qweb_engine_default_and_render(self):
        move = self._create_invoice()
        self.assertEqual(move._l10n_py_kude_engine(), "qweb")
        move.write({"l10n_py_cdc": CDC, "l10n_py_edi_status": "accepted"})
        move.l10n_py_qr_string = QRGenerator.build_qr_link(
            cdc=CDC,
            emission_date="2026-09-15T00:00:00",
            digest_value="YWJj",
            idcsc="0001",
            csc="ABCD",
            total_operation="110000",
            total_iva="10000",
            item_count=1,
            receptor_ruc="80028061",
        )
        move._l10n_py_generate_qr_image()
        move._generate_kude()
        self.assertTrue(move.l10n_py_kude_pdf)
        self.assertEqual(move.l10n_py_kude_filename, f"KUDE_{CDC}.pdf")
        # en modo test Odoo devuelve el HTML del reporte: debe contener el CDC
        content = base64.b64decode(move.l10n_py_kude_pdf)
        self.assertIn(CDC.encode(), content)
        action = move.action_preview_kude()
        self.assertEqual(
            action.get("report_name"), "l10n_py_edi_base.kude_report_template"
        )

    def test_qr_image_is_scannable(self):
        try:
            import zxingcpp
            from PIL import Image
        except ImportError:
            self.skipTest("zxing-cpp no instalado")
        move = self._create_invoice()
        link = QRGenerator.build_qr_link(
            cdc=CDC,
            emission_date="2026-09-15T00:00:00",
            digest_value="YWJj",
            idcsc="0001",
            csc="ABCD",
            total_operation="110000",
            total_iva="10000",
            item_count=1,
            receptor_ruc="80028061",
        )
        move.l10n_py_qr_string = link
        move._l10n_py_generate_qr_image()
        image = Image.open(io.BytesIO(base64.b64decode(move.l10n_py_qr_code)))
        results = zxingcpp.read_barcodes(image)
        self.assertEqual(len(results), 1)
        self.assertIn("QR", str(results[0].format))
        self.assertEqual(results[0].text, link)

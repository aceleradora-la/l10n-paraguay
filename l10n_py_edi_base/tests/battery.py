# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
"""Batería de contrato para conectores.

Cada módulo conector declara ``class TestXContract(ProviderContractBattery,
<Common>)`` e implementa ``_arrange(scenario)``: prepara el transporte
(mocks HTTP, comportamiento del dummy...) para que la siguiente operación
termine en el escenario pedido, o devuelve ``False`` si el proveedor no
modela ese escenario. La batería ejecuta el flujo desde ``account.move`` y
verifica el contrato de ``docs/conectores.md``: estados, forma de
``deList``, origen y prefijo de los errores, adjuntos y reintentos.

Escenarios:

- envío síncrono: ``accepted``, ``accepted_obs``, ``rejected``;
- envío asíncrono: ``processing`` y luego ``poll_accepted``,
  ``poll_accepted_obs``, ``poll_rejected``;
- ``transport_error``;
- eventos: ``cancel_accepted``, ``cancel_rejected``,
  ``inutilization_accepted``;
- ``ruc_query``.
"""

import re

from odoo.exceptions import UserError

CDC_RE = re.compile(r"^\d{44}$")


class ProviderContractBattery:
    # el loader de Odoo (odoo/tests/loader.py) solo toma los test_* definidos en
    # la propia clase salvo que la clase declare esto: sin él, la batería no corre
    allow_inherited_tests_method = True
    provider = None  # provider_type del conector bajo prueba
    error_prefix = None  # prefijo de los errores del intermediario (FS-, DIR-...)
    returns_xml = True  # el proveedor entrega el XML firmado al aprobar
    returns_qr = True  # el proveedor entrega el enlace QR

    def _arrange(self, scenario):
        raise NotImplementedError

    def _connector(self):
        connector = self.env["l10n_py.edi.connector"].search(
            [("company_id", "=", self.company.id)], limit=1
        )
        self.assertEqual(connector.provider_type, self.provider)
        return connector

    def _assert_document_shape(self, move):
        self.assertTrue(CDC_RE.match(move.l10n_py_cdc or ""), "CDC de 44 dígitos")
        self.assertEqual(move.l10n_py_cdc[2:10], self.company.l10n_py_ruc)

    def _send_expecting(self, move, target):
        """Lleva ``move`` al estado ``target`` (accepted / accepted_obs /
        rejected) por la vía síncrona o, si el proveedor es asíncrono, por
        ``processing`` + consulta. Devuelve ``False`` si no hay escenario."""
        if self._arrange(target) is not False:
            move._l10n_py_edi_send()
            return "sync"
        if self._arrange("processing") is False:
            return False
        move._l10n_py_edi_send()
        self.assertEqual(move.l10n_py_edi_status, "processing")
        if self._arrange(f"poll_{target}") is False:
            return False
        move.action_check_edi_status()
        return "async"

    # ------------------------------------------------------------ envío
    def test_contract_accepted(self):
        move = self._create_invoice()
        if not self._send_expecting(move, "accepted"):
            self.skipTest("sin escenario accepted")
        self.assertEqual(move.l10n_py_edi_status, "accepted")
        self._assert_document_shape(move)
        self.assertTrue(move.l10n_py_edi_approval_date)
        self.assertFalse(move.l10n_py_edi_errors)
        if self.returns_qr:
            self.assertIn("ekuatia.set.gov.py", move.l10n_py_qr_string or "")
            self.assertTrue(move.l10n_py_qr_code)
        if self.returns_xml:
            self.assertEqual(
                move.l10n_py_edi_xml_attachment_id.name, f"{move.l10n_py_cdc}.xml"
            )
        with self.assertRaises(UserError):
            move.button_draft()

    def test_contract_accepted_obs(self):
        move = self._create_invoice()
        if not self._send_expecting(move, "accepted_obs"):
            self.skipTest("sin escenario accepted_obs")
        self.assertEqual(move.l10n_py_edi_status, "accepted_obs")
        self._assert_document_shape(move)
        self.assertIn("[SIFEN]", move.l10n_py_edi_errors or "")

    def test_contract_rejected(self):
        move = self._create_invoice()
        mode = self._send_expecting(move, "rejected")
        if not mode:
            self.skipTest("sin escenario rejected")
        self.assertEqual(move.l10n_py_edi_status, "rejected")
        self.assertFalse(move.l10n_py_edi_retryable)
        self.assertIn("[SIFEN]", move.l10n_py_edi_errors)
        if mode == "sync":
            # un solo documento: el rechazo se muestra al usuario
            self._arrange("rejected")
            with self.assertRaises(UserError):
                move.action_send_edi()
        # corregir y reenviar es posible
        self.assertTrue(self._send_expecting(move, "accepted"))
        self.assertEqual(move.l10n_py_edi_status, "accepted")

    def test_contract_transport_error(self):
        if self._arrange("transport_error") is False:
            self.skipTest("sin escenario transport_error")
        move = self._create_invoice()
        move._l10n_py_edi_send()
        self.assertEqual(move.l10n_py_edi_status, "error")
        self.assertTrue(move.l10n_py_edi_retryable)
        self.assertIn("[Proveedor]", move.l10n_py_edi_errors)
        if self.error_prefix:
            self.assertIn(self.error_prefix, move.l10n_py_edi_errors)
        self.assertNotIn("[SIFEN]", move.l10n_py_edi_errors)

    def test_contract_processing_reference(self):
        connector = self._connector()
        if not connector.supports("async"):
            self.skipTest("proveedor síncrono")
        if self._arrange("processing") is False:
            self.skipTest("sin escenario processing")
        move = self._create_invoice()
        move.action_send_edi()
        self.assertEqual(move.l10n_py_edi_status, "processing")
        self.assertTrue(
            move.l10n_py_cdc or move.l10n_py_edi_batch_id, "referencia para consultar"
        )
        self.assertFalse(move.l10n_py_edi_errors)

    # ---------------------------------------------------------- eventos
    def _accepted_move(self):
        move = self._create_invoice()
        self.assertTrue(self._send_expecting(move, "accepted"))
        self.assertEqual(move.l10n_py_edi_status, "accepted")
        return move

    def test_contract_cancel(self):
        connector = self._connector()
        if not connector.supports("cancel"):
            self.skipTest("sin cancelación")
        move = self._accepted_move()
        if self._arrange("cancel_accepted") is False:
            self.skipTest("sin escenario cancel_accepted")
        event = move.action_cancel_edi("Datos del receptor erróneos")
        self.assertEqual(move.l10n_py_edi_status, "cancelled")
        self.assertEqual((event.event_type, event.state), ("cancel", "accepted"))
        move2 = self._accepted_move()
        if self._arrange("cancel_rejected") is False:
            return
        error = ""
        try:
            move2.action_cancel_edi("Fuera de plazo")
        except UserError as e:
            error = str(e)
        self.assertTrue(error, "la cancelación rechazada debe levantar UserError")
        self.assertEqual(move2.l10n_py_edi_status, "accepted")
        self.assertIn("[SIFEN]", move2.l10n_py_edi_errors)

    def test_contract_inutilization(self):
        connector = self._connector()
        if not connector.supports("inutilization"):
            self.skipTest("sin inutilización")
        if self._arrange("inutilization_accepted") is False:
            self.skipTest("sin escenario inutilization_accepted")
        result = connector.inutilize_range(
            {
                "timbrado": self.authorization.name,
                "establecimiento": "001",
                "punto": "001",
                "numeroDesde": "0000100",
                "numeroHasta": "0000102",
                "tipoDocumento": 1,
                "motivo": "Salto de numeración",
            }
        )
        self.assertEqual(result["status"], "accepted")
        self.assertTrue(result["success"])

    def test_contract_ruc_query(self):
        connector = self._connector()
        if not connector.supports("ruc_query"):
            self.skipTest("sin consulta de RUC")
        if self._arrange("ruc_query") is False:
            self.skipTest("sin escenario ruc_query")
        info = connector.query_ruc(self.company.l10n_py_ruc)
        self.assertEqual(info["ruc"][:8], self.company.l10n_py_ruc)
        self.assertTrue(info["name"])
        self.assertTrue(info["status"])

# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
"""Grabación y reproducción de respuestas de proveedores (homologación)."""

import json
import os
import tempfile
from unittest import mock

from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import L10nPyEdiCommon


class FakeResponse:
    def __init__(self, status_code=200, json_body=None, content=b""):
        self.status_code = status_code
        self._json = json_body
        self.content = content if json_body is None else json.dumps(json_body).encode()
        self.text = self.content.decode(errors="ignore")

    def json(self):
        if self._json is None:
            raise ValueError("no json")
        return self._json


@tagged("post_install", "-at_install", "l10n_py")
class TestFixtureReplay(L10nPyEdiCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Connector = cls.env["l10n_py.edi.connector"]
        field = cls.Connector._fields["provider_type"]
        original = field.selection
        field.selection = list(original) + [("mock", "Mock")]
        cls.addClassCleanup(setattr, field, "selection", original)
        if hasattr(field, "_selection"):
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
        cls.tmp = tempfile.mkdtemp(prefix="l10n_py_fixtures_")
        cls.icp = cls.env["ir.config_parameter"].sudo()

    def tearDown(self):
        self.icp.set_param("l10n_py.edi.record_dir", "")
        self.icp.set_param("l10n_py.edi.replay_dir", "")
        self.Connector._l10n_py_reset_replay()
        super().tearDown()

    def _call(self, payload):
        return self.connector._l10n_py_rest_request(
            "POST",
            "https://api.example.com/send",
            "send",
            "MK",
            json=payload,
            headers={"Authorization": "Bearer secret", "Accept": "application/json"},
        )

    def test_record_then_replay(self):
        self.icp.set_param("l10n_py.edi.record_dir", self.tmp)
        with mock.patch(
            "requests.request",
            return_value=FakeResponse(202, {"cdc": "1" * 44, "estado": "PENDIENTE"}),
        ):
            code, body = self._call(
                {"api_key": "k", "cliente": {"token": "t", "ruc": "80028061"}}
            )
        self.assertEqual((code, body["estado"]), (202, "PENDIENTE"))
        folder = os.path.join(self.tmp, "mock", "send")
        files = sorted(os.listdir(folder))
        self.assertEqual(len(files), 1)
        with open(os.path.join(folder, files[0]), encoding="utf-8") as fh:
            fixture = json.load(fh)
        # credenciales redactadas, datos de negocio intactos
        self.assertEqual(fixture["request"]["headers"]["Authorization"], "***")
        self.assertEqual(fixture["request"]["json"]["api_key"], "***")
        self.assertEqual(fixture["request"]["json"]["cliente"]["token"], "***")
        self.assertEqual(fixture["request"]["json"]["cliente"]["ruc"], "80028061")
        self.assertEqual(
            (fixture["status_code"], fixture["body"]["cdc"]), (202, "1" * 44)
        )

        # reproducción: sin red, misma respuesta; luego se agotan
        self.icp.set_param("l10n_py.edi.record_dir", "")
        self.icp.set_param("l10n_py.edi.replay_dir", self.tmp)
        with mock.patch(
            "requests.request", side_effect=AssertionError("no debe llamar a la red")
        ):
            code, body = self._call({"cliente": {"ruc": "80028061"}})
            self.assertEqual(
                (code, body), (202, {"cdc": "1" * 44, "estado": "PENDIENTE"})
            )
            with self.assertRaisesRegex(UserError, "agotaron"):
                self._call({})
            with self.assertRaisesRegex(UserError, "no hay grabaciones"):
                self.connector._l10n_py_rest_request("GET", "https://x", "status", "MK")
        log = self.env["l10n_py.edi.log"].search(
            [("provider", "=", "mock")], order="id desc", limit=1
        )
        self.assertTrue(log.success)

    def test_xml_bodies_roundtrip(self):
        self.icp.set_param("l10n_py.edi.record_dir", self.tmp + "_xml")
        xml = b'<?xml version="1.0"?><env:Envelope xmlns:env="x"><ok/></env:Envelope>'
        with mock.patch(
            "requests.request", return_value=FakeResponse(200, content=xml)
        ):
            code, body = self.connector._l10n_py_rest_request(
                "POST",
                "https://api.example.com/soap",
                "send",
                "MK",
                data=b"<rEnviDe/>",
                expect_json=False,
            )
        self.assertEqual(body, xml)
        self.icp.set_param("l10n_py.edi.record_dir", "")
        self.icp.set_param("l10n_py.edi.replay_dir", self.tmp + "_xml")
        code, body = self.connector._l10n_py_rest_request(
            "POST", "https://api.example.com/soap", "send", "MK"
        )
        self.assertEqual(body, xml)

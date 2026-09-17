# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
"""Carga de los datos de demostración de ``l10n_py_edi_base``.

Los documentos demo (NCE, NDE, NRE, AFE, asociados, inutilización) parten de
las facturas demo de ``l10n_py_account``, que solo existen si su
``post_init_hook`` pudo instalar el plan de cuentas paraguayo en la empresa
principal (no ocurre cuando otro módulo con demo, p. ej. ``point_of_sale``,
ya generó asientos). Por eso se cargan aquí, en el ``post_init_hook`` y solo
si existen.
"""

import logging

from odoo.tools import convert_file

_logger = logging.getLogger(__name__)

DEMO_FILES = (
    "demo/res_company_edi_demo.xml",
    "demo/account_move_nce_demo.xml",
    "demo/account_move_nde_demo.xml",
    "demo/account_move_nre_demo.xml",
    "demo/account_move_afe_demo.xml",
    "demo/l10n_py_associated_document_demo.xml",
    "demo/l10n_py_number_inutilization_demo.xml",
)


def post_init_hook(env):
    module = env["ir.module.module"].search(
        [("name", "=", "l10n_py_edi_base")], limit=1
    )
    if not module.demo:
        return
    if not env.ref("l10n_py_account.demo_invoice_fe_iva10", raise_if_not_found=False):
        _logger.info(
            "l10n_py_edi_base: sin facturas demo de l10n_py_account; "
            "no se cargan los documentos electrónicos demo"
        )
        return
    for fname in DEMO_FILES:
        _logger.info("l10n_py_edi_base: cargando demo %s", fname)
        convert_file(
            env, "l10n_py_edi_base", fname, {}, mode="init", noupdate=True, kind="demo"
        )

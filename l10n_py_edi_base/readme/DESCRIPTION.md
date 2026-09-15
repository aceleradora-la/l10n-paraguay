# Paraguay - Electronic Invoicing Base

Base module for electronic invoicing (SIFEN / e-Kuatia, DNIT) in Paraguay.
It knows **what** has to be sent (the canonical document, validated) and
delegates **how** it is sent to a connector module: direct SOAP transmission
to the DNIT web services or a REST intermediary. The user interface, the
document states and the reports are the same whatever the connector.

## Features

- Document types: Factura, Nota de Crédito, Nota de Débito, Nota de Remisión
  and Autofactura electrónica (`iTiDE` 1, 5, 6, 7, 4).
- Canonical document builder (`account.move._prepare_edi_document_data()`):
  a JSON-like dict mirroring the SIFEN XSD groups, shared by every connector.
- VAT breakdown driven by `account.tax` (`l10n_py_iva_affectation`,
  `l10n_py_iva_rate`, `l10n_py_taxable_proportion`): taxed, exonerated,
  exempt and partially taxed items; discounts; single rounding point
  (`_l10n_py_round()`, guaraní without decimals).
- Connector interface (`l10n_py.edi.connector`) with capabilities
  (`batch`, `async`, `events`, `pdf`, `ruc_query`, `contingency`, `preview`)
  and a **normalised result contract**: `status`
  (`accepted`, `accepted_obs`, `processing`, `rejected`, `error`), documents
  (`cdc`, `qr`, `xml`, `pdf`, `protocol`, `approval_date`, `digest`), errors
  `(code, message, source)` where `source` tells SIFEN rejections apart from
  intermediary/transport failures, and `retryable`.
- State machine on the invoice: `to_send → sent → accepted/accepted_obs/
  rejected/error`, `processing` with polling (`check_status`, cron),
  `to_cancel → cancelled`. Approved documents cannot be reset to draft and
  their XML is immutable.
- Cancellation event with the legal deadline counted from the SIFEN approval
  (48 h FE/AFE, 168 h NCE/NDE/NRE), number range inutilization, contingency
  flag with automatic re-transmission.
- CDC (44 digits, modulo 11), QR link (`cHashQR` with the CSC), KuDE report,
  operation log, associated documents (group H), transport data (group G).

## Connectors

- `l10n_py_edi_sifen`: direct SIFEN transmission (this repository).
- Other connectors (FacturaSend, direct with `signxml`, a dummy provider for
  tests) live in <https://github.com/aceleradora-la/odoo-paraguay>.

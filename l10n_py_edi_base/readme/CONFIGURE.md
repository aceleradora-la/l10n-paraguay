# Configuration

1. **Company**: RUC (without check digit), trade name, economic activity,
   SET department/district/city codes.
2. **Connector** (*Facturación Electrónica > Configuración > Conectores*, group
   *EDI Paraguay / Responsable*): one connector per company; choose the
   provider (`provider_type`), the environment (test / production) and the
   credentials the provider module adds to the *Credenciales* group.
3. **Timbrado** (`account.authorization`) and **journal**: establishment,
   expedition point and timbrado on each electronic sales journal
   (`l10n_latam_use_documents` enabled).
4. **Taxes**: check the SIFEN tab of each tax (`Afectación tributaria IVA`,
   `Tasa IVA`, `Proporción gravada`). Defaults are derived from the percentage
   (10 % / 5 % taxed, 0 % exempt); set *Exonerado* or *Gravado parcial*
   explicitly.
5. **Products**: NCM code and SET unit of measure code (`l10n_py_unit_code`,
   77 = unit).
6. **Partners**: taxpayer type, RUC or identity document, address.

## System parameters

| Key | Default | Meaning |
|---|---|---|
| `l10n_py.mt_version` | `150` | SIFEN technical manual version supported |
| `l10n_py.transmission_hours` | `72` | Transmission deadline from issue date |
| `l10n_py.contingency_hours` | `72` | Deadline to transmit contingency documents (not fixed by MT v150) |
| `l10n_py.cron_batch_size` | `50` | Documents processed per cron run |

## Security groups

- *EDI Paraguay / Usuario*: send, check status, cancel, inutilize.
- *EDI Paraguay / Responsable*: configure connectors, credentials and
  timbrados. Credentials are only visible to this group.

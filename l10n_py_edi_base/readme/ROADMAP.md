# Roadmap

- Numbering through `l10n_latam_invoice_document` sequences instead of the
  `MAX()` per timbrado in `l10n_py_account`.
- Receiver events (conformidad, disconformidad, desconocimiento,
  notificación) and nomination in the base state machine.
- Demo/test data independent from the `account` demo (explicit chart
  loading in `tests/common.py`).
- Drop `l10n_py.edi.document.type` in favour of `l10n_latam.document.type`.
- Decide between the QWeb KuDE and `pykude`.

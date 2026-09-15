# Usage

## Sending

1. Confirm the invoice: the EDI state becomes *Para Enviar*.
2. Click **Enviar a EDI** (single document) or select several invoices and
   use the same action: documents are validated (all errors are reported at
   once) and sent, in batch when the provider supports it.
3. The result updates the invoice: CDC, QR, signed XML (an immutable
   attachment), protocol, approval date and, when available, the KuDE.

| EDI state | Meaning |
|---|---|
| Para Enviar | Confirmed, not sent yet |
| Enviado | Sent, waiting for a synchronous answer |
| Procesando | Queued by the provider/SIFEN; **Consultar estado** or the cron polls it |
| Aceptado / Aceptado con observación | Approved by SIFEN (observations in *Errores EDI*) |
| Rechazado | Rejected by SIFEN or the provider: fix the data and **Reintentar** (same number) |
| Error | Transport failure, retryable |
| Cancelación en proceso / Cancelado | Cancellation event sent / accepted |

*Errores EDI* lists every error as `[SIFEN] code: message` or
`[Proveedor] code: message`, so a DNIT rejection is never confused with an
intermediary outage.

## Cancelling

**Cancelar EDI** opens a wizard showing the legal deadline (48 h for FE/AFE,
168 h for NCE/NDE/NRE, counted from the SIFEN approval) and sends the
cancellation event. Approved documents cannot be reset to draft or cancelled
through the standard accounting flow.

## Inutilization and contingency

- *Facturación Electrónica > Inutilización de números* declares unused
  number ranges of a timbrado.
- Documents issued with *Tipo de emisión = Contingencia* are queued and
  re-transmitted by the cron *Verificar Estado EDI*.

## Cron

*Verificar Estado EDI* (hourly) re-sends pending contingency documents and
applies the provider answer to documents in *Enviado*, *Procesando* or
*Cancelación en proceso*, `l10n_py.cron_batch_size` at a time.

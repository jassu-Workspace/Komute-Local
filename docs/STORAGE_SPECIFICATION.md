# Storage

Code: `storage/` (blob store, encryption, retention) and `backend/core/audit.py`, `idempotency.py`. The engine talks only to the `BlobStore` interface (`put`, `get`, `exists`, `delete_prefix`, `list_prefix`). `storage/` imports nothing from `backend/`.

## Layout (all files encrypted)

```text
sessions/{driver_id}/{request_id}/
  started.json            written first; lets the sweeper age an unfinished session
  originals/{selfie,licence_front,licence_back,vehicle}.{jpg,png,webp}   the uploaded bytes
  cropped/{selfie_face,licence_face,plate}.webp
  compressed/{selfie,licence_front,licence_back,vehicle}.webp           long side at most 1280 px
  record.json             decision, reasons, scores, claimed data, barcode fields, consent
  manifest.json           written LAST: SHA-256 of every file, record hash, key id, HMAC-SHA256 signature
requests/{request_id}.json   idempotency entry: payload hash and the stored response
```

A session without `manifest.json` is incomplete. Readers ignore it, and the sweeper deletes it after 1 hour.

## Encryption and integrity

- AES-256-GCM per file. Format: `KMT1`, key-id length, key id, 12-byte random nonce, ciphertext. The file's storage key is the authenticated data, so a ciphertext copied to another path fails to decrypt.
- Writes go to `<file>.tmp`, are flushed and fsynced, then renamed. The parent directory is fsynced on POSIX. A crash never leaves a half file under its real name.
- Every path segment must survive `sanitize_folder_name` unchanged, may not end in `.tmp`, and the resolved path must stay inside the root.
- The data key and the manifest signing key come from the host (environment variable or sidecar) as 32-byte base64. The module never generates keys. Key ids are recorded so keys can rotate.
- `verify_session` recomputes the signature and every hash and reports what is missing or changed.

## Retention (in-process sweeper: at startup and every hour)

| Session | After | Deleted |
|---|---|---|
| Rejected | 72 hours | all images (originals, crops, compressed). `record.json` and `manifest.json` stay |
| Approved | 30 days | originals. Crops and compressed images stay |
| Incomplete | 1 hour | everything |

The approved manifest is kept for the driver's tenure plus 7 years through the host's lifecycle rules. `delete_prefix` removes crash-left `.tmp` files and fails loudly if anything survives.

## Idempotency

Same `request_id` and same payload hash returns the stored response without running again. A different payload returns `409`. The payload hash covers every form field and every image.

## Not done

Application-level encryption protects data on disk. TLS is the host's proxy job. There is no S3 implementation yet, only the local one.

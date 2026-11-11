# Test page

`backend/static/index.html`, served at `GET /`, is one file with inline CSS and script, no framework and no external requests. It is for testing the module, not a product UI: the host application owns the real interface.

It has: an API key box (kept in `sessionStorage`, guarded for blocked storage), the request and consent fields, the claimed details (province is a 13-code list), four photo inputs (selfie, licence front, licence back, vehicle), a Verify button, and a result panel with the decision, each reason's message (tagged "retake" when retryable, "final" otherwise), advisories, timings and the raw JSON.

All text is set with `textContent`, every input has a label, and the layout works at 360 px width. The field names match the API exactly (`claimed.full_name`, `selfie`, and so on), and a test checks them.

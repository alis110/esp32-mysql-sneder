#pragma once

// Copy this file to secrets.h. Never commit the real secrets.h.
#define WIFI_SSID "REPLACE_WITH_WIFI_SSID"
#define WIFI_PASSWORD "REPLACE_WITH_WIFI_PASSWORD"
#define API_URL "https://example.com/api/plc-records"
#define API_TOKEN "REPLACE_WITH_API_TOKEN"

// true = skip certificate check (lab only). false = require ROOT_CA below.
#define ALLOW_INSECURE_TLS false

#if !ALLOW_INSECURE_TLS
// Paste the issuing CA certificate in PEM format.
static const char ROOT_CA[] = R"PEM(
-----BEGIN CERTIFICATE-----
REPLACE_WITH_CA_CERTIFICATE
-----END CERTIFICATE-----
)PEM";
#endif

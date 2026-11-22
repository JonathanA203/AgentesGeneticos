-- Servidor XMPP local para pruebas con SPADE (NO usar en producción)
admins = { }

modules_enabled = {
    "roster"; "saslauth"; "tls"; "dialback"; "disco";
    "carbons"; "pep"; "private"; "blocklist"; "vcard4"; "vcard_legacy";
    "version"; "uptime"; "time"; "ping"; "register"; "admin_adhoc";
}

allow_registration = true
-- Aceptar autenticación sin cifrado en local
c2s_require_encryption = false
allow_unencrypted_plain_auth = true
authentication = "internal_plain"
storage = "internal"

log = { { levels = { min = "info" }, to = "console" } }

VirtualHost "localhost"

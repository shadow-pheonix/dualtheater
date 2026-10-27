# Connection setup

Start the Windows host, open the TV app and select the laptop's name. Enter its six-digit code once. The code is shown in the terminal and at **http://localhost:8764**. Paired TVs reconnect automatically when they discover that laptop again.

The remembered-laptop shortcut uses the last known address if discovery is blocked. **Advanced connection** exposes manual fields for troubleshooting and older clients. Both the host and companion should come from the same beta release.

Discovery uses UDP 8767. Control uses TCP 8766, media TCP 8765 and the local browser controller TCP 8764. These are application ports, not a request to open router forwarding. Use a trusted local network; guest-client isolation, VPN routing and firewall rules can block discovery or playback.

The TV probes interface broadcast addresses, and the host replies by unicast with only a stable ID, name and control port. A per-discovery random nonce validates the reply. Credentials and pairing codes are not advertised.

The host stores its stable identity and remembered per-TV tokens in `pairings.json`. The TV stores its remembered credential in private app preferences. Preserve the host file when updating in place; never publish it. A changed short code after restart does not invalidate an existing remembered token. If the token is missing or invalid, enter the current short code again.

Incorrect short-code attempts are limited. A corrupt pairing file is reported rather than silently overwritten. Authentication and streaming retain the beta's cleartext trusted-LAN design; they are not Internet-safe services.

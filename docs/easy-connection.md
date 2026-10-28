# Connection setup

The unreleased `0.5.0-beta.2` preview also supports a separate paired phone calibration role on the same control port, alongside the TV socket. The phone uses the displayed six-digit code and receives its own remembered credential. See [phone calibration setup](phone-calibration.md); published `0.4.1-beta.1` builds do not contain this feature.

In the Windows desktop EXE, click **Download mpv** on **Connect** (or **Browse…** for an existing build), wait for automatic selection and choose the HDMI audio device, then click **Start TV connection**. The setup is remembered; later launches start the connection when the saved endpoint is still available. Open the TV app and select the computer's name. Enter its six-digit code once; the code appears on Connect. Paired TVs can reconnect automatically when they discover that computer again. The app switches to Player after connection; choose a movie and click Load movie, then Play.

The optional command-line host shows the same code in its terminal and browser controller at **http://localhost:8764**. The browser is not required for the desktop EXE. Only run one host instance on the default ports.

The remembered-laptop shortcut uses the last known address if discovery is blocked. **Advanced connection** exposes manual fields for troubleshooting and older clients. Both the host and companion should come from the same beta release.

Discovery uses UDP 8767. Control uses TCP 8766, media TCP 8765 and the local browser controller TCP 8764. These are application ports, not a request to open router forwarding. Use a trusted local network; guest-client isolation, VPN routing and firewall rules can block discovery or playback.

The TV probes interface broadcast addresses, and the host replies by unicast with only a stable ID, name and control port. A per-discovery random nonce validates the reply. Credentials and pairing codes are not advertised.

The host stores its stable identity and remembered per-TV tokens in `pairings.json`. The desktop stores this and calibration under `%LOCALAPPDATA%\DualTheater`; the source CLI defaults to its source directory. The TV stores its remembered credential in private app preferences. Preserve the host file when updating in place; never publish it. Switching from the old CLI state directory to the EXE can require first-time app pairing again. A changed short code after restart does not invalidate an existing remembered token. If the token is missing or invalid, enter the current short code again.

After a lost connection, reconnect the TV and reload the movie before resuming. The desktop disables transport until reloading succeeds. Disconnecting from Connect stops the host/audio path so audio settings can be changed safely; start, reconnect and reload afterward.

Incorrect short-code attempts are limited. A corrupt pairing file is reported rather than silently overwritten. Authentication and streaming retain the beta's cleartext trusted-LAN design; they are not Internet-safe services.

package dev.dualtheater.calibration;

import java.net.*;
import java.nio.charset.StandardCharsets;
import java.util.*;
import org.json.JSONObject;

final class Discovery implements AutoCloseable {
    interface Listener { void found(String id, String name, String address, int port); }
    private final Listener listener;
    private volatile boolean closed;
    private volatile DatagramSocket socket;
    Discovery(Listener listener) { this.listener = listener; }
    void start() {
        new Thread(() -> {
            try (DatagramSocket udp = new DatagramSocket()) {
                socket = udp; udp.setBroadcast(true); udp.setSoTimeout(300);
                String nonce = UUID.randomUUID().toString().replace("-", "");
                byte[] probe = new JSONObject().put("op", "dualtheater.discover").put("version", 1)
                    .put("nonce", nonce).toString().getBytes(StandardCharsets.UTF_8);
                Set<InetAddress> targets = new LinkedHashSet<>();
                targets.add(InetAddress.getByName("255.255.255.255"));
                Enumeration<NetworkInterface> networks = NetworkInterface.getNetworkInterfaces();
                while (networks != null && networks.hasMoreElements()) {
                    NetworkInterface network = networks.nextElement();
                    if (network.isUp() && !network.isLoopback()) for (InterfaceAddress address : network.getInterfaceAddresses())
                        if (address.getBroadcast() != null) targets.add(address.getBroadcast());
                }
                long next = 0;
                while (!closed) {
                    if (System.nanoTime() > next) {
                        for (InetAddress address : targets) try { udp.send(new DatagramPacket(probe, probe.length, address, 8767)); }
                        catch (Exception ignored) {}
                        next = System.nanoTime() + 1_500_000_000L;
                    }
                    DatagramPacket packet = new DatagramPacket(new byte[2048], 2048);
                    try { udp.receive(packet); } catch (SocketTimeoutException timeout) { continue; }
                    try {
                        JSONObject value = new JSONObject(new String(packet.getData(), 0, packet.getLength(), StandardCharsets.UTF_8));
                        if (!value.optString("op").equals("dualtheater.host") || value.optInt("version") != 1
                            || !nonce.equals(value.optString("nonce")) || !(packet.getAddress() instanceof Inet4Address)) continue;
                        String id = UUID.fromString(value.getString("host_id")).toString();
                        int port = value.getInt("control_port");
                        if (port < 1 || port > 65535) continue;
                        String name = value.optString("name", "Computer").replaceAll("[\\p{Cntrl}]", "");
                        listener.found(id, name.substring(0, Math.min(48, name.length())), packet.getAddress().getHostAddress(), port);
                    } catch (Exception ignored) {}
                }
            } catch (Exception ignored) { /* Manual LAN address remains available. */ }
        }, "calibration-discovery").start();
    }
    @Override public void close() { closed = true; if (socket != null) socket.close(); }
}

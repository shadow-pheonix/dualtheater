package dev.dualtheater.tv;

import java.net.*;
import java.nio.charset.StandardCharsets;
import java.util.*;
import org.json.JSONObject;

/** Broadcast only a random probe. Replies and all subsequent pairing are unicast. */
final class HostDiscovery implements AutoCloseable {
    interface Listener { void onFound(DiscoveredHost host); void onError(String message); }
    private final Listener listener;
    private volatile boolean closed;
    private volatile DatagramSocket socket;
    HostDiscovery(Listener listener) { this.listener = listener; }

    void start() {
        Thread worker = new Thread(() -> {
            try (DatagramSocket udp = new DatagramSocket()) {
                socket = udp;
                udp.setBroadcast(true); udp.setSoTimeout(350);
                String nonce = UUID.randomUUID().toString().replace("-", "");
                byte[] query = new JSONObject().put("op", "dualtheater.discover").put("version", 1)
                    .put("nonce", nonce).toString().getBytes(StandardCharsets.UTF_8);
                Set<InetAddress> broadcasts = new LinkedHashSet<>();
                broadcasts.add(InetAddress.getByName("255.255.255.255"));
                Enumeration<NetworkInterface> interfaces = NetworkInterface.getNetworkInterfaces();
                while (interfaces != null && interfaces.hasMoreElements()) {
                    NetworkInterface nic = interfaces.nextElement();
                    if (!nic.isUp() || nic.isLoopback()) continue;
                    for (InterfaceAddress entry : nic.getInterfaceAddresses()) {
                        if (entry.getBroadcast() != null) broadcasts.add(entry.getBroadcast());
                    }
                }
                long nextProbe = 0;
                while (!closed) {
                    long now = System.nanoTime();
                    if (now >= nextProbe) {
                        for (InetAddress address : broadcasts) {
                            try { udp.send(new DatagramPacket(query, query.length, address, 8767)); }
                            catch (java.io.IOException ignored) {}
                        }
                        nextProbe = now + 1_500_000_000L;
                    }
                    DatagramPacket packet = new DatagramPacket(new byte[2048], 2048);
                    try { udp.receive(packet); } catch (SocketTimeoutException e) { continue; }
                    try {
                        JSONObject reply = new JSONObject(new String(packet.getData(), 0, packet.getLength(), StandardCharsets.UTF_8));
                        if (!reply.optString("op").equals("dualtheater.host") || reply.optInt("version") != 1
                            || !nonce.equals(reply.optString("nonce")) || !(packet.getAddress() instanceof Inet4Address)) continue;
                        listener.onFound(new DiscoveredHost(reply.getString("host_id"), reply.optString("name"),
                            packet.getAddress().getHostAddress(), reply.getInt("control_port")));
                    } catch (Exception ignored) {}
                }
            } catch (Exception e) {
                if (!closed) listener.onError("Laptop discovery is unavailable. Try Reconnect or Advanced connection.");
            }
        }, "dualtheater-discovery");
        worker.setDaemon(true); worker.start();
    }

    @Override public void close() { closed = true; if (socket != null) socket.close(); }
}

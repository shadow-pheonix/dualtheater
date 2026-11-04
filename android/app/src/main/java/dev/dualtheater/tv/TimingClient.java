package dev.dualtheater.tv;

import java.io.*;
import java.net.*;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import android.util.Log;
import org.json.JSONObject;

/** Dedicated, session-authorized timing stream. No player calls on this thread. */
final class TimingClient implements AutoCloseable {
    private final Object lifecycle = new Object();
    private volatile Socket socket;
    private volatile DatagramSocket datagram;
    private volatile boolean closed;
    private final CountDownLatch cancelled = new CountDownLatch(1);
    void connect(String host, int port, String token, RemoteTimeline timeline, Runnable ready, Runnable failed) {
        connect(host, port, token, timeline, ready, failed, false);
    }
    void connect(String host, int port, String token, RemoteTimeline timeline, Runnable ready, Runnable failed,
                 boolean useDatagrams) {
        connect(host, port, token, timeline, ready, failed, useDatagrams, 0);
    }
    void connect(String host, int port, String token, RemoteTimeline timeline, Runnable ready, Runnable failed,
                 boolean useDatagrams, int fallbackTcpPort) {
        if (useDatagrams) {
            connectDatagrams(host, port, token, timeline, ready, failed, fallbackTcpPort); return;
        }
        new Thread(() -> {
            long retryMs = 250;
            while (!closed) {
                Socket s = new Socket();
                try {
                    synchronized (lifecycle) {
                        if (closed) break;
                        socket = s;
                    }
                    s.connect(new InetSocketAddress(host, port), 3000);
                    s.setTcpNoDelay(true); s.setSoTimeout(3000);
                    BufferedWriter out = new BufferedWriter(new OutputStreamWriter(s.getOutputStream(), StandardCharsets.UTF_8));
                    BufferedReader in = new BufferedReader(new InputStreamReader(s.getInputStream(), StandardCharsets.UTF_8));
                    out.write(new JSONObject().put("op", "hello").put("version", 1)
                        .put("role", "timing").put("token", token).toString()); out.newLine(); out.flush();
                    while (!closed) {
                        StringBuilder line = new StringBuilder(); int c;
                        while ((c = in.read()) != -1 && c != '\n') {
                            if (line.length() >= 4096) throw new IOException("Oversized timing message");
                            line.append((char)c);
                        }
                        if (c == -1) throw new EOFException();
                        long received = System.nanoTime();
                        JSONObject msg = new JSONObject(line.toString());
                        if ("ping".equals(msg.optString("op"))) {
                            JSONObject reply = new JSONObject().put("op", "pong").put("t0", msg.getLong("t0"))
                                .put("t1", received);
                            reply.put("t2", System.nanoTime()); // immediately before the write, no output queue
                            out.write(reply.toString()); out.newLine(); out.flush();
                        } else if ("anchor".equals(msg.optString("op"))) {
                            timeline.accept(msg.getLong("epoch"), msg.getLong("sequence"), msg.getLong("local_ns"),
                                Math.round(msg.getDouble("position_ms") * 1000), msg.getDouble("rate"),
                                msg.getDouble("uncertainty_ms"), received);
                        } else if ("timing_ready".equals(msg.optString("op"))) {
                            if (msg.optInt("version") != 2) throw new IOException("Unsupported timing protocol");
                            retryMs = 250; ready.run();
                        } else throw new IOException("Unknown timing operation");
                    }
                } catch (Exception e) {
                    if (!closed) {
                        Log.w("DTTransport", "Timing disconnected: " + e.getClass().getSimpleName());
                        failed.run();
                    }
                } finally {
                    try { s.close(); } catch (IOException ignored) {}
                    if (socket == s) socket = null;
                }
                try { if (cancelled.await(retryMs, TimeUnit.MILLISECONDS)) break; }
                catch (InterruptedException e) { Thread.currentThread().interrupt(); break; }
                retryMs = Math.min(3000, retryMs * 2);
            }
        }, "dualtheater-timing").start();
    }

    private void connectDatagrams(String host, int port, String token, RemoteTimeline timeline,
                                  Runnable ready, Runnable failed, int fallbackTcpPort) {
        new Thread(() -> {
            long retryMs = 250;
            while (!closed) {
                DatagramSocket s = null;
                boolean acknowledged = false, fallback = false;
                try {
                    s = new DatagramSocket();
                    synchronized (lifecycle) {
                        if (closed) break;
                        datagram = s;
                    }
                    s.connect(InetAddress.getByName(host), port);
                    s.setSoTimeout(250);
                    byte[] buffer = new byte[2049];
                    long deadline = System.nanoTime() + 2_500_000_000L, nextHello = 0;
                    while (!closed) {
                        // Check independently of receive timeouts: malformed or
                        // unauthenticated traffic must not extend negotiation.
                        if (!acknowledged && fallbackTcpPort > 0 && System.nanoTime() >= deadline) {
                            fallback = true; break;
                        }
                        if (!acknowledged && System.nanoTime() >= nextHello) {
                            sendDatagram(s, new JSONObject().put("op", "hello").put("version", 3).put("token", token));
                            nextHello = System.nanoTime() + 250_000_000L;
                        }
                        DatagramPacket packet = new DatagramPacket(buffer, buffer.length);
                        try { s.receive(packet); }
                        catch (SocketTimeoutException timeout) {
                            if (acknowledged) throw timeout;
                            continue;
                        }
                        long received = System.nanoTime();
                        if (packet.getLength() > 2048) continue;
                        JSONObject msg;
                        try { msg = new JSONObject(new String(packet.getData(), packet.getOffset(),
                                packet.getLength(), StandardCharsets.UTF_8)); }
                        catch (org.json.JSONException malformed) { continue; }
                        if (!java.security.MessageDigest.isEqual(token.getBytes(StandardCharsets.UTF_8),
                                msg.optString("token").getBytes(StandardCharsets.UTF_8))) continue;
                        String op = msg.optString("op");
                        if ("ping".equals(op)) {
                            JSONObject reply = new JSONObject().put("op", "pong").put("token", token)
                                .put("t0", msg.getLong("t0")).put("t1", received);
                            reply.put("t2", System.nanoTime());
                            sendDatagram(s, reply);
                            // A valid session-bound ping proves that the host
                            // adopted UDP even if its explicit READY was lost.
                            if (!acknowledged) {
                                acknowledged = true; s.setSoTimeout(3000); retryMs = 250; ready.run();
                            }
                        } else if ("anchor".equals(op) && acknowledged) {
                            timeline.accept(msg.getLong("epoch"), msg.getLong("sequence"), msg.getLong("local_ns"),
                                Math.round(msg.getDouble("position_ms") * 1000), msg.getDouble("rate"),
                                msg.getDouble("uncertainty_ms"), received);
                        } else if ("timing_ready".equals(op) && msg.optInt("version") == 3 && !acknowledged) {
                            acknowledged = true; s.setSoTimeout(3000); retryMs = 250; ready.run();
                        }
                    }
                } catch (Exception error) {
                    if (!closed) {
                        if (!acknowledged && fallbackTcpPort > 0) fallback = true;
                        else {
                            Log.w("DTTransport", "UDP timing disconnected: " + error.getClass().getSimpleName());
                            failed.run();
                        }
                    }
                } finally {
                    if (s != null) s.close();
                    if (datagram == s) datagram = null;
                }
                if (fallback && !closed) {
                    // Only setup switches transport. Established-link loss still
                    // reports failure; the coordinator owns pause/recovery.
                    connect(host, fallbackTcpPort, token, timeline, ready, failed, false);
                    return;
                }
                try { if (cancelled.await(retryMs, TimeUnit.MILLISECONDS)) break; }
                catch (InterruptedException error) { Thread.currentThread().interrupt(); break; }
                retryMs = Math.min(3000, retryMs * 2);
            }
        }, "dualtheater-timing-udp").start();
    }

    private static void sendDatagram(DatagramSocket socket, JSONObject message) throws IOException {
        byte[] payload = message.toString().getBytes(StandardCharsets.UTF_8);
        if (payload.length > 2048) throw new IOException("Oversized timing datagram");
        socket.send(new DatagramPacket(payload, payload.length));
    }
    @Override public void close() {
        synchronized (lifecycle) {
            closed = true;
            cancelled.countDown();
            Socket s = socket;
            try { if (s != null) s.close(); } catch (IOException ignored) {}
            DatagramSocket d = datagram;
            if (d != null) d.close();
        }
    }
}

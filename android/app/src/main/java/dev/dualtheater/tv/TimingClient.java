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
    private volatile Socket socket;
    private volatile boolean closed;
    private final CountDownLatch cancelled = new CountDownLatch(1);
    void connect(String host, int port, String token, RemoteTimeline timeline, Runnable ready, Runnable failed) {
        new Thread(() -> {
            long retryMs = 250;
            while (!closed) {
                Socket s = new Socket(); socket = s;
                try {
                    if (closed) break;
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
    @Override public void close() {
        closed = true;
        cancelled.countDown();
        Socket s = socket;
        try { if (s != null) s.close(); } catch (IOException ignored) {}
    }
}

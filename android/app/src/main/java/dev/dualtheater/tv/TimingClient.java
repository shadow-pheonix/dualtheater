package dev.dualtheater.tv;

import java.io.*;
import java.net.*;
import java.nio.charset.StandardCharsets;
import org.json.JSONObject;

/** Dedicated, session-authorized timing stream. No player calls on this thread. */
final class TimingClient implements AutoCloseable {
    private volatile Socket socket;
    private volatile boolean closed;
    void connect(String host, int port, String token, RemoteTimeline timeline, Runnable failed) {
        new Thread(() -> {
            try {
                Socket s = new Socket(); socket = s;
                s.connect(new InetSocketAddress(host, port), 3000);
                s.setTcpNoDelay(true); s.setSoTimeout(1500);
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
                    } else if (!"timing_ready".equals(msg.optString("op"))) throw new IOException("Unknown timing operation");
                }
            } catch (Exception e) { if (!closed) failed.run(); }
            finally { close(); }
        }, "dualtheater-timing").start();
    }
    @Override public void close() {
        closed = true;
        try { if (socket != null) socket.close(); } catch (IOException ignored) {}
    }
}

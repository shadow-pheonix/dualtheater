package dev.dualtheater.tv;

import org.json.JSONObject;
import java.io.*;
import java.net.*;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicBoolean;

/** One authenticated connection. Bounded output; no silent replay after disconnect. */
final class ControlClient implements AutoCloseable {
    interface Listener {
        void onMessage(JSONObject message);
        void onDisconnected(String reason);
    }
    private final Listener listener;
    private final BlockingQueue<String> outbound = new ArrayBlockingQueue<>(64);
    private final AtomicBoolean closed = new AtomicBoolean(false);
    private volatile Socket socket;
    private Thread readerThread, writerThread;

    ControlClient(Listener listener) { this.listener = listener; }

    void connect(String host, int port, String token, String clientId) {
        readerThread = new Thread(() -> {
            try {
                Socket s = new Socket();
                socket = s;
                s.connect(new InetSocketAddress(host, port), 5000);
                s.setTcpNoDelay(true);
                s.setSoTimeout(4000);
                BufferedWriter writer = new BufferedWriter(new OutputStreamWriter(s.getOutputStream(), StandardCharsets.UTF_8));
                JSONObject hello = new JSONObject().put("op", "hello").put("version", 1)
                    .put("remote_controls", true)
                    .put("client_id", clientId)
                    .put("token", token).put("device", android.os.Build.MANUFACTURER + " " + android.os.Build.MODEL);
                writer.write(hello.toString()); writer.newLine(); writer.flush();
                writerThread = new Thread(() -> {
                    try {
                        while (!closed.get()) {
                            String line = outbound.take();
                            writer.write(line); writer.newLine(); writer.flush();
                        }
                    } catch (Exception e) { disconnect("Control writer: " + e.getMessage()); }
                }, "dualtheater-writer");
                writerThread.start();
                BufferedReader reader = new BufferedReader(new InputStreamReader(s.getInputStream(), StandardCharsets.UTF_8));
                while (!closed.get()) {
                    // Enforce a limit before allocating an unbounded line.
                    StringBuilder line = new StringBuilder();
                    int c;
                    while ((c = reader.read()) != -1 && c != '\n') {
                        if (line.length() >= 65536) throw new IOException("Oversized control message");
                        line.append((char)c);
                    }
                    if (c == -1) throw new EOFException("Host disconnected");
                    JSONObject msg = new JSONObject(line.toString());
                    if ("ping".equals(msg.optString("op"))) {
                        long t1 = System.nanoTime();
                        send(new JSONObject().put("op", "pong").put("t0", msg.getLong("t0"))
                             .put("t1", t1).put("t2", System.nanoTime()));
                    } else listener.onMessage(msg);
                }
            } catch (Exception e) { disconnect(e.getMessage()); }
        }, "dualtheater-reader");
        readerThread.start();
    }

    void send(JSONObject message) {
        if (!closed.get() && !outbound.offer(message.toString())) disconnect("Control output queue full");
    }

    private void disconnect(String reason) {
        if (closed.compareAndSet(false, true)) {
            try { if (socket != null) socket.close(); } catch (IOException ignored) {}
            if (writerThread != null) writerThread.interrupt();
            listener.onDisconnected(reason == null ? "Disconnected" : reason);
        }
    }

    @Override public void close() { disconnect("Disconnected"); }
}
